from pathlib import Path
from typing import Any

import pytest

from research_rag import strict_heading_diagnostics
from research_rag.evaluation import RetrievalEvaluationCase
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult
from research_rag.strict_heading_diagnostics import (
    StrictHeadingCaseDiagnostic,
    StrictHeadingDiagnosticsReport,
    build_strict_heading_variant_diagnostic,
    format_strict_heading_diagnostics_report,
    run_strict_heading_diagnostics,
    starts_with_strict_heading,
)


def make_chunk(page: int, index: int, text: str) -> Chunk:
    return Chunk("paper.pdf", page, index, text)


def make_result(chunk: Chunk, rank: int, score: float) -> SearchResult:
    return SearchResult(chunk=chunk, rank=rank, score=score)


def test_variant_uses_full_ranking_and_retains_relevant_page_chunks() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    top_chunks = [
        make_chunk(page, 0, f"Top text {page}") for page in range(1, 6)
    ]
    relevant_chunks = [
        make_chunk(20, 1, "4.2 Results\nRelevant second text"),
        make_chunk(20, 0, "Relevant first text"),
    ]
    ranking = [
        make_result(chunk, rank, 1.0 / rank)
        for rank, chunk in enumerate(top_chunks, start=1)
    ]
    ranking.extend(
        [
            make_result(relevant_chunks[1], 6, 0.41),
            make_result(relevant_chunks[0], 7, 0.35),
        ]
    )

    diagnostic = build_strict_heading_variant_diagnostic(
        case,
        ranking,
        relevant_chunks,
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
    page_chunks = diagnostic.relevant_page_chunks[0]
    assert page_chunks.page_number == 20
    assert tuple(chunk.chunk_index for chunk in page_chunks.chunks) == (0, 1)
    first, second = page_chunks.chunks
    assert (first.rank, first.score, first.text) == (
        6,
        pytest.approx(0.41),
        "Relevant first text",
    )
    assert first.character_count == len(first.text)
    assert (second.rank, second.score) == (7, pytest.approx(0.35))
    assert second.starts_with_heading is True


def test_starts_with_heading_uses_candidate_v2_detection() -> None:
    assert starts_with_strict_heading("4.2 Results\nRelevant body text")
    assert starts_with_strict_heading(
        "4.2\nResults\nThe evaluation compares two data sets."
    )
    assert not starts_with_strict_heading("0.7")
    assert not starts_with_strict_heading("Ordinary paragraph text")


def test_variant_retains_all_chunks_from_every_relevant_page() -> None:
    case = RetrievalEvaluationCase("Question", (20, 21))
    relevant_chunks = [
        make_chunk(20, 0, "Page 20 first"),
        make_chunk(20, 1, "Page 20 second"),
        make_chunk(21, 0, "5 Results\nPage 21 first"),
    ]
    ranking = [
        make_result(chunk, rank, 1.0 / rank)
        for rank, chunk in enumerate(relevant_chunks, start=4)
    ]

    diagnostic = build_strict_heading_variant_diagnostic(
        case,
        ranking,
        relevant_chunks,
    )

    assert tuple(
        page.page_number for page in diagnostic.relevant_page_chunks
    ) == (20, 21)
    assert tuple(
        chunk.chunk_index
        for chunk in diagnostic.relevant_page_chunks[0].chunks
    ) == (0, 1)
    assert tuple(
        chunk.chunk_index
        for chunk in diagnostic.relevant_page_chunks[1].chunks
    ) == (0,)
    assert diagnostic.relevant_page_chunks[1].chunks[0].rank == 6
    assert diagnostic.relevant_page_chunks[1].chunks[0].starts_with_heading


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


def test_runner_reuses_pdf_chunk_embeddings_and_query_embeddings(
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
        make_chunk(2, 0, "4.2 Candidate\ncandidate two body"),
        make_chunk(2, 1, "candidate three"),
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
    client = StubClient(
        {
            "Question one": [1.0, 0.0],
            "Question two": [0.0, 1.0],
        },
        events,
    )

    def fake_extract(path: Path) -> list[PageText]:
        events.append(("pdf", path))
        return pages

    def fake_baseline(received: list[PageText]) -> list[Chunk]:
        events.append(("baseline_chunker", received))
        return baseline_chunks

    def fake_candidate(received: list[PageText]) -> list[Chunk]:
        events.append(("v2_chunker", received))
        return candidate_chunks

    def fake_embed(
        chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        variant = "baseline" if chunks is baseline_chunks else "v2"
        events.append(("chunk_embedding", variant, model, received_client))
        return (
            baseline_embedded
            if variant == "baseline"
            else candidate_embedded
        )

    def fake_retrieve(
        query: list[float],
        chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        variant = "baseline" if chunks is baseline_embedded else "v2"
        events.append(("retriever", variant, query, top_k))
        return [
            make_result(item.chunk, rank, 1.0 / rank)
            for rank, item in enumerate(chunks, start=1)
        ]

    monkeypatch.setattr(
        strict_heading_diagnostics,
        "extract_page_texts",
        fake_extract,
    )
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "split_pages_into_chunks",
        fake_baseline,
    )
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "split_pages_into_strict_heading_aware_chunks",
        fake_candidate,
    )
    monkeypatch.setattr(strict_heading_diagnostics, "embed_chunks", fake_embed)
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "retrieve_similar_chunks",
        fake_retrieve,
    )

    report = run_strict_heading_diagnostics(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert len(report.cases) == 2
    assert [event[0] for event in events].count("pdf") == 1
    assert [event[0] for event in events].count("baseline_chunker") == 1
    assert [event[0] for event in events].count("v2_chunker") == 1
    assert [event[:2] for event in events if event[0] == "chunk_embedding"] == [
        ("chunk_embedding", "baseline"),
        ("chunk_embedding", "v2"),
    ]
    assert [event[0] for event in events].count("question_embedding") == 2
    retrieval_events = [event for event in events if event[0] == "retriever"]
    assert [event[3] for event in retrieval_events] == [2, 3, 2, 3]
    assert retrieval_events[0][2] is retrieval_events[1][2]
    assert retrieval_events[2][2] is retrieval_events[3][2]


def test_report_compares_baseline_and_candidate_v2_boundaries() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    baseline_chunk = make_chunk(20, 0, "Context before heading and answer")
    candidate_chunk = make_chunk(20, 0, "4.2 Results\nAnswer")
    baseline = build_strict_heading_variant_diagnostic(
        case,
        [make_result(baseline_chunk, 6, 0.4)],
        [baseline_chunk],
    )
    candidate = build_strict_heading_variant_diagnostic(
        case,
        [make_result(candidate_chunk, 1, 0.8)],
        [candidate_chunk],
    )
    report = StrictHeadingDiagnosticsReport(
        cases=(
            StrictHeadingCaseDiagnostic(
                question=case.question,
                relevant_pages=case.relevant_pages,
                baseline=baseline,
                candidate_v2=candidate,
            ),
        )
    )

    output = format_strict_heading_diagnostics_report(report)

    assert "question: Question" in output
    assert "relevant_pages: (20,)" in output
    assert "Baseline:" in output
    assert "Candidate v2:" in output
    assert "first_relevant_rank: 6" in output
    assert "best_relevant_score: 0.400000" in output
    assert "Top results:" in output
    assert "Relevant page chunks:" in output
    assert "rank=6 document_name=paper.pdf page_number=20" in output
    assert "chunk_index=0 score=0.400000 character_count=33" in output
    assert "starts_with_heading=False" in output
    assert "text: Context before heading and answer" in output
    assert "starts_with_heading=True" in output
    assert "text: 4.2 Results\nAnswer" in output


@pytest.mark.parametrize("top_n", [0, -1])
def test_runner_rejects_invalid_top_n_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
    top_n: int,
) -> None:
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "extract_page_texts",
        lambda path: pytest.fail("PDF must not be processed"),
    )

    with pytest.raises(ValueError, match="top_n must be greater than 0"):
        run_strict_heading_diagnostics(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            top_n=top_n,
        )


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "extract_page_texts",
        lambda path: pytest.fail("PDF must not be processed"),
    )

    with pytest.raises(ValueError, match="diagnostic cases must not be empty"):
        run_strict_heading_diagnostics(Path("paper.pdf"), [])


def test_runner_rejects_empty_embedding_model_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        strict_heading_diagnostics,
        "extract_page_texts",
        lambda path: pytest.fail("PDF must not be processed"),
    )

    with pytest.raises(ValueError, match="embedding_model must not be empty"):
        run_strict_heading_diagnostics(
            Path("paper.pdf"),
            [RetrievalEvaluationCase("Question", (1,))],
            embedding_model="   ",
        )
