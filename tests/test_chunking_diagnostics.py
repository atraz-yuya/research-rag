from pathlib import Path
from typing import Any

import pytest

from research_rag import chunking_diagnostics
from research_rag.chunking_diagnostics import (
    ChunkingCaseDiagnostic,
    ChunkingDiagnosticsReport,
    build_chunking_variant_diagnostic,
    calculate_chunk_statistics,
    format_chunking_diagnostics_report,
    run_chunking_diagnostics,
)
from research_rag.evaluation import RetrievalEvaluationCase
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult


def make_chunk(
    page_number: int,
    chunk_index: int,
    text: str,
) -> Chunk:
    return Chunk("paper.pdf", page_number, chunk_index, text)


def make_search_result(
    rank: int,
    page_number: int,
    *,
    chunk_index: int = 0,
    score: float | None = None,
    text: str | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=make_chunk(
            page_number,
            chunk_index,
            text or f"Page {page_number}, chunk {chunk_index}",
        ),
        score=score if score is not None else 1.0 / rank,
        rank=rank,
    )


def test_variant_diagnostic_uses_full_ranking_and_preserves_chunk_details() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    full_ranking = [
        make_search_result(rank, page_number=rank)
        for rank in range(1, 6)
    ]
    first_relevant = make_search_result(
        6,
        20,
        chunk_index=0,
        score=0.41,
        text="First relevant text",
    )
    second_relevant = make_search_result(
        7,
        20,
        chunk_index=1,
        score=0.35,
        text="Second relevant text",
    )
    full_ranking.extend([first_relevant, second_relevant])
    page_chunks = [
        make_chunk(20, 1, "Second relevant text"),
        make_chunk(20, 0, "First relevant text"),
        make_chunk(21, 0, "Other page"),
    ]

    diagnostic = build_chunking_variant_diagnostic(
        case,
        full_ranking,
        page_chunks,
        top_n=5,
    )

    assert tuple(result.rank for result in diagnostic.top_results) == (
        1,
        2,
        3,
        4,
        5,
    )
    assert diagnostic.first_relevant_rank == 6
    assert diagnostic.best_relevant_score == pytest.approx(0.41)
    assert tuple(result.rank for result in diagnostic.relevant_matches) == (
        6,
        7,
    )
    relevant = diagnostic.relevant_matches[0]
    assert relevant.rank == 6
    assert relevant.page_number == 20
    assert relevant.chunk_index == 0
    assert relevant.score == pytest.approx(0.41)
    assert relevant.character_count == len("First relevant text")
    assert relevant.text == "First relevant text"
    assert diagnostic.relevant_page_chunks[0].page_number == 20
    assert [
        chunk.chunk_index
        for chunk in diagnostic.relevant_page_chunks[0].chunks
    ] == [0, 1]
    assert [
        chunk.text for chunk in diagnostic.relevant_page_chunks[0].chunks
    ] == ["First relevant text", "Second relevant text"]


def test_chunk_statistics_include_count_and_length_distribution() -> None:
    chunk_statistics = calculate_chunk_statistics(
        [
            make_chunk(1, 0, "ab"),
            make_chunk(1, 1, "abcd"),
            make_chunk(2, 0, "abcdefgh"),
            make_chunk(2, 1, "abcdefghij"),
        ]
    )

    assert chunk_statistics.total_chunk_count == 4
    assert chunk_statistics.minimum_chunk_length == 2
    assert chunk_statistics.maximum_chunk_length == 10
    assert chunk_statistics.mean_chunk_length == pytest.approx(6.0)
    assert chunk_statistics.median_chunk_length == pytest.approx(6.0)


def test_chunk_statistics_reject_empty_chunks() -> None:
    with pytest.raises(ValueError, match="chunks must not be empty"):
        calculate_chunk_statistics([])


class StubDiagnosticsClient:
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


def test_runner_reuses_processing_and_gets_full_rankings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (1,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    baseline_chunks = [
        make_chunk(1, 0, "baseline one"),
        make_chunk(2, 0, "baseline two"),
    ]
    candidate_chunks = [
        make_chunk(1, 0, "candidate one"),
        make_chunk(1, 1, "candidate two"),
        make_chunk(2, 0, "candidate three"),
    ]
    baseline_embedded = [
        EmbeddedChunk(chunk, (float(index + 1), 0.0))
        for index, chunk in enumerate(baseline_chunks)
    ]
    candidate_embedded = [
        EmbeddedChunk(chunk, (0.0, float(index + 1)))
        for index, chunk in enumerate(candidate_chunks)
    ]
    events: list[tuple[Any, ...]] = []
    client = StubDiagnosticsClient(
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
        assert top_k == len(received_chunks)

        if query_embedding == [1.0, 0.0]:
            if variant == "baseline":
                return [make_search_result(1, 1), make_search_result(2, 2)]
            return [
                make_search_result(1, 1),
                make_search_result(2, 2),
                make_search_result(3, 3),
            ]

        if variant == "baseline":
            return [make_search_result(1, 1), make_search_result(2, 2)]
        return [
            make_search_result(1, 1),
            make_search_result(2, 2),
            make_search_result(3, 3),
        ]

    monkeypatch.setattr(
        chunking_diagnostics,
        "extract_page_texts",
        fake_extract_page_texts,
    )
    monkeypatch.setattr(
        chunking_diagnostics,
        "split_pages_into_chunks",
        fake_baseline_chunker,
    )
    monkeypatch.setattr(
        chunking_diagnostics,
        "split_pages_into_heading_aware_chunks",
        fake_candidate_chunker,
    )
    monkeypatch.setattr(
        chunking_diagnostics,
        "embed_chunks",
        fake_embed_chunks,
    )
    monkeypatch.setattr(
        chunking_diagnostics,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )

    report = run_chunking_diagnostics(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        top_n=1,
        client=client,
    )

    assert report.baseline_statistics.total_chunk_count == 2
    assert report.candidate_statistics.total_chunk_count == 3
    assert len(report.cases) == 2
    assert report.cases[0].baseline.first_relevant_rank == 2
    assert report.cases[0].candidate.first_relevant_rank == 2
    assert events == [
        ("pdf_reader", pdf_path),
        ("baseline_chunker", pages),
        ("candidate_chunker", pages),
        ("chunk_embedding", baseline_chunks, "embedding-model", client),
        ("chunk_embedding", candidate_chunks, "embedding-model", client),
        ("question_embedding", ["Question one"], "embedding-model"),
        ("retriever", "baseline", [1.0, 0.0], 2),
        ("retriever", "candidate", [1.0, 0.0], 3),
        ("question_embedding", ["Question two"], "embedding-model"),
        ("retriever", "baseline", [0.0, 1.0], 2),
        ("retriever", "candidate", [0.0, 1.0], 3),
    ]
    assert events[6][2] is events[7][2]
    assert events[9][2] is events[10][2]


def test_report_displays_rankings_page_chunks_and_statistics() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    baseline_chunks = [make_chunk(20, 0, "baseline chunk")]
    candidate_chunks = [
        make_chunk(20, 0, "candidate one"),
        make_chunk(20, 1, "candidate two"),
    ]
    baseline = build_chunking_variant_diagnostic(
        case,
        [make_search_result(6, 20, score=0.4, text="baseline chunk")],
        baseline_chunks,
        top_n=5,
    )
    candidate = build_chunking_variant_diagnostic(
        case,
        [make_search_result(1, 20, score=0.8, text="candidate one")],
        candidate_chunks,
        top_n=5,
    )
    report = ChunkingDiagnosticsReport(
        baseline_statistics=calculate_chunk_statistics(baseline_chunks),
        candidate_statistics=calculate_chunk_statistics(candidate_chunks),
        cases=(
            ChunkingCaseDiagnostic(
                question=case.question,
                relevant_pages=case.relevant_pages,
                baseline=baseline,
                candidate=candidate,
            ),
        ),
    )

    output = format_chunking_diagnostics_report(report)

    assert "Chunk statistics" in output
    assert "total_chunk_count: 1" in output
    assert "minimum_chunk_length:" in output
    assert "maximum_chunk_length:" in output
    assert "mean_chunk_length:" in output
    assert "median_chunk_length:" in output
    assert "question: Question" in output
    assert "relevant_pages: (20,)" in output
    assert "Baseline:" in output
    assert "Candidate:" in output
    assert "first_relevant_rank: 6" in output
    assert "best_relevant_score: 0.400000" in output
    assert "Top results:" in output
    assert "Relevant matches:" in output
    assert "rank=6 page_number=20 chunk_index=0 score=0.400000" in output
    assert "character_count=14" in output
    assert "text: baseline chunk" in output
    assert "Relevant page chunks:" in output
    assert "Page 20: 1 chunks" in output
    assert "Page 20: 2 chunks" in output
    assert "      chunk_index=0 character_count=14" in output
    assert "      text: baseline chunk" in output
    assert "      chunk_index=1 character_count=13" in output
    assert "      text: candidate two" in output


def test_runner_rejects_invalid_top_n_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        chunking_diagnostics,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="top_n must be greater than 0"):
        run_chunking_diagnostics(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            top_n=0,
        )


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        chunking_diagnostics,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="diagnostic cases must not be empty"):
        run_chunking_diagnostics(Path("paper.pdf"), [])
