from pathlib import Path
from typing import Any

import pytest

from research_rag import retrieval_diagnostics
from research_rag.evaluation import RetrievalEvaluationCase
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult
from research_rag.retrieval_diagnostics import (
    RetrievalDiagnosticsReport,
    build_retrieval_diagnostic,
    format_retrieval_diagnostics_report,
    run_retrieval_diagnostics,
)


def make_search_result(
    rank: int,
    page_number: int,
    *,
    chunk_index: int = 0,
    score: float | None = None,
    text: str | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=page_number,
            chunk_index=chunk_index,
            text=text or f"Page {page_number}, chunk {chunk_index}",
        ),
        score=score if score is not None else 1.0 / rank,
        rank=rank,
    )


def test_diagnostic_keeps_only_requested_number_of_top_results() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    full_ranking = [
        make_search_result(rank, page_number=rank)
        for rank in range(1, 6)
    ]

    diagnostic = build_retrieval_diagnostic(case, full_ranking, top_n=3)

    assert tuple(result.rank for result in diagnostic.top_results) == (1, 2, 3)


def test_diagnostic_finds_first_relevant_rank_outside_top_results() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    full_ranking = [
        make_search_result(rank, page_number=rank)
        for rank in range(1, 11)
    ]
    relevant_result = make_search_result(11, page_number=20)
    full_ranking.append(relevant_result)

    diagnostic = build_retrieval_diagnostic(case, full_ranking, top_n=10)

    assert diagnostic.first_relevant_rank == 11
    assert relevant_result not in diagnostic.top_results
    assert diagnostic.relevant_matches == (relevant_result,)


def test_diagnostic_preserves_all_relevant_chunks_and_their_fields() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    first_match = make_search_result(
        12,
        page_number=20,
        chunk_index=0,
        score=0.42,
        text="First relevant chunk",
    )
    second_match = make_search_result(
        14,
        page_number=20,
        chunk_index=1,
        score=0.38,
        text="Second relevant chunk",
    )

    diagnostic = build_retrieval_diagnostic(
        case,
        [second_match, make_search_result(1, 29), first_match],
        top_n=1,
    )

    assert diagnostic.first_relevant_rank == 12
    assert diagnostic.relevant_matches == (first_match, second_match)
    assert diagnostic.relevant_matches[0].rank == 12
    assert diagnostic.relevant_matches[0].chunk.document_name == "paper.pdf"
    assert diagnostic.relevant_matches[0].chunk.page_number == 20
    assert diagnostic.relevant_matches[0].chunk.chunk_index == 0
    assert diagnostic.relevant_matches[0].score == pytest.approx(0.42)
    assert diagnostic.relevant_matches[0].chunk.text == "First relevant chunk"


def test_diagnostic_handles_missing_relevant_page() -> None:
    diagnostic = build_retrieval_diagnostic(
        RetrievalEvaluationCase("Question", (20,)),
        [make_search_result(1, 29)],
    )

    assert diagnostic.first_relevant_rank is None
    assert diagnostic.relevant_matches == ()


def test_report_displays_top_results_and_relevant_matches() -> None:
    top_result = make_search_result(
        1,
        page_number=29,
        chunk_index=2,
        score=0.91,
        text="Top chunk text",
    )
    relevant_result = make_search_result(
        17,
        page_number=20,
        chunk_index=1,
        score=0.51,
        text="Relevant chunk text",
    )
    diagnostic = build_retrieval_diagnostic(
        RetrievalEvaluationCase("Dataset question", (20,)),
        [top_result, relevant_result],
        top_n=1,
    )

    output = format_retrieval_diagnostics_report(
        RetrievalDiagnosticsReport((diagnostic,))
    )

    assert "question: Dataset question" in output
    assert "relevant_pages: (20,)" in output
    assert "first_relevant_rank: 17" in output
    assert "Top results:" in output
    assert "rank=1 document_name=paper.pdf page_number=29" in output
    assert "chunk_index=2 score=0.910000" in output
    assert "text: Top chunk text" in output
    assert "Relevant matches:" in output
    assert "rank=17 document_name=paper.pdf page_number=20" in output
    assert "chunk_index=1 score=0.510000" in output
    assert "text: Relevant chunk text" in output


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


def test_runner_reuses_pdf_and_chunk_embeddings_and_requests_full_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Case 4 question", (9,)),
        RetrievalEvaluationCase("Case 8 question", (20,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [
        Chunk("paper.pdf", 1, 0, "First chunk"),
        Chunk("paper.pdf", 2, 0, "Second chunk"),
    ]
    embedded_chunks = [
        EmbeddedChunk(chunks[0], (1.0, 0.0)),
        EmbeddedChunk(chunks[1], (0.0, 1.0)),
    ]
    events: list[tuple[Any, ...]] = []
    client = StubDiagnosticsClient(
        {
            "Case 4 question": [1.0, 0.0],
            "Case 8 question": [0.0, 1.0],
        },
        events,
    )

    def fake_extract_page_texts(received_path: Path) -> list[PageText]:
        events.append(("pdf_reader", received_path))
        return pages

    def fake_split_pages_into_chunks(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("chunker", received_pages))
        return chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        events.append(
            ("chunk_embedding", received_chunks, model, received_client)
        )
        return embedded_chunks

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        events.append(
            ("retriever", query_embedding, received_chunks, top_k)
        )
        assert top_k == len(embedded_chunks)
        if query_embedding == [1.0, 0.0]:
            return [make_search_result(1, 2), make_search_result(2, 9)]
        return [make_search_result(1, 29), make_search_result(2, 20)]

    monkeypatch.setattr(
        retrieval_diagnostics,
        "extract_page_texts",
        fake_extract_page_texts,
    )
    monkeypatch.setattr(
        retrieval_diagnostics,
        "split_pages_into_chunks",
        fake_split_pages_into_chunks,
    )
    monkeypatch.setattr(
        retrieval_diagnostics,
        "embed_chunks",
        fake_embed_chunks,
    )
    monkeypatch.setattr(
        retrieval_diagnostics,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )

    report = run_retrieval_diagnostics(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        top_n=1,
        client=client,
    )

    assert len(report.diagnostics) == 2
    assert report.diagnostics[0].first_relevant_rank == 2
    assert report.diagnostics[1].first_relevant_rank == 2
    assert events == [
        ("pdf_reader", pdf_path),
        ("chunker", pages),
        ("chunk_embedding", chunks, "embedding-model", client),
        ("question_embedding", ["Case 4 question"], "embedding-model"),
        ("retriever", [1.0, 0.0], embedded_chunks, 2),
        ("question_embedding", ["Case 8 question"], "embedding-model"),
        ("retriever", [0.0, 1.0], embedded_chunks, 2),
    ]


def test_build_diagnostic_rejects_invalid_top_n() -> None:
    with pytest.raises(ValueError, match="top_n must be greater than 0"):
        build_retrieval_diagnostic(
            RetrievalEvaluationCase("Question", (1,)),
            [],
            top_n=0,
        )


def test_runner_rejects_invalid_top_n_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        retrieval_diagnostics,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="top_n must be greater than 0"):
        run_retrieval_diagnostics(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            embedding_model="embedding-model",
            top_n=0,
        )


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(
        retrieval_diagnostics,
        "extract_page_texts",
        fail_extract,
    )

    with pytest.raises(ValueError, match="diagnostic cases must not be empty"):
        run_retrieval_diagnostics(
            Path("paper.pdf"),
            [],
            embedding_model="embedding-model",
        )
