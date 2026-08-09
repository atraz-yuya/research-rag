from pathlib import Path
from typing import Any

import pytest

from research_rag import query_variant_diagnostics
from research_rag.evaluation import RetrievalEvaluationCase
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult
from research_rag.query_variant_diagnostics import (
    RetrievalQueryVariant,
    RetrievalQueryVariantCase,
    RetrievalQueryVariantDiagnosticsReport,
    build_query_variant_diagnostic,
    compare_query_variant_diagnostics,
    format_query_variant_diagnostics_report,
    run_query_variant_diagnostics,
)


def make_result(
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


def test_diagnostic_uses_full_ranking_beyond_top_five() -> None:
    case = RetrievalEvaluationCase("Original question", (20,))
    variant = RetrievalQueryVariant("english", "English question")
    first_relevant = make_result(
        7,
        20,
        chunk_index=0,
        score=0.41,
        text="Direct answer",
    )
    second_relevant = make_result(
        9,
        20,
        chunk_index=1,
        score=0.35,
        text="Supporting context",
    )
    full_ranking = [
        make_result(rank, rank)
        for rank in range(1, 7)
    ] + [first_relevant, make_result(8, 30), second_relevant]

    diagnostic = build_query_variant_diagnostic(
        case,
        variant,
        full_ranking,
    )

    assert diagnostic.variant_label == "english"
    assert diagnostic.query == "English question"
    assert diagnostic.relevant_pages == (20,)
    assert diagnostic.first_relevant_rank == 7
    assert diagnostic.best_relevant_score == pytest.approx(0.41)
    assert diagnostic.hit_at_3 is False
    assert tuple(item.rank for item in diagnostic.top_results) == (
        1,
        2,
        3,
        4,
        5,
    )
    assert tuple(item.rank for item in diagnostic.relevant_chunks) == (7, 9)
    assert diagnostic.relevant_chunks[0].document_name == "paper.pdf"
    assert diagnostic.relevant_chunks[0].page_number == 20
    assert diagnostic.relevant_chunks[0].chunk_index == 0
    assert diagnostic.relevant_chunks[0].score == pytest.approx(0.41)
    assert diagnostic.relevant_chunks[0].character_count == len(
        "Direct answer"
    )
    assert diagnostic.relevant_chunks[0].text == "Direct answer"


def test_diagnostic_supports_multiple_relevant_pages() -> None:
    diagnostic = build_query_variant_diagnostic(
        RetrievalEvaluationCase("Question", (20, 21)),
        RetrievalQueryVariant("short", "Short question"),
        [
            make_result(1, 30),
            make_result(2, 21, chunk_index=1),
            make_result(3, 20, chunk_index=0),
        ],
    )

    assert diagnostic.first_relevant_rank == 2
    assert diagnostic.best_relevant_score == pytest.approx(0.5)
    assert tuple(item.page_number for item in diagnostic.relevant_chunks) == (
        21,
        20,
    )


def test_variant_comparison_reports_rank_score_and_top_page_changes() -> None:
    case = RetrievalEvaluationCase("Question", (20,))
    reference = build_query_variant_diagnostic(
        case,
        RetrievalQueryVariant("original", "Original"),
        [
            make_result(1, 10, score=0.9),
            make_result(2, 11, score=0.8),
            make_result(3, 12, score=0.7),
            make_result(4, 13, score=0.6),
            make_result(5, 14, score=0.5),
            make_result(6, 20, score=0.4),
        ],
    )
    candidate = build_query_variant_diagnostic(
        case,
        RetrievalQueryVariant("concise", "Concise"),
        [
            make_result(1, 20, score=0.7),
            make_result(2, 11, score=0.65),
            make_result(3, 12, score=0.6),
            make_result(4, 15, score=0.55),
            make_result(5, 16, score=0.5),
            make_result(6, 10, score=0.45),
        ],
    )

    comparison = compare_query_variant_diagnostics(reference, candidate)

    assert comparison.reference_label == "original"
    assert comparison.variant_label == "concise"
    assert comparison.reference_first_relevant_rank == 6
    assert comparison.variant_first_relevant_rank == 1
    assert comparison.reference_best_relevant_score == pytest.approx(0.4)
    assert comparison.variant_best_relevant_score == pytest.approx(0.7)
    assert comparison.best_relevant_score_delta == pytest.approx(0.3)
    assert comparison.reference_hit_at_3 is False
    assert comparison.variant_hit_at_3 is True
    assert comparison.top_n_page_overlap == (11, 12)
    assert comparison.removed_top_n_pages == (10, 13, 14)
    assert comparison.added_top_n_pages == (20, 15, 16)


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
        self.events.append(("query_embedding", texts, model))
        return [self.embeddings[texts[0]]]


def test_runner_reuses_document_work_and_embeds_each_variant_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalQueryVariantCase(
            RetrievalEvaluationCase("Case A", (2,)),
            (
                RetrievalQueryVariant("ja", "質問A"),
                RetrievalQueryVariant("en", "Question A"),
            ),
        ),
        RetrievalQueryVariantCase(
            RetrievalEvaluationCase("Case B", (3,)),
            (RetrievalQueryVariant("short", "Question B"),),
        ),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [
        Chunk("paper.pdf", 1, 0, "First"),
        Chunk("paper.pdf", 2, 0, "Second"),
        Chunk("paper.pdf", 3, 0, "Third"),
    ]
    embedded_chunks = [
        EmbeddedChunk(chunks[0], (1.0, 0.0)),
        EmbeddedChunk(chunks[1], (0.5, 0.5)),
        EmbeddedChunk(chunks[2], (0.0, 1.0)),
    ]
    events: list[tuple[Any, ...]] = []
    client = StubClient(
        {
            "質問A": [1.0, 0.0],
            "Question A": [0.5, 0.5],
            "Question B": [0.0, 1.0],
        },
        events,
    )

    def fake_extract(path: Path) -> list[PageText]:
        events.append(("pdf", path))
        return pages

    def fake_split(received_pages: list[PageText]) -> list[Chunk]:
        events.append(("chunk", received_pages))
        return chunks

    def fake_embed(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        events.append(("document_embedding", received_chunks, model))
        assert received_client is client
        return embedded_chunks

    def fake_retrieve(
        query_embedding: list[float],
        received_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        events.append(("retriever", query_embedding, top_k))
        assert received_chunks == embedded_chunks
        assert top_k == len(embedded_chunks)
        if query_embedding == [1.0, 0.0]:
            order = (chunks[0], chunks[1], chunks[2])
        elif query_embedding == [0.5, 0.5]:
            order = (chunks[1], chunks[0], chunks[2])
        else:
            order = (chunks[2], chunks[1], chunks[0])
        return [
            SearchResult(chunk, 1.0 / rank, rank)
            for rank, chunk in enumerate(order, start=1)
        ]

    monkeypatch.setattr(
        query_variant_diagnostics,
        "extract_page_texts",
        fake_extract,
    )
    monkeypatch.setattr(
        query_variant_diagnostics,
        "split_pages_into_chunks",
        fake_split,
    )
    monkeypatch.setattr(query_variant_diagnostics, "embed_chunks", fake_embed)
    monkeypatch.setattr(
        query_variant_diagnostics,
        "retrieve_similar_chunks",
        fake_retrieve,
    )

    report = run_query_variant_diagnostics(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert len(report.cases) == 2
    assert tuple(
        diagnostic.variant_label
        for diagnostic in report.cases[0].variants
    ) == ("ja", "en")
    assert report.cases[0].variants[0].first_relevant_rank == 2
    assert report.cases[0].variants[1].first_relevant_rank == 1
    assert report.cases[1].variants[0].first_relevant_rank == 1
    assert events.count(("pdf", pdf_path)) == 1
    assert events.count(("chunk", pages)) == 1
    assert events.count(
        ("document_embedding", chunks, "embedding-model")
    ) == 1
    assert [event for event in events if event[0] == "query_embedding"] == [
        ("query_embedding", ["質問A"], "embedding-model"),
        ("query_embedding", ["Question A"], "embedding-model"),
        ("query_embedding", ["Question B"], "embedding-model"),
    ]
    assert len([event for event in events if event[0] == "retriever"]) == 3


def test_report_clearly_separates_variants_and_comparisons() -> None:
    case = RetrievalEvaluationCase("Original question", (20,))
    original = build_query_variant_diagnostic(
        case,
        RetrievalQueryVariant("original_ja", "元の質問"),
        [
            make_result(1, 10, text="Competitor"),
            make_result(2, 20, score=0.4, text="Relevant answer"),
        ],
    )
    english = build_query_variant_diagnostic(
        case,
        RetrievalQueryVariant("english_equivalent", "English question"),
        [
            make_result(1, 20, score=0.6, text="Relevant answer"),
            make_result(2, 11, text="Other competitor"),
        ],
    )
    case_report = query_variant_diagnostics.QueryVariantCaseDiagnostic(
        question=case.question,
        relevant_pages=case.relevant_pages,
        variants=(original, english),
        comparisons=(
            compare_query_variant_diagnostics(original, english),
        ),
    )

    output = format_query_variant_diagnostics_report(
        RetrievalQueryVariantDiagnosticsReport((case_report,))
    )

    assert "Variant: original_ja" in output
    assert "query: 元の質問" in output
    assert "first_relevant_rank: 2" in output
    assert "best_relevant_score: 0.400000" in output
    assert "Top 5 results:" in output
    assert "character_count=10" in output
    assert "Relevant page chunks:" in output
    assert "Variant: english_equivalent" in output
    assert "original_ja -> english_equivalent" in output
    assert "Top 5 page overlap:" in output
    assert "removed competitor pages:" in output
    assert "added competitor pages:" in output


@pytest.mark.parametrize(
    ("label", "query", "message"),
    [
        ("", "Question", "label"),
        ("variant", "  ", "query"),
    ],
)
def test_variant_rejects_blank_values(
    label: str,
    query: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RetrievalQueryVariant(label, query)


@pytest.mark.parametrize(
    ("cases", "embedding_model", "message"),
    [
        ((), "model", "cases"),
        (
            (
                RetrievalQueryVariantCase(
                    RetrievalEvaluationCase("Question", (1,)),
                    (),
                ),
            ),
            "model",
            "variants",
        ),
        (
            (
                RetrievalQueryVariantCase(
                    RetrievalEvaluationCase("Question", (1,)),
                    (RetrievalQueryVariant("original", "Question"),),
                ),
            ),
            " ",
            "embedding_model",
        ),
    ],
)
def test_runner_rejects_invalid_inputs_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
    cases: tuple[RetrievalQueryVariantCase, ...],
    embedding_model: str,
    message: str,
) -> None:
    def unexpected_extract(_: Path) -> list[PageText]:
        raise AssertionError("PDF processing must not start")

    monkeypatch.setattr(
        query_variant_diagnostics,
        "extract_page_texts",
        unexpected_extract,
    )

    with pytest.raises(ValueError, match=message):
        run_query_variant_diagnostics(
            Path("paper.pdf"),
            cases,
            embedding_model=embedding_model,
        )


def test_runner_rejects_duplicate_variant_labels_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        RetrievalQueryVariantCase(
            RetrievalEvaluationCase("Question", (1,)),
            (
                RetrievalQueryVariant("same", "Question one"),
                RetrievalQueryVariant("same", "Question two"),
            ),
        ),
    )
    monkeypatch.setattr(
        query_variant_diagnostics,
        "extract_page_texts",
        lambda _: pytest.fail("PDF processing must not start"),
    )

    with pytest.raises(ValueError, match="unique"):
        run_query_variant_diagnostics(
            Path("paper.pdf"),
            cases,
            embedding_model="model",
        )


def test_runner_rejects_invalid_top_n_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = (
        RetrievalQueryVariantCase(
            RetrievalEvaluationCase("Question", (1,)),
            (RetrievalQueryVariant("original", "Question"),),
        ),
    )
    monkeypatch.setattr(
        query_variant_diagnostics,
        "extract_page_texts",
        lambda _: pytest.fail("PDF processing must not start"),
    )

    with pytest.raises(ValueError, match="top_n"):
        run_query_variant_diagnostics(
            Path("paper.pdf"),
            cases,
            embedding_model="model",
            top_n=0,
        )
