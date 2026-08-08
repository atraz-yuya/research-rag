from collections.abc import Sequence
from pathlib import Path

from .chunker import split_pages_into_chunks
from .embedder import embed_chunks
from .models import RagAnswer, SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
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
    """Run the complete single-PDF RAG pipeline for one question."""
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    if not embedding_model.strip():
        raise ValueError("embedding_model must not be empty")
    if not generation_model.strip():
        raise ValueError("generation_model must not be empty")
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    chunks = split_pages_into_chunks(pages)
    if not chunks:
        raise ValueError("no searchable chunks were generated from PDF")

    embedded_chunks = embed_chunks(
        chunks,
        embedding_model.strip(),
        ollama_client,
    )
    if not embedded_chunks:
        raise ValueError("no chunk embeddings were generated")

    query_embeddings = ollama_client.embed_texts(
        [clean_question],
        model=embedding_model.strip(),
    )
    if len(query_embeddings) != 1:
        raise ValueError("question embedding response must contain exactly one vector")

    search_results = retrieve_similar_chunks(
        query_embeddings[0],
        embedded_chunks,
        top_k=top_k,
    )
    if not search_results:
        raise ValueError("no search results were found for the question")

    return generate_answer(
        clean_question,
        search_results,
        generation_model.strip(),
        ollama_client,
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
