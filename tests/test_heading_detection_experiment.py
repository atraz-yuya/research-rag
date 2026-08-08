from pathlib import Path
from typing import Any

import pytest

from research_rag import heading_detection_experiment
from research_rag.evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationSummary,
)
from research_rag.heading_detection_experiment import (
    HeadingDetectionCaseComparison,
    HeadingDetectionExperimentReport,
    HeadingVariantResult,
    format_heading_detection_experiment_report,
    run_heading_detection_experiment,
)
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult


def make_chunk(label: str, page_number: int) -> Chunk:
    return Chunk("paper.pdf", page_number, 0, f"{label} chunk")


def make_search_result(page_number: int, rank: int) -> SearchResult:
    return SearchResult(
        chunk=make_chunk("result", page_number),
        score=1.0 / rank,
        rank=rank,
    )


class StubExperimentClient:
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
        self.events.append(("question_embedding", texts, model))
        return [self.embeddings[texts[0]]]


def test_runner_reuses_processing_and_query_embedding_for_three_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (4,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    baseline_chunks = [make_chunk("baseline", 1)]
    candidate_v1_chunks = [
        make_chunk("v1-one", 1),
        make_chunk("v1-two", 2),
    ]
    candidate_v2_chunks = [
        make_chunk("v2-one", 1),
        make_chunk("v2-two", 2),
        make_chunk("v2-three", 3),
    ]
    baseline_embedded = [EmbeddedChunk(baseline_chunks[0], (1.0, 0.0))]
    candidate_v1_embedded = [
        EmbeddedChunk(chunk, (0.0, float(index + 1)))
        for index, chunk in enumerate(candidate_v1_chunks)
    ]
    candidate_v2_embedded = [
        EmbeddedChunk(chunk, (float(index + 1), float(index + 1)))
        for index, chunk in enumerate(candidate_v2_chunks)
    ]
    events: list[tuple[Any, ...]] = []
    client = StubExperimentClient(
        {
            "Question one": [1.0, 0.0],
            "Question two": [0.0, 1.0],
        },
        events,
    )

    def fake_extract_page_texts(received_path: Path) -> list[PageText]:
        events.append(("pdf_reader", received_path))
        return pages

    def fake_baseline_chunker(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("baseline_chunker", received_pages))
        return baseline_chunks

    def fake_candidate_v1_chunker(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("candidate_v1_chunker", received_pages))
        return candidate_v1_chunks

    def fake_candidate_v2_chunker(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("candidate_v2_chunker", received_pages))
        return candidate_v2_chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        events.append(
            ("chunk_embedding", received_chunks, model, received_client)
        )
        if received_chunks is baseline_chunks:
            return baseline_embedded
        if received_chunks is candidate_v1_chunks:
            return candidate_v1_embedded
        return candidate_v2_embedded

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        if received_chunks is baseline_embedded:
            variant = "baseline"
        elif received_chunks is candidate_v1_embedded:
            variant = "candidate_v1"
        else:
            variant = "candidate_v2"
        events.append(("retriever", variant, query_embedding, top_k))
        assert top_k == 3

        if query_embedding == [1.0, 0.0]:
            if variant == "baseline":
                return [make_search_result(2, 1)]
            if variant == "candidate_v1":
                return [make_search_result(3, 1), make_search_result(2, 2)]
            return [make_search_result(2, 1)]

        if variant == "baseline":
            return [make_search_result(1, 1), make_search_result(3, 2)]
        return [make_search_result(4, 1)]

    monkeypatch.setattr(
        heading_detection_experiment,
        "extract_page_texts",
        fake_extract_page_texts,
    )
    monkeypatch.setattr(
        heading_detection_experiment,
        "split_pages_into_chunks",
        fake_baseline_chunker,
    )
    monkeypatch.setattr(
        heading_detection_experiment,
        "split_pages_into_heading_aware_chunks",
        fake_candidate_v1_chunker,
    )
    monkeypatch.setattr(
        heading_detection_experiment,
        "split_pages_into_strict_heading_aware_chunks",
        fake_candidate_v2_chunker,
    )
    monkeypatch.setattr(
        heading_detection_experiment,
        "embed_chunks",
        fake_embed_chunks,
    )
    monkeypatch.setattr(
        heading_detection_experiment,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )

    report = run_heading_detection_experiment(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert report.baseline.total_chunk_count == 1
    assert report.candidate_v1.total_chunk_count == 2
    assert report.candidate_v2.total_chunk_count == 3
    assert report.baseline.summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.candidate_v1.summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.candidate_v2.summary.hit_at_1_rate == pytest.approx(1.0)
    assert report.baseline.summary.hit_at_3_rate == pytest.approx(0.5)
    assert report.candidate_v1.summary.hit_at_3_rate == pytest.approx(1.0)
    assert report.candidate_v2.summary.hit_at_3_rate == pytest.approx(1.0)
    assert report.baseline.summary.mrr == pytest.approx(0.5)
    assert report.candidate_v1.summary.mrr == pytest.approx(0.75)
    assert report.candidate_v2.summary.mrr == pytest.approx(1.0)
    assert report.candidate_v1_minus_baseline.hit_at_3 == pytest.approx(0.5)
    assert report.candidate_v2_minus_baseline.mrr == pytest.approx(0.5)
    assert report.candidate_v2_minus_candidate_v1.mrr == pytest.approx(0.25)
    assert report.comparisons[0] == HeadingDetectionCaseComparison(
        question="Question one",
        relevant_pages=(2,),
        baseline_retrieved_pages=(2,),
        candidate_v1_retrieved_pages=(3, 2),
        candidate_v2_retrieved_pages=(2,),
        baseline_first_relevant_rank=1,
        candidate_v1_first_relevant_rank=2,
        candidate_v2_first_relevant_rank=1,
    )
    assert events == [
        ("pdf_reader", pdf_path),
        ("baseline_chunker", pages),
        ("candidate_v1_chunker", pages),
        ("candidate_v2_chunker", pages),
        ("chunk_embedding", baseline_chunks, "embedding-model", client),
        ("chunk_embedding", candidate_v1_chunks, "embedding-model", client),
        ("chunk_embedding", candidate_v2_chunks, "embedding-model", client),
        ("question_embedding", ["Question one"], "embedding-model"),
        ("retriever", "baseline", [1.0, 0.0], 3),
        ("retriever", "candidate_v1", [1.0, 0.0], 3),
        ("retriever", "candidate_v2", [1.0, 0.0], 3),
        ("question_embedding", ["Question two"], "embedding-model"),
        ("retriever", "baseline", [0.0, 1.0], 3),
        ("retriever", "candidate_v1", [0.0, 1.0], 3),
        ("retriever", "candidate_v2", [0.0, 1.0], 3),
    ]
    assert events[8][2] is events[9][2] is events[10][2]
    assert events[12][2] is events[13][2] is events[14][2]


def test_report_displays_variants_deltas_and_per_case_results() -> None:
    baseline_summary = RetrievalEvaluationSummary(1, 0.0, 0.0, 0.0)
    candidate_v1_summary = RetrievalEvaluationSummary(1, 0.0, 1.0, 0.5)
    candidate_v2_summary = RetrievalEvaluationSummary(1, 1.0, 1.0, 1.0)
    report = HeadingDetectionExperimentReport(
        comparisons=(
            HeadingDetectionCaseComparison(
                question="Question",
                relevant_pages=(20,),
                baseline_retrieved_pages=(29, 12, 4),
                candidate_v1_retrieved_pages=(20, 29, 12),
                candidate_v2_retrieved_pages=(20, 12, 4),
                baseline_first_relevant_rank=None,
                candidate_v1_first_relevant_rank=1,
                candidate_v2_first_relevant_rank=1,
            ),
        ),
        baseline=HeadingVariantResult(35, baseline_summary),
        candidate_v1=HeadingVariantResult(50, candidate_v1_summary),
        candidate_v2=HeadingVariantResult(40, candidate_v2_summary),
    )

    output = format_heading_detection_experiment_report(report)

    assert "Baseline\ntotal chunk count: 35" in output
    assert "Candidate v1\ntotal chunk count: 50" in output
    assert "Candidate v2\ntotal chunk count: 40" in output
    assert "Candidate v1 - Baseline" in output
    assert "Candidate v2 - Baseline" in output
    assert "Candidate v2 - Candidate v1" in output
    assert "Hit@1 delta: +1.0000" in output
    assert "MRR delta: +0.5000" in output
    assert "relevant_pages: (20,)" in output
    assert "baseline retrieved_pages: (29, 12, 4)" in output
    assert "Candidate v1 retrieved_pages: (20, 29, 12)" in output
    assert "Candidate v2 retrieved_pages: (20, 12, 4)" in output
    assert "baseline first_relevant_rank: None" in output
    assert "Candidate v1 first_relevant_rank: 1" in output
    assert "Candidate v2 first_relevant_rank: 1" in output


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        heading_detection_experiment,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="experiment cases must not be empty"):
        run_heading_detection_experiment(Path("paper.pdf"), [])


def test_runner_rejects_empty_embedding_model_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        heading_detection_experiment,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="embedding_model must not be empty"):
        run_heading_detection_experiment(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            embedding_model="   ",
        )
