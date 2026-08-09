from pathlib import Path
from typing import Any

import pytest

from research_rag import heading_context_experiment
from research_rag.evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationSummary,
)
from research_rag.heading_context_experiment import (
    HeadingContextCaseComparison,
    HeadingContextExperimentReport,
    HeadingContextVariantResult,
    format_heading_context_experiment_report,
    run_heading_context_experiment,
)
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult


def make_chunk(label: str, page_number: int) -> Chunk:
    return Chunk("paper.pdf", page_number, 0, f"{label} chunk")


def make_result(page_number: int, rank: int) -> SearchResult:
    return SearchResult(
        chunk=make_chunk("result", page_number),
        score=1.0 / rank,
        rank=rank,
    )


class StubClient:
    def __init__(
        self,
        embeddings: dict[str, list[float]],
        events: list[tuple[Any, ...]],
    ) -> None:
        self.embeddings = embeddings
        self.events = events

    def embed_texts(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        embedding = self.embeddings[texts[0]]
        self.events.append(("question_embedding", texts, model, embedding))
        return [embedding]


def test_runner_reuses_processing_and_query_for_all_three_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (4,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    baseline_chunks = [make_chunk("baseline", 1)]
    candidate_v2_chunks = [
        make_chunk("v2-one", 1),
        make_chunk("v2-two", 2),
    ]
    candidate_v3_chunks = [
        make_chunk("v3-one", 1),
        make_chunk("v3-two", 2),
        make_chunk("v3-three", 3),
    ]
    baseline_embedded = [EmbeddedChunk(baseline_chunks[0], (1.0, 0.0))]
    candidate_v2_embedded = [
        EmbeddedChunk(chunk, (0.0, float(index + 1)))
        for index, chunk in enumerate(candidate_v2_chunks)
    ]
    candidate_v3_embedded = [
        EmbeddedChunk(chunk, (float(index + 1), float(index + 1)))
        for index, chunk in enumerate(candidate_v3_chunks)
    ]
    events: list[tuple[Any, ...]] = []
    client = StubClient(
        {
            "Question one": [1.0, 0.0],
            "Question two": [0.0, 1.0],
        },
        events,
    )

    def fake_extract(path: Path) -> list[PageText]:
        events.append(("pdf_reader", path))
        return pages

    def fake_baseline(received: list[PageText]) -> list[Chunk]:
        events.append(("baseline_chunker", received))
        return baseline_chunks

    def fake_v2(received: list[PageText]) -> list[Chunk]:
        events.append(("candidate_v2_chunker", received))
        return candidate_v2_chunks

    def fake_v3(received: list[PageText]) -> list[Chunk]:
        events.append(("candidate_v3_chunker", received))
        return candidate_v3_chunks

    def fake_embed(
        chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        if chunks is baseline_chunks:
            variant = "baseline"
            embedded = baseline_embedded
        elif chunks is candidate_v2_chunks:
            variant = "candidate_v2"
            embedded = candidate_v2_embedded
        else:
            variant = "candidate_v3"
            embedded = candidate_v3_embedded
        events.append(("chunk_embedding", variant, model, received_client))
        return embedded

    def fake_retrieve(
        query: list[float],
        embedded: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        if embedded is baseline_embedded:
            variant = "baseline"
        elif embedded is candidate_v2_embedded:
            variant = "candidate_v2"
        else:
            variant = "candidate_v3"
        events.append(("retriever", variant, query, top_k))
        assert top_k == 3

        if query == [1.0, 0.0]:
            if variant == "baseline":
                return [make_result(2, 1)]
            if variant == "candidate_v2":
                return [make_result(3, 1), make_result(2, 2)]
            return [make_result(2, 1)]

        if variant == "baseline":
            return [make_result(1, 1), make_result(3, 2)]
        if variant == "candidate_v2":
            return [make_result(1, 1), make_result(4, 2)]
        return [make_result(4, 1)]

    monkeypatch.setattr(
        heading_context_experiment,
        "extract_page_texts",
        fake_extract,
    )
    monkeypatch.setattr(
        heading_context_experiment,
        "split_pages_into_chunks",
        fake_baseline,
    )
    monkeypatch.setattr(
        heading_context_experiment,
        "split_pages_into_strict_heading_aware_chunks",
        fake_v2,
    )
    monkeypatch.setattr(
        heading_context_experiment,
        "split_pages_into_heading_context_chunks",
        fake_v3,
    )
    monkeypatch.setattr(heading_context_experiment, "embed_chunks", fake_embed)
    monkeypatch.setattr(
        heading_context_experiment,
        "retrieve_similar_chunks",
        fake_retrieve,
    )

    report = run_heading_context_experiment(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert report.baseline.total_chunk_count == 1
    assert report.candidate_v2.total_chunk_count == 2
    assert report.candidate_v3.total_chunk_count == 3
    assert report.baseline.summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.candidate_v2.summary.hit_at_3_rate == pytest.approx(1.0)
    assert report.candidate_v3.summary.hit_at_1_rate == pytest.approx(1.0)
    assert report.candidate_v3_minus_candidate_v2.mrr == pytest.approx(0.5)
    assert report.comparisons[0] == HeadingContextCaseComparison(
        question="Question one",
        relevant_pages=(2,),
        baseline_retrieved_pages=(2,),
        candidate_v2_retrieved_pages=(3, 2),
        candidate_v3_retrieved_pages=(2,),
        baseline_first_relevant_rank=1,
        candidate_v2_first_relevant_rank=2,
        candidate_v3_first_relevant_rank=1,
    )
    assert [event[0] for event in events].count("pdf_reader") == 1
    assert [event[0] for event in events].count("baseline_chunker") == 1
    assert [event[0] for event in events].count("candidate_v2_chunker") == 1
    assert [event[0] for event in events].count("candidate_v3_chunker") == 1
    assert [event[0] for event in events].count("chunk_embedding") == 3
    assert [event[0] for event in events].count("question_embedding") == 2
    retrievals = [event for event in events if event[0] == "retriever"]
    assert [event[3] for event in retrievals] == [3, 3, 3, 3, 3, 3]
    assert retrievals[0][2] is retrievals[1][2] is retrievals[2][2]
    assert retrievals[3][2] is retrievals[4][2] is retrievals[5][2]


def test_report_displays_metrics_deltas_and_case_comparison() -> None:
    baseline_summary = RetrievalEvaluationSummary(1, 0.0, 0.0, 0.0)
    candidate_v2_summary = RetrievalEvaluationSummary(1, 0.0, 1.0, 0.5)
    candidate_v3_summary = RetrievalEvaluationSummary(1, 1.0, 1.0, 1.0)
    report = HeadingContextExperimentReport(
        comparisons=(
            HeadingContextCaseComparison(
                question="Question",
                relevant_pages=(20,),
                baseline_retrieved_pages=(29, 12, 4),
                candidate_v2_retrieved_pages=(20, 29, 12),
                candidate_v3_retrieved_pages=(20, 12, 4),
                baseline_first_relevant_rank=None,
                candidate_v2_first_relevant_rank=1,
                candidate_v3_first_relevant_rank=1,
            ),
        ),
        baseline=HeadingContextVariantResult(204, baseline_summary),
        candidate_v2=HeadingContextVariantResult(218, candidate_v2_summary),
        candidate_v3=HeadingContextVariantResult(218, candidate_v3_summary),
    )

    output = format_heading_context_experiment_report(report)

    assert "Baseline\ntotal chunk count: 204" in output
    assert "Candidate v2\ntotal chunk count: 218" in output
    assert "Candidate v3\ntotal chunk count: 218" in output
    assert "Candidate v2 - Baseline" in output
    assert "Candidate v3 - Baseline" in output
    assert "Candidate v3 - Candidate v2" in output
    assert "Hit@3 delta: +1.0000" in output
    assert "MRR delta: +0.5000" in output
    assert "baseline retrieved_pages: (29, 12, 4)" in output
    assert "Candidate v2 retrieved_pages: (20, 29, 12)" in output
    assert "Candidate v3 retrieved_pages: (20, 12, 4)" in output
    assert "Candidate v3 first_relevant_rank: 1" in output


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        heading_context_experiment,
        "extract_page_texts",
        lambda path: pytest.fail("PDF must not be processed"),
    )

    with pytest.raises(ValueError, match="experiment cases must not be empty"):
        run_heading_context_experiment(Path("paper.pdf"), [])


def test_runner_rejects_empty_embedding_model_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        heading_context_experiment,
        "extract_page_texts",
        lambda path: pytest.fail("PDF must not be processed"),
    )

    with pytest.raises(ValueError, match="embedding_model must not be empty"):
        run_heading_context_experiment(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            embedding_model="   ",
        )
