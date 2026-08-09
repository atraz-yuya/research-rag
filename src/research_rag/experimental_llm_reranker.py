import json
from collections.abc import Sequence
from dataclasses import dataclass

from .models import SearchResult
from .ollama_client import OllamaClient


_SYSTEM_PROMPT = """You are a retrieval reranker.
Rank the supplied candidates by how directly and completely each Chunk answers the exact question, not by topic similarity alone.
Consider:
1. the question's scope and qualifiers;
2. dates, quantities, and named conditions;
3. whether the Chunk contains the answer instead of related discussion;
4. whether a competing Chunk answers a narrower or different question.
Return only one strict JSON object in this form: {"ranking":["C001","C002"]}.
Use only supplied candidate IDs, do not repeat IDs, and do not reproduce Chunk text."""


class ExperimentalRerankingError(ValueError):
    """An invalid output or state in the experimental LLM reranker."""


@dataclass(frozen=True)
class RerankCandidate:
    """One dense-retrieval candidate with a request-stable ID."""

    candidate_id: str
    search_result: SearchResult


@dataclass(frozen=True)
class ExperimentalRerankingOutcome:
    """Reranked results and the size of the generation prompt."""

    search_results: tuple[SearchResult, ...]
    prompt_character_count: int


def build_rerank_candidates(
    dense_results: Sequence[SearchResult],
) -> tuple[RerankCandidate, ...]:
    """Assign stable IDs to candidates in their original dense rank order."""
    ordered_results = tuple(sorted(dense_results, key=lambda result: result.rank))
    dense_ranks = tuple(result.rank for result in ordered_results)
    if len(set(dense_ranks)) != len(dense_ranks):
        raise ValueError("dense ranks must be unique")

    return tuple(
        RerankCandidate(f"C{position:03d}", result)
        for position, result in enumerate(ordered_results, start=1)
    )


def build_reranking_messages(
    question: str,
    candidates: Sequence[RerankCandidate],
) -> list[dict[str, str]]:
    """Build one comparison prompt containing all candidate Chunks."""
    candidate_blocks = [
        "\n".join(
            [
                f"Candidate ID: {candidate.candidate_id}",
                f"Dense rank: {candidate.search_result.rank}",
                f"Document: {candidate.search_result.chunk.document_name}",
                f"Page: {candidate.search_result.chunk.page_number}",
                f"Chunk index: {candidate.search_result.chunk.chunk_index}",
                "Text:",
                candidate.search_result.chunk.text,
            ]
        )
        for candidate in candidates
    ]
    user_prompt = "\n".join(
        [
            "Question:",
            question,
            "",
            "Candidates:",
            "",
            "\n\n".join(candidate_blocks),
        ]
    )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def parse_reranking_output(
    model_output: str,
    candidates: Sequence[RerankCandidate],
) -> tuple[str, ...]:
    """Validate model IDs, deduplicate them, and append omissions densely."""
    try:
        payload = json.loads(model_output)
    except json.JSONDecodeError as exc:
        raise ExperimentalRerankingError(
            "LLM reranker output must be valid JSON"
        ) from exc

    if not isinstance(payload, dict):
        raise ExperimentalRerankingError(
            "LLM reranker output must be a JSON object"
        )
    if "ranking" not in payload:
        raise ExperimentalRerankingError(
            "LLM reranker output does not contain a ranking field"
        )

    ranking = payload["ranking"]
    if not isinstance(ranking, list):
        raise ExperimentalRerankingError(
            "LLM reranker ranking field must be an array"
        )

    supplied_ids = tuple(candidate.candidate_id for candidate in candidates)
    supplied_id_set = set(supplied_ids)
    ordered_ids: list[str] = []
    seen_ids: set[str] = set()

    for candidate_id in ranking:
        if not isinstance(candidate_id, str):
            raise ExperimentalRerankingError(
                "LLM reranker candidate IDs must be strings"
            )
        if candidate_id not in supplied_id_set:
            raise ExperimentalRerankingError(
                f"LLM reranker returned unknown candidate ID: {candidate_id}"
            )
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        ordered_ids.append(candidate_id)

    ordered_ids.extend(
        candidate_id
        for candidate_id in supplied_ids
        if candidate_id not in seen_ids
    )
    return tuple(ordered_ids)


def rerank_search_results(
    question: str,
    dense_results: Sequence[SearchResult],
    *,
    model: str,
    client: OllamaClient,
    context_size: int,
    max_output_tokens: int,
) -> ExperimentalRerankingOutcome:
    """Rerank one dense candidate pool with one local generation request."""
    clean_question = question.strip()
    if not clean_question:
        raise ValueError("question must not be empty")
    if not dense_results:
        raise ValueError("candidate pool must not be empty")
    clean_model = model.strip()
    if not clean_model:
        raise ValueError("model must not be empty")
    if context_size <= 0:
        raise ValueError("context_size must be greater than 0")
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be greater than 0")

    candidates = build_rerank_candidates(dense_results)
    messages = build_reranking_messages(clean_question, candidates)
    model_output = client.generate_chat(
        messages,
        model=clean_model,
        options={
            "num_ctx": context_size,
            "num_predict": max_output_tokens,
            "temperature": 0,
        },
    )
    ranked_ids = parse_reranking_output(model_output, candidates)
    candidates_by_id = {
        candidate.candidate_id: candidate.search_result
        for candidate in candidates
    }

    reranked_results = tuple(
        SearchResult(
            chunk=candidates_by_id[candidate_id].chunk,
            score=candidates_by_id[candidate_id].score,
            rank=rank,
        )
        for rank, candidate_id in enumerate(ranked_ids, start=1)
    )
    return ExperimentalRerankingOutcome(
        search_results=reranked_results,
        prompt_character_count=sum(
            len(message["content"]) for message in messages
        ),
    )
