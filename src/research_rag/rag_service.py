from collections.abc import Sequence

from .models import RagAnswer, SearchResult
from .ollama_client import OllamaClient


_SYSTEM_PROMPT = (
    "Answer the user's question using only the provided source material.\n"
    "If the answer cannot be determined from the source material, clearly state "
    "that it cannot be determined.\n"
    "Do not guess or assert information that is not present in the source "
    "material.\n"
    "Keep the answer concise and easy to read."
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
