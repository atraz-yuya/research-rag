from pathlib import Path
from typing import Any

import pytest

from research_rag import rag_service
from research_rag.models import (
    Chunk,
    EmbeddedChunk,
    PageText,
    RagAnswer,
    SearchResult,
)
from research_rag.pdf_reader import NoExtractableTextError
from research_rag.rag_service import (
    answer_question_from_pdf,
    answer_question_from_pdfs,
    generate_answer,
)


class StubChatClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> str:
        self.calls.append((messages, model))
        return self.response


def make_search_result(
    *,
    rank: int,
    document_name: str,
    page_number: int,
    text: str,
    score: float = 0.9,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            document_name=document_name,
            page_number=page_number,
            chunk_index=rank - 1,
            text=text,
        ),
        score=score,
        rank=rank,
    )


def test_generate_answer_uses_one_source_and_preserves_it() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=3,
        text="The experiment improved accuracy.",
    )
    client = StubChatClient("Accuracy improved in the experiment.")

    answer = generate_answer(
        "What improved?",
        [source],
        model="generation-model",
        client=client,
    )

    assert answer == RagAnswer(
        text="Accuracy improved in the experiment.",
        sources=(source,),
    )
    assert answer.sources[0] is source
    assert client.calls[0][1] == "generation-model"


def test_generate_answer_includes_question_and_source_details_in_prompt() -> None:
    source = make_search_result(
        rank=1,
        document_name="research-paper.pdf",
        page_number=8,
        text="Grounded source text.",
    )
    client = StubChatClient("Grounded answer")

    generate_answer(
        "What does the source say?",
        [source],
        model="generation-model",
        client=client,
    )

    messages, _ = client.calls[0]
    user_prompt = messages[1]["content"]
    assert "What does the source say?" in user_prompt
    assert "[Source 1]" in user_prompt
    assert "Rank: 1" in user_prompt
    assert "Document: research-paper.pdf" in user_prompt
    assert "Page: 8" in user_prompt
    assert "Grounded source text." in user_prompt


def test_generate_answer_instructs_model_to_use_only_sources() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    generate_answer(
        "Question",
        [source],
        model="generation-model",
        client=client,
    )

    system_prompt = client.calls[0][0][0]["content"]
    assert "only the provided source material" in system_prompt
    assert "cannot be determined" in system_prompt
    assert "Do not guess" in system_prompt
    assert "final answer only" in system_prompt
    assert "Do not output analysis or reasoning" in system_prompt
    assert 'prefaces such as "Let me analyze"' in system_prompt
    assert "same language as the user's question" in system_prompt
    assert "concise" in system_prompt


def test_generate_answer_orders_prompt_and_sources_by_rank() -> None:
    second = make_search_result(
        rank=2,
        document_name="paper.pdf",
        page_number=9,
        text="Second-ranked text.",
    )
    first = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=2,
        text="First-ranked text.",
    )
    client = StubChatClient("Answer")

    answer = generate_answer(
        "Question",
        [second, first],
        model="generation-model",
        client=client,
    )

    user_prompt = client.calls[0][0][1]["content"]
    assert user_prompt.index("[Source 1]") < user_prompt.index("[Source 2]")
    assert user_prompt.index("First-ranked text.") < user_prompt.index(
        "Second-ranked text."
    )
    assert answer.sources == (first, second)
    assert answer.sources[0] is first
    assert answer.sources[1] is second


@pytest.mark.parametrize("question", ["", "   \n\t"])
def test_generate_answer_rejects_empty_or_whitespace_question(
    question: str,
) -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="question must not be empty"):
        generate_answer(
            question,
            [source],
            model="generation-model",
            client=client,
        )

    assert client.calls == []


def test_generate_answer_rejects_empty_search_results() -> None:
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="no search results are available"):
        generate_answer(
            "Question",
            [],
            model="generation-model",
            client=client,
        )

    assert client.calls == []


def test_generate_answer_rejects_empty_model() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="model must not be empty"):
        generate_answer("Question", [source], model="  ", client=client)

    assert client.calls == []


@pytest.mark.parametrize("response", ["", "   \n\t"])
def test_generate_answer_rejects_empty_llm_answer(response: str) -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient(response)

    with pytest.raises(ValueError, match="LLM returned an empty answer"):
        generate_answer(
            "Question",
            [source],
            model="generation-model",
            client=client,
        )


class StubEmbeddingClient:
    def __init__(
        self,
        query_embedding: list[float],
        events: list[tuple[Any, ...]],
    ) -> None:
        self.query_embedding = query_embedding
        self.events = events

    def embed_texts(
        self,
        texts: list[str],
        model: str,
    ) -> list[list[float]]:
        self.events.append(("query_embedder", texts, model))
        return [self.query_embedding]


def test_answer_question_from_pdf_connects_pipeline_and_preserves_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    question = "What is the main contribution?"
    pages = [PageText("paper.pdf", 1, "Extracted page text")]
    chunks = [Chunk("paper.pdf", 1, 0, "Chunk text")]
    embedded_chunks = [EmbeddedChunk(chunks[0], (1.0, 0.0))]
    search_results = [SearchResult(chunks[0], 0.95, 1)]
    expected_answer = RagAnswer("Grounded answer", tuple(search_results))
    events: list[tuple[Any, ...]] = []
    client = StubEmbeddingClient([1.0, 0.0], events)

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
            ("chunk_embedder", received_chunks, model, received_client)
        )
        return embedded_chunks

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_embedded_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        events.append(
            ("retriever", query_embedding, received_embedded_chunks, top_k)
        )
        return search_results

    def fake_generate_answer(
        received_question: str,
        received_results: list[SearchResult],
        model: str,
        received_client: Any,
    ) -> RagAnswer:
        events.append(
            (
                "answer_generator",
                received_question,
                received_results,
                model,
                received_client,
            )
        )
        return expected_answer

    monkeypatch.setattr(
        rag_service,
        "extract_page_texts",
        fake_extract_page_texts,
    )
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

    answer = answer_question_from_pdf(
        pdf_path,
        question,
        embedding_model="shared-embedding-model",
        generation_model="generation-model",
        top_k=2,
        client=client,
    )

    assert answer is expected_answer
    assert answer.sources[0] is search_results[0]
    assert events == [
        ("pdf_reader", pdf_path),
        ("chunker", pages),
        (
            "chunk_embedder",
            chunks,
            "shared-embedding-model",
            client,
        ),
        (
            "query_embedder",
            [question],
            "shared-embedding-model",
        ),
        ("retriever", [1.0, 0.0], embedded_chunks, 2),
        (
            "answer_generator",
            question,
            search_results,
            "generation-model",
            client,
        ),
    ]


def test_answer_question_from_pdfs_uses_one_shared_global_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_paths = (Path("first.pdf"), Path("second.pdf"))
    question = "Which document is most relevant?"
    first_pages = [PageText("first.pdf", 1, "First document text")]
    second_pages = [PageText("second.pdf", 2, "Second document text")]
    combined_pages = [*first_pages, *second_pages]
    chunks = [
        Chunk("first.pdf", 1, 0, "First chunk"),
        Chunk("second.pdf", 2, 0, "Second chunk"),
    ]
    embedded_chunks = [
        EmbeddedChunk(chunks[0], (0.0, 1.0)),
        EmbeddedChunk(chunks[1], (1.0, 0.0)),
    ]
    search_results = [
        SearchResult(chunks[1], 0.98, 1),
        SearchResult(chunks[0], 0.25, 2),
    ]
    expected_answer = RagAnswer("Second is most relevant.", tuple(search_results))
    events: list[tuple[Any, ...]] = []
    client = StubEmbeddingClient([1.0, 0.0], events)

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        events.append(("pdf_reader", pdf_path))
        if pdf_path == pdf_paths[0]:
            return first_pages
        return second_pages

    def fake_split_pages_into_chunks(
        pages: list[PageText],
    ) -> list[Chunk]:
        events.append(("chunker", pages))
        return chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        received_client: Any,
    ) -> list[EmbeddedChunk]:
        events.append(
            ("chunk_embedder", received_chunks, model, received_client)
        )
        return embedded_chunks

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_embedded_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        events.append(
            ("retriever", query_embedding, received_embedded_chunks, top_k)
        )
        return search_results

    def fake_generate_answer(
        received_question: str,
        received_results: list[SearchResult],
        model: str,
        received_client: Any,
    ) -> RagAnswer:
        events.append(
            (
                "answer_generator",
                received_question,
                received_results,
                model,
                received_client,
            )
        )
        return expected_answer

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

    answer = answer_question_from_pdfs(
        pdf_paths,
        question,
        embedding_model="shared-embedding-model",
        generation_model="generation-model",
        top_k=2,
        client=client,
    )

    assert answer is expected_answer
    assert answer.sources[0].chunk.document_name == "second.pdf"
    assert answer.sources[0].chunk.page_number == 2
    assert events == [
        ("pdf_reader", pdf_paths[0]),
        ("pdf_reader", pdf_paths[1]),
        ("chunker", combined_pages),
        (
            "chunk_embedder",
            chunks,
            "shared-embedding-model",
            client,
        ),
        ("query_embedder", [question], "shared-embedding-model"),
        ("retriever", [1.0, 0.0], embedded_chunks, 2),
        (
            "answer_generator",
            question,
            search_results,
            "generation-model",
            client,
        ),
    ]


def test_answer_question_from_pdfs_rejects_empty_collection_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF extraction must not start")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_extract)

    with pytest.raises(ValueError, match="at least one PDF"):
        answer_question_from_pdfs(
            [],
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
        )


def test_answer_question_from_pdfs_rejects_duplicate_basenames_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF extraction must not start")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_extract)

    with pytest.raises(ValueError, match=r"unique.*paper\.pdf"):
        answer_question_from_pdfs(
            [Path("first/paper.pdf"), Path("second/paper.pdf")],
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
        )


def test_answer_question_from_pdfs_skips_one_empty_pdf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty_path = Path("empty.pdf")
    searchable_path = Path("searchable.pdf")
    pages = [PageText("searchable.pdf", 4, "Searchable text")]
    chunks = [Chunk("searchable.pdf", 4, 0, "Searchable text")]
    embedded_chunks = [EmbeddedChunk(chunks[0], (1.0, 0.0))]
    search_results = [SearchResult(chunks[0], 1.0, 1)]
    client = StubEmbeddingClient([1.0, 0.0], [])
    extracted_paths: list[Path] = []

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        extracted_paths.append(pdf_path)
        if pdf_path == empty_path:
            raise NoExtractableTextError(
                f"No text could be extracted from PDF: {pdf_path}"
            )
        return pages

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        lambda received_pages: chunks,
    )
    monkeypatch.setattr(
        rag_service,
        "embed_chunks",
        lambda received_chunks, model, received_client: embedded_chunks,
    )
    monkeypatch.setattr(
        rag_service,
        "retrieve_similar_chunks",
        lambda query_embedding, received_chunks, top_k: search_results,
    )
    monkeypatch.setattr(
        rag_service,
        "generate_answer",
        lambda question, results, model, received_client: RagAnswer(
            "Answer", tuple(results)
        ),
    )

    answer = answer_question_from_pdfs(
        [empty_path, searchable_path],
        "Question",
        embedding_model="embedding-model",
        generation_model="generation-model",
        client=client,
    )

    assert extracted_paths == [empty_path, searchable_path]
    assert answer.sources[0].chunk.document_name == "searchable.pdf"
    assert answer.sources[0].chunk.page_number == 4


def test_answer_question_from_pdfs_rejects_when_all_pdfs_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_paths = [Path("first.pdf"), Path("second.pdf")]
    extracted_paths: list[Path] = []

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        extracted_paths.append(pdf_path)
        raise NoExtractableTextError(
            f"No text could be extracted from PDF: {pdf_path}"
        )

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)

    with pytest.raises(ValueError, match="no searchable chunks.*selected PDFs"):
        answer_question_from_pdfs(
            pdf_paths,
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
        )

    assert extracted_paths == pdf_paths


def test_answer_question_from_pdf_delegates_to_multi_pdf_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    client = StubEmbeddingClient([1.0], [])
    expected = RagAnswer("Answer", ())
    captured: dict[str, Any] = {}

    def fake_answer_question_from_pdfs(
        pdf_paths: tuple[Path, ...],
        question: str,
        *,
        embedding_model: str,
        generation_model: str,
        top_k: int,
        client: Any,
    ) -> RagAnswer:
        captured.update(
            pdf_paths=pdf_paths,
            question=question,
            embedding_model=embedding_model,
            generation_model=generation_model,
            top_k=top_k,
            client=client,
        )
        return expected

    monkeypatch.setattr(
        rag_service,
        "answer_question_from_pdfs",
        fake_answer_question_from_pdfs,
    )

    answer = answer_question_from_pdf(
        pdf_path,
        "Question",
        embedding_model="embedding-model",
        generation_model="generation-model",
        top_k=5,
        client=client,
    )

    assert answer is expected
    assert captured == {
        "pdf_paths": (pdf_path,),
        "question": "Question",
        "embedding_model": "embedding-model",
        "generation_model": "generation-model",
        "top_k": 5,
        "client": client,
    }


def test_answer_question_from_pdfs_propagates_nonempty_pdf_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = Path("first.pdf")
    second_path = Path("second.pdf")

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        if pdf_path == first_path:
            return [PageText("first.pdf", 1, "Text")]
        raise RuntimeError("failure in second PDF")

    monkeypatch.setattr(rag_service, "extract_page_texts", fake_extract_page_texts)

    with pytest.raises(RuntimeError, match="failure in second PDF"):
        answer_question_from_pdfs(
            [first_path, second_path],
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
        )


def test_answer_question_from_pdf_rejects_empty_question_before_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(
        rag_service,
        "extract_page_texts",
        fake_extract_page_texts,
    )

    with pytest.raises(ValueError, match="question must not be empty"):
        answer_question_from_pdf(
            Path("paper.pdf"),
            "  \n\t",
            embedding_model="embedding-model",
            generation_model="generation-model",
        )

    assert called is False


@pytest.mark.parametrize(
    "failure_stage",
    [
        "pdf_reader",
        "chunker",
        "chunk_embedder",
        "query_embedder",
        "retriever",
        "answer_generator",
    ],
)
def test_answer_question_from_pdf_propagates_downstream_errors(
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [Chunk("paper.pdf", 1, 0, "Chunk text")]
    embedded_chunks = [EmbeddedChunk(chunks[0], (1.0, 0.0))]
    search_results = [SearchResult(chunks[0], 1.0, 1)]

    def fail_if(stage: str) -> None:
        if failure_stage == stage:
            raise RuntimeError(f"failure in {stage}")

    def fake_extract_page_texts(pdf_path: Path) -> list[PageText]:
        fail_if("pdf_reader")
        return pages

    def fake_split_pages_into_chunks(
        received_pages: list[PageText],
    ) -> list[Chunk]:
        fail_if("chunker")
        return chunks

    def fake_embed_chunks(
        received_chunks: list[Chunk],
        model: str,
        client: Any,
    ) -> list[EmbeddedChunk]:
        fail_if("chunk_embedder")
        return embedded_chunks

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_embedded_chunks: list[EmbeddedChunk],
        top_k: int,
    ) -> list[SearchResult]:
        fail_if("retriever")
        return search_results

    def fake_generate_answer(
        question: str,
        received_results: list[SearchResult],
        model: str,
        client: Any,
    ) -> RagAnswer:
        fail_if("answer_generator")
        return RagAnswer("Answer", tuple(search_results))

    class FailingQueryClient:
        def embed_texts(
            self,
            texts: list[str],
            model: str,
        ) -> list[list[float]]:
            fail_if("query_embedder")
            return [[1.0, 0.0]]

    monkeypatch.setattr(
        rag_service,
        "extract_page_texts",
        fake_extract_page_texts,
    )
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

    with pytest.raises(RuntimeError, match=f"failure in {failure_stage}"):
        answer_question_from_pdf(
            Path("paper.pdf"),
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
            client=FailingQueryClient(),
        )


def test_answer_question_from_pdf_rejects_missing_search_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [Chunk("paper.pdf", 1, 0, "Chunk text")]
    embedded_chunks = [EmbeddedChunk(chunks[0], (1.0, 0.0))]
    client = StubEmbeddingClient([1.0, 0.0], [])

    monkeypatch.setattr(rag_service, "extract_page_texts", lambda path: pages)
    monkeypatch.setattr(
        rag_service,
        "split_pages_into_chunks",
        lambda received_pages: chunks,
    )
    monkeypatch.setattr(
        rag_service,
        "embed_chunks",
        lambda received_chunks, model, client: embedded_chunks,
    )
    monkeypatch.setattr(
        rag_service,
        "retrieve_similar_chunks",
        lambda query_embedding, received_chunks, top_k: [],
    )

    with pytest.raises(ValueError, match="no search results"):
        answer_question_from_pdf(
            Path("paper.pdf"),
            "Question",
            embedding_model="embedding-model",
            generation_model="generation-model",
            client=client,
        )
