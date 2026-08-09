from collections.abc import Sequence
from pathlib import Path

from .chunker import split_pages_into_chunks
from .embedder import embed_chunks
from .models import RagAnswer, RagIndex, SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import NoExtractableTextError, extract_page_texts
from .retriever import retrieve_similar_chunks


_SYSTEM_PROMPT = (
    "Answer the user's question using only the provided source material.\n"
    "If the answer cannot be determined from the source material, clearly state "
    "that it cannot be determined.\n"
    "Do not guess or assert information that is not present in the source "
    "material.\n"
    "Output the final answer only, in the same language as the user's question.\n"
    "Do not output analysis or reasoning, and do not use prefaces such as "
    '"Let me analyze".\n'
    "Keep the answer concise and easy to read."
)


def answer_question_from_pdf(
    pdf_path: Path,
    question: str,
    *,
    embedding_model: str,
    generation_model: str,
    top_k: int = 3,
    client: OllamaClient | None = None,
) -> RagAnswer:
    """Run the RAG pipeline for one PDF while preserving the original API."""
    return answer_question_from_pdfs(
        (pdf_path,),
        question,
        embedding_model=embedding_model,
        generation_model=generation_model,
        top_k=top_k,
        client=client,
    )


def answer_question_from_pdfs(
    pdf_paths: Sequence[Path],
    question: str,
    *,
    embedding_model: str,
    generation_model: str,
    top_k: int = 3,
    client: OllamaClient | None = None,
) -> RagAnswer:
    """Build one in-memory index and answer one question from it."""
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    clean_embedding_model = embedding_model.strip()
    if not clean_embedding_model:
        raise ValueError("embedding_model must not be empty")
    clean_generation_model = generation_model.strip()
    if not clean_generation_model:
        raise ValueError("generation_model must not be empty")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    ordered_pdf_paths = tuple(pdf_paths)
    if not ordered_pdf_paths:
        raise ValueError("at least one PDF must be selected")
    _validate_unique_document_names(ordered_pdf_paths)

    ollama_client = client if client is not None else OllamaClient()
    index = build_rag_index(
        ordered_pdf_paths,
        embedding_model=clean_embedding_model,
        client=ollama_client,
    )
    return answer_question_from_index(
        index,
        clean_question,
        generation_model=clean_generation_model,
        top_k=top_k,
        client=ollama_client,
    )


def build_rag_index(
    pdf_paths: Sequence[Path],
    *,
    embedding_model: str,
    client: OllamaClient | None = None,
) -> RagIndex:
    """Prepare an immutable in-memory index from one or more PDFs."""
    clean_embedding_model = embedding_model.strip()
    if not clean_embedding_model:
        raise ValueError("embedding_model must not be empty")

    ordered_pdf_paths = tuple(pdf_paths)
    if not ordered_pdf_paths:
        raise ValueError("at least one PDF must be selected")
    _validate_unique_document_names(ordered_pdf_paths)

    ollama_client = client if client is not None else OllamaClient()
    pages = []
    for pdf_path in ordered_pdf_paths:
        try:
            pages.extend(extract_page_texts(pdf_path))
        except NoExtractableTextError:
            continue

    chunks = split_pages_into_chunks(pages)
    if not chunks:
        raise ValueError(
            "no searchable chunks were generated from the selected PDFs"
        )

    embedded_chunks = embed_chunks(
        chunks,
        clean_embedding_model,
        ollama_client,
    )
    if not embedded_chunks:
        raise ValueError("no chunk embeddings were generated")

    return RagIndex(
        document_names=tuple(path.name for path in ordered_pdf_paths),
        embedding_model=clean_embedding_model,
        embedded_chunks=tuple(embedded_chunks),
    )


def answer_question_from_index(
    index: RagIndex,
    question: str,
    *,
    generation_model: str,
    top_k: int = 3,
    client: OllamaClient | None = None,
) -> RagAnswer:
    """Answer one question using an already prepared in-memory index."""
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    clean_embedding_model = index.embedding_model.strip()
    if not clean_embedding_model:
        raise ValueError("index embedding_model must not be empty")
    if not index.embedded_chunks:
        raise ValueError("index must contain at least one embedded chunk")
    clean_generation_model = generation_model.strip()
    if not clean_generation_model:
        raise ValueError("generation_model must not be empty")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    ollama_client = client if client is not None else OllamaClient()
    query_embeddings = ollama_client.embed_texts(
        [clean_question],
        model=clean_embedding_model,
    )
    if len(query_embeddings) != 1:
        raise ValueError("question embedding response must contain exactly one vector")

    search_results = retrieve_similar_chunks(
        query_embeddings[0],
        index.embedded_chunks,
        top_k=top_k,
    )
    if not search_results:
        raise ValueError("no search results were found for the question")

    return generate_answer(
        clean_question,
        search_results,
        clean_generation_model,
        ollama_client,
    )


def _validate_unique_document_names(pdf_paths: Sequence[Path]) -> None:
    seen_names: set[str] = set()
    duplicate_names: set[str] = set()

    for pdf_path in pdf_paths:
        document_name = pdf_path.name
        if document_name in seen_names:
            duplicate_names.add(document_name)
        seen_names.add(document_name)

    if duplicate_names:
        names = ", ".join(sorted(duplicate_names))
        raise ValueError(
            "PDF document names must be unique; duplicate basename(s): "
            f"{names}"
        )


def generate_answer(
    question: str,
    search_results: Sequence[SearchResult],
    model: str,
    client: OllamaClient,
) -> RagAnswer:
    """Generate an answer grounded in ranked search results."""
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    if not search_results:
        raise ValueError("no search results are available to support the answer")
    if not model.strip():
        raise ValueError("model must not be empty")

    ordered_sources = tuple(
        sorted(search_results, key=lambda result: result.rank)
    )
    messages = _build_messages(clean_question, ordered_sources)
    answer_text = client.generate_chat(messages, model=model).strip()

    if not answer_text:
        raise ValueError("LLM returned an empty answer")

    return RagAnswer(text=answer_text, sources=ordered_sources)


def _build_messages(
    question: str,
    search_results: Sequence[SearchResult],
) -> list[dict[str, str]]:
    source_blocks = [
        "\n".join(
            [
                f"[Source {result.rank}]",
                f"Rank: {result.rank}",
                f"Document: {result.chunk.document_name}",
                f"Page: {result.chunk.page_number}",
                "Text:",
                result.chunk.text,
            ]
        )
        for result in search_results
    ]
    user_prompt = "\n".join(
        [
            "Question:",
            question,
            "",
            "Source material:",
            "",
            "\n\n".join(source_blocks),
        ]
    )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
