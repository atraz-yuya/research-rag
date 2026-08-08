from pathlib import Path
from typing import Any

import pytest

from research_rag import chunking_experiment
from research_rag.chunking_experiment import (
    ChunkingCaseComparison,
    ChunkingExperimentReport,
    format_chunking_experiment_report,
    run_chunking_experiment,
)
from research_rag.evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationSummary,
)
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult


def make_search_result(
    page_number: int,
    rank: int,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=page_number,
            chunk_index=0,
            text=f"Page {page_number}",
        ),
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


def test_runner_reuses_processing_and_query_embeddings_for_both_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (4,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    baseline_chunks = [Chunk("paper.pdf", 1, 0, "Baseline chunk")]
    candidate_chunks = [Chunk("paper.pdf", 1, 0, "Candidate chunk")]
    baseline_embedded = [EmbeddedChunk(baseline_chunks[0], (1.0, 0.0))]
    candidate_embedded = [EmbeddedChunk(candidate_chunks[0], (0.0, 1.0))]
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

    def fake_candidate_chunker(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("candidate_chunker", received_pages))
        return candidate_chunks

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
        return candidate_embedded

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        variant = (
            "baseline" if received_chunks is baseline_embedded else "candidate"
        )
        events.append(("retriever", variant, query_embedding, top_k))
        assert top_k == 3

        if query_embedding == [1.0, 0.0]:
            if variant == "baseline":
                return [make_search_result(2, 1), make_search_result(3, 2)]
            return [make_search_result(3, 1), make_search_result(2, 2)]

        if variant == "baseline":
            return [
                make_search_result(1, 1),
                make_search_result(3, 2),
                make_search_result(5, 3),
            ]
        return [make_search_result(4, 1), make_search_result(5, 2)]

    monkeypatch.setattr(
        chunking_experiment,
        "extract_page_texts",
        fake_extract_page_texts,
    )
    monkeypatch.setattr(
        chunking_experiment,
        "split_pages_into_chunks",
        fake_baseline_chunker,
    )
    monkeypatch.setattr(
        chunking_experiment,
        "split_pages_into_heading_aware_chunks",
        fake_candidate_chunker,
    )
    monkeypatch.setattr(
        chunking_experiment,
        "embed_chunks",
        fake_embed_chunks,
    )
    monkeypatch.setattr(
        chunking_experiment,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )

    report = run_chunking_experiment(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert report.baseline_summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.baseline_summary.hit_at_3_rate == pytest.approx(0.5)
    assert report.baseline_summary.mrr == pytest.approx(0.5)
    assert report.candidate_summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.candidate_summary.hit_at_3_rate == pytest.approx(1.0)
    assert report.candidate_summary.mrr == pytest.approx(0.75)
    assert report.hit_at_1_delta == pytest.approx(0.0)
    assert report.hit_at_3_delta == pytest.approx(0.5)
    assert report.mrr_delta == pytest.approx(0.25)
    assert report.comparisons[0] == ChunkingCaseComparison(
        question="Question one",
        relevant_pages=(2,),
        baseline_retrieved_pages=(2, 3),
        candidate_retrieved_pages=(3, 2),
        baseline_first_relevant_rank=1,
        candidate_first_relevant_rank=2,
    )
    assert report.comparisons[1].baseline_first_relevant_rank is None
    assert report.comparisons[1].candidate_first_relevant_rank == 1
    assert events == [
        ("pdf_reader", pdf_path),
        ("baseline_chunker", pages),
        ("candidate_chunker", pages),
        ("chunk_embedding", baseline_chunks, "embedding-model", client),
        ("chunk_embedding", candidate_chunks, "embedding-model", client),
        ("question_embedding", ["Question one"], "embedding-model"),
        ("retriever", "baseline", [1.0, 0.0], 3),
        ("retriever", "candidate", [1.0, 0.0], 3),
        ("question_embedding", ["Question two"], "embedding-model"),
        ("retriever", "baseline", [0.0, 1.0], 3),
        ("retriever", "candidate", [0.0, 1.0], 3),
    ]
    assert events[6][2] is events[7][2]
    assert events[9][2] is events[10][2]


def test_report_displays_summaries_deltas_and_per_case_comparison() -> None:
    report = ChunkingExperimentReport(
        comparisons=(
            ChunkingCaseComparison(
                question="Question",
                relevant_pages=(20,),
                baseline_retrieved_pages=(29, 12, 4),
                candidate_retrieved_pages=(20, 29, 12),
                baseline_first_relevant_rank=None,
                candidate_first_relevant_rank=1,
            ),
        ),
        baseline_summary=RetrievalEvaluationSummary(1, 0.0, 0.0, 0.0),
        candidate_summary=RetrievalEvaluationSummary(1, 1.0, 1.0, 1.0),
    )

    output = format_chunking_experiment_report(report)

    assert "Baseline\nHit@1 rate: 0.0000" in output
    assert "Candidate\nHit@1 rate: 1.0000" in output
    assert "Delta (Candidate - Baseline)" in output
    assert "Hit@1 delta: +1.0000" in output
    assert "Hit@3 delta: +1.0000" in output
    assert "MRR delta: +1.0000" in output
    assert "relevant_pages: (20,)" in output
    assert "baseline retrieved_pages: (29, 12, 4)" in output
    assert "candidate retrieved_pages: (20, 29, 12)" in output
    assert "baseline first_relevant_rank: None" in output
    assert "candidate first_relevant_rank: 1" in output


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        chunking_experiment,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="experiment cases must not be empty"):
        run_chunking_experiment(Path("paper.pdf"), [])


def test_runner_rejects_empty_embedding_model_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        chunking_experiment,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="embedding_model must not be empty"):
        run_chunking_experiment(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            embedding_model="   ",
        )
