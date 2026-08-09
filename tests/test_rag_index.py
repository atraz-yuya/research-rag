from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any

import pytest

from research_rag import rag_service
from research_rag.models import (
    Chunk,
    EmbeddedChunk,
    PageText,
    RagAnswer,
    RagIndex,
    SearchResult,
)
from research_rag.pdf_reader import NoExtractableTextError
from research_rag.rag_service import (
    answer_question_from_index,
    answer_question_from_pdfs,
    build_rag_index,
)


class QueryEmbeddingClient:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.embeddings = iter(embeddings)
        self.calls: list[tuple[list[str], str]] = []

    def embed_texts(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        self.calls.append((texts, model))
        return [next(self.embeddings)]


def make_embedded_chunks() -> tuple[EmbeddedChunk, ...]:
    return (
        EmbeddedChunk(
            Chunk("first.pdf", 1, 0, "First source"),
            (1.0, 0.0),
        ),
        EmbeddedChunk(
            Chunk("second.pdf", 3, 0, "Second source"),
            (0.0, 1.0),
        ),
    )


def test_rag_index_is_immutable_and_contains_only_prepared_corpus_data() -> None:
    index = RagIndex(
        document_names=("paper.pdf",),
        embedding_model="embedding-model",
        embedded_chunks=make_embedded_chunks()[:1],
    )

    assert tuple(field.name for field in fields(RagIndex)) == (
        "document_names",
        "embedding_model",
        "embedded_chunks",
    )
    with pytest.raises(FrozenInstanceError):
        index.embedding_model = "other-model"  # type: ignore[misc]


def test_build_rag_index_prepares_multiple_pdfs_once_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_paths = (Path("first.pdf"), Path("second.pdf"))
    first_pages = [PageText("first.pdf", 1, "First page")]
    second_pages = [PageText("second.pdf", 3, "Second page")]
    combined_pages = [*first_pages, *second_pages]
    chunks = [
        Chunk("first.pdf", 1, 0, "First source"),
        Chunk("second.pdf", 3, 0, "Second source"),
    ]
    embedded_chunks = make_embedded_chunks()
    events: list[tuple[Any, ...]] = []
    client = object()

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        events.append(("extract", pdf_path))
        if pdf_path == pdf_paths[0]:
            return first_pages
        return second_pages

    def fake_split_pages_into_chunks(
        pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("chunk", pages))
        return chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        events.append(("embed", received_chunks, model, received_client))
        return list(embedded_chunks)

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        fake_split_pages_into_chunks,
    )
    monkeypatch.setattr(rag_service, "embed_chunks", fake_embed_chunks)

    index = build_rag_index(
        pdf_paths,
        embedding_model="  embedding-model  ",
        client=client,  # type: ignore[arg-type]
    )

    assert index == RagIndex(
        document_names=("first.pdf", "second.pdf"),
        embedding_model="embedding-model",
        embedded_chunks=embedded_chunks,
    )
    assert index.embedded_chunks[0].chunk.document_name == "first.pdf"
    assert index.embedded_chunks[0].chunk.page_number == 1
    assert index.embedded_chunks[1].chunk.document_name == "second.pdf"
    assert index.embedded_chunks[1].chunk.page_number == 3
    assert events == [
        ("extract", pdf_paths[0]),
        ("extract", pdf_paths[1]),
        ("chunk", combined_pages),
        ("embed", chunks, "embedding-model", client),
    ]


def test_build_rag_index_rejects_duplicate_basenames_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF extraction must not start")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_extract)

    with pytest.raises(ValueError, match=r"unique.*paper\.pdf"):
        build_rag_index(
            [Path("one/paper.pdf"), Path("two/paper.pdf")],
            embedding_model="embedding-model",
        )


@pytest.mark.parametrize(
    ("pdf_paths", "embedding_model", "message"),
    [
        ([], "embedding-model", "at least one PDF"),
        ([Path("paper.pdf")], "  ", "embedding_model must not be empty"),
    ],
)
def test_build_rag_index_rejects_invalid_input_before_processing(
    monkeypatch: pytest.MonkeyPatch,
    pdf_paths: list[Path],
    embedding_model: str,
    message: str,
) -> None:
    def unexpected_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF extraction must not start")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_extract)

    with pytest.raises(ValueError, match=message):
        build_rag_index(pdf_paths, embedding_model=embedding_model)


def test_build_rag_index_skips_no_text_pdf_and_retains_document_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_path = Path("empty.pdf")
    searchable_path = Path("searchable.pdf")
    pages = [PageText("searchable.pdf", 2, "Searchable text")]
    chunk = Chunk("searchable.pdf", 2, 0, "Searchable text")
    embedded_chunk = EmbeddedChunk(chunk, (1.0, 0.0))

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        if pdf_path == empty_path:
            raise NoExtractableTextError("No text")
        return pages

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        lambda received_pages: [chunk],
    )
    monkeypatch.setattr(
        rag_service,
        "embed_chunks",
        lambda chunks, model, client: [embedded_chunk],
    )

    index = build_rag_index(
        [empty_path, searchable_path],
        embedding_model="embedding-model",
        client=object(),  # type: ignore[arg-type]
    )

    assert index.document_names == ("empty.pdf", "searchable.pdf")
    assert index.embedded_chunks == (embedded_chunk,)


def test_build_rag_index_rejects_empty_document_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = PageText("paper.pdf", 1, "Searchable text")
    chunk = Chunk("paper.pdf", 1, 0, "Searchable text")

    monkeypatch.setattr(
        rag_service,
        "extract_page_texts",
        lambda pdf_path: [page],
    )
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        lambda pages: [chunk],
    )
    monkeypatch.setattr(
        rag_service,
        "embed_chunks",
        lambda chunks, model, client: [],
    )

    with pytest.raises(ValueError, match="no chunk embeddings"):
        build_rag_index(
            [Path("paper.pdf")],
            embedding_model="embedding-model",
            client=object(),  # type: ignore[arg-type]
        )


def test_build_rag_index_rejects_when_all_pdfs_have_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extracted_paths: list[Path] = []
    pdf_paths = [Path("first.pdf"), Path("second.pdf")]

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        extracted_paths.append(pdf_path)
        raise NoExtractableTextError("No text")

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)

    with pytest.raises(ValueError, match="no searchable chunks"):
        build_rag_index(
            pdf_paths,
            embedding_model="embedding-model",
            client=object(),  # type: ignore[arg-type]
        )

    assert extracted_paths == pdf_paths


def test_build_rag_index_propagates_other_pdf_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_extract(pdf_path: Path) -> list[PageText]:
        raise RuntimeError("damaged PDF")

    monkeypatch.setattr(rag_service, "extract_page_texts", failing_extract)

    with pytest.raises(RuntimeError, match="damaged PDF"):
        build_rag_index(
            [Path("paper.pdf")],
            embedding_model="embedding-model",
            client=object(),  # type: ignore[arg-type]
        )


def test_answer_question_from_index_uses_recorded_model_and_global_corpus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedded_chunks = make_embedded_chunks()
    index = RagIndex(
        document_names=("first.pdf", "second.pdf"),
        embedding_model="index-embedding-model",
        embedded_chunks=embedded_chunks,
    )
    client = QueryEmbeddingClient([[0.0, 1.0]])
    search_results = [
        SearchResult(embedded_chunks[1].chunk, 0.99, 1),
        SearchResult(embedded_chunks[0].chunk, 0.10, 2),
    ]
    events: list[tuple[Any, ...]] = []
    expected = RagAnswer("Second document answer", tuple(search_results))

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: tuple[EmbeddedChunk, ...],
        top_k: int,
    ) -> list[SearchResult]:
        events.append(("retrieve", query_embedding, received_chunks, top_k))
        return search_results

    def fake_generate_answer(
        question: str,
        results: list[SearchResult],
        model: str,
        received_client: Any,
    ) -> RagAnswer:
        events.append(("generate", question, results, model, received_client))
        return expected

    monkeypatch.setattr(
        rag_service,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )
    monkeypatch.setattr(rag_service, "generate_answer", fake_generate_answer)

    answer = answer_question_from_index(
        index,
        "Which document answers the question?",
        generation_model="generation-model",
        top_k=2,
        client=client,  # type: ignore[arg-type]
    )

    assert answer is expected
    assert client.calls == [
        (["Which document answers the question?"], "index-embedding-model")
    ]
    assert events == [
        ("retrieve", [0.0, 1.0], index.embedded_chunks, 2),
        (
            "generate",
            "Which document answers the question?",
            search_results,
            "generation-model",
            client,
        ),
    ]
    assert answer.sources[0].chunk.document_name == "second.pdf"
    assert answer.sources[0].chunk.page_number == 3


def test_two_questions_reuse_document_work_and_run_question_work_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_paths = [Path("first.pdf"), Path("second.pdf")]
    pages_by_path = {
        pdf_paths[0]: [PageText("first.pdf", 1, "First page")],
        pdf_paths[1]: [PageText("second.pdf", 2, "Second page")],
    }
    chunks = [
        Chunk("first.pdf", 1, 0, "First source"),
        Chunk("second.pdf", 2, 0, "Second source"),
    ]
    embedded_chunks = (
        EmbeddedChunk(chunks[0], (1.0, 0.0)),
        EmbeddedChunk(chunks[1], (0.0, 1.0)),
    )
    counts = {"extract": 0, "chunk": 0, "document_embed": 0}
    retrieval_calls: list[tuple[list[float], tuple[EmbeddedChunk, ...]]] = []
    generation_calls: list[str] = []
    client = QueryEmbeddingClient([[1.0, 0.0], [0.0, 1.0]])

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        counts["extract"] += 1
        return pages_by_path[pdf_path]

    def fake_split_pages_into_chunks(pages: list[PageText]) -> list[Chunk]:
        counts["chunk"] += 1
        return chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        counts["document_embed"] += 1
        return list(embedded_chunks)

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: tuple[EmbeddedChunk, ...],
        top_k: int,
    ) -> list[SearchResult]:
        retrieval_calls.append((query_embedding, received_chunks))
        selected = chunks[0] if query_embedding[0] == 1.0 else chunks[1]
        return [SearchResult(selected, 1.0, 1)]

    def fake_generate_answer(
        question: str,
        results: list[SearchResult],
        model: str,
        received_client: Any,
    ) -> RagAnswer:
        generation_calls.append(question)
        return RagAnswer(f"Answer for {question}", tuple(results))

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        fake_split_pages_into_chunks,
    )
    monkeypatch.setattr(rag_service, "embed_chunks", fake_embed_chunks)
    monkeypatch.setattr(
        rag_service,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )
    monkeypatch.setattr(rag_service, "generate_answer", fake_generate_answer)

    index = build_rag_index(
        pdf_paths,
        embedding_model="embedding-model",
        client=client,  # type: ignore[arg-type]
    )
    first_answer = answer_question_from_index(
        index,
        "Question one",
        generation_model="generation-model",
        client=client,  # type: ignore[arg-type]
    )
    second_answer = answer_question_from_index(
        index,
        "Question two",
        generation_model="generation-model",
        client=client,  # type: ignore[arg-type]
    )

    assert counts == {"extract": 2, "chunk": 1, "document_embed": 1}
    assert client.calls == [
        (["Question one"], "embedding-model"),
        (["Question two"], "embedding-model"),
    ]
    assert retrieval_calls == [
        ([1.0, 0.0], index.embedded_chunks),
        ([0.0, 1.0], index.embedded_chunks),
    ]
    assert generation_calls == ["Question one", "Question two"]
    assert first_answer.sources[0].chunk.document_name == "first.pdf"
    assert second_answer.sources[0].chunk.document_name == "second.pdf"


@pytest.mark.parametrize(
    ("index", "question", "generation_model", "top_k", "message"),
    [
        (
            RagIndex(("paper.pdf",), "", make_embedded_chunks()[:1]),
            "Question",
            "generation-model",
            3,
            "index embedding_model must not be empty",
        ),
        (
            RagIndex(("paper.pdf",), "embedding-model", ()),
            "Question",
            "generation-model",
            3,
            "index must contain at least one embedded chunk",
        ),
        (
            RagIndex(
                ("paper.pdf",),
                "embedding-model",
                make_embedded_chunks()[:1],
            ),
            "   ",
            "generation-model",
            3,
            "question must not be empty",
        ),
        (
            RagIndex(
                ("paper.pdf",),
                "embedding-model",
                make_embedded_chunks()[:1],
            ),
            "Question",
            "  ",
            3,
            "generation_model must not be empty",
        ),
        (
            RagIndex(
                ("paper.pdf",),
                "embedding-model",
                make_embedded_chunks()[:1],
            ),
            "Question",
            "generation-model",
            0,
            "top_k must be greater than 0",
        ),
    ],
)
def test_answer_question_from_index_rejects_invalid_input_before_query_work(
    index: RagIndex,
    question: str,
    generation_model: str,
    top_k: int,
    message: str,
) -> None:
    class UnexpectedClient:
        def embed_texts(self, texts: list[str], model: str) -> list[list[float]]:
            raise AssertionError("query embedding must not start")

    with pytest.raises(ValueError, match=message):
        answer_question_from_index(
            index,
            question,
            generation_model=generation_model,
            top_k=top_k,
            client=UnexpectedClient(),  # type: ignore[arg-type]
        )


def test_answer_question_from_pdfs_composes_build_and_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_paths = (Path("first.pdf"), Path("second.pdf"))
    index = RagIndex(
        ("first.pdf", "second.pdf"),
        "embedding-model",
        make_embedded_chunks(),
    )
    expected = RagAnswer("Answer", ())
    client = object()
    calls: list[tuple[Any, ...]] = []

    def fake_build_rag_index(
        received_paths: tuple[Path, ...],
        *,
        embedding_model: str,
        client: Any,
    ) -> RagIndex:
        calls.append(("build", received_paths, embedding_model, client))
        return index

    def fake_answer_question_from_index(
        received_index: RagIndex,
        question: str,
        *,
        generation_model: str,
        top_k: int,
        client: Any,
    ) -> RagAnswer:
        calls.append(
            (
                "answer",
                received_index,
                question,
                generation_model,
                top_k,
                client,
            )
        )
        return expected

    monkeypatch.setattr(rag_service, "build_rag_index", fake_build_rag_index)
    monkeypatch.setattr(
        rag_service,
        "answer_question_from_index",
        fake_answer_question_from_index,
    )

    answer = answer_question_from_pdfs(
        pdf_paths,
        "  Question  ",
        embedding_model="  embedding-model  ",
        generation_model="  generation-model  ",
        top_k=4,
        client=client,  # type: ignore[arg-type]
    )

    assert answer is expected
    assert calls == [
        ("build", pdf_paths, "embedding-model", client),
        ("answer", index, "Question", "generation-model", 4, client),
    ]
