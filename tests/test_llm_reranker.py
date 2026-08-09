from typing import Any

import pytest

from research_rag.experimental_llm_reranker import (
    ExperimentalRerankingError,
    build_rerank_candidates,
    build_reranking_messages,
    parse_reranking_output,
    rerank_search_results,
)
from research_rag.models import Chunk, SearchResult


def make_result(
    rank: int,
    *,
    page_number: int | None = None,
    chunk_index: int = 0,
    score: float | None = None,
    text: str | None = None,
) -> SearchResult:
    page = page_number if page_number is not None else rank
    return SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=page,
            chunk_index=chunk_index,
            text=text or f"Text for dense rank {rank}",
        ),
        score=score if score is not None else 1.0 / rank,
        rank=rank,
    )


def test_candidate_ids_are_stable_unique_and_follow_dense_rank() -> None:
    results = [make_result(3), make_result(1), make_result(2)]

    candidates = build_rerank_candidates(results)

    assert tuple(candidate.candidate_id for candidate in candidates) == (
        "C001",
        "C002",
        "C003",
    )
    assert tuple(candidate.search_result.rank for candidate in candidates) == (
        1,
        2,
        3,
    )
    assert len({candidate.candidate_id for candidate in candidates}) == 3


def test_prompt_contains_question_candidate_metadata_text_and_ranking_rules() -> None:
    candidates = build_rerank_candidates(
        [
            make_result(
                1,
                page_number=20,
                chunk_index=4,
                text="The direct answer is here.",
            )
        ]
    )

    messages = build_reranking_messages("正確な質問ですか？", candidates)

    assert messages[0]["role"] == "system"
    assert "scope and qualifiers" in messages[0]["content"]
    assert "dates, quantities, and named conditions" in messages[0]["content"]
    assert "contains the answer" in messages[0]["content"]
    assert "narrower or different question" in messages[0]["content"]
    user_prompt = messages[1]["content"]
    assert "正確な質問ですか？" in user_prompt
    assert "Candidate ID: C001" in user_prompt
    assert "Dense rank: 1" in user_prompt
    assert "Document: paper.pdf" in user_prompt
    assert "Page: 20" in user_prompt
    assert "Chunk index: 4" in user_prompt
    assert "The direct answer is here." in user_prompt


def test_valid_model_ranking_is_parsed_and_missing_candidates_are_appended() -> None:
    candidates = build_rerank_candidates(
        [make_result(1), make_result(2), make_result(3)]
    )

    candidate_ids = parse_reranking_output(
        '{"ranking": ["C003", "C001"]}',
        candidates,
    )

    assert candidate_ids == ("C003", "C001", "C002")


def test_duplicate_model_ids_keep_first_occurrence_deterministically() -> None:
    candidates = build_rerank_candidates(
        [make_result(1), make_result(2), make_result(3)]
    )

    candidate_ids = parse_reranking_output(
        '{"ranking": ["C002", "C002", "C001"]}',
        candidates,
    )

    assert candidate_ids == ("C002", "C001", "C003")


def test_unknown_candidate_id_raises_clear_error() -> None:
    candidates = build_rerank_candidates([make_result(1)])

    with pytest.raises(ExperimentalRerankingError, match="unknown candidate ID"):
        parse_reranking_output('{"ranking": ["C999"]}', candidates)


@pytest.mark.parametrize(
    ("model_output", "message"),
    [
        ("not json", "valid JSON"),
        ("[]", "JSON object"),
        ("{}", "ranking field"),
        ('{"ranking": "C001"}', "ranking field must be an array"),
        ('{"ranking": [1]}', "candidate IDs must be strings"),
    ],
)
def test_malformed_model_output_raises_clear_error(
    model_output: str,
    message: str,
) -> None:
    candidates = build_rerank_candidates([make_result(1)])

    with pytest.raises(ExperimentalRerankingError, match=message):
        parse_reranking_output(model_output, candidates)


class StubGenerationClient:
    def __init__(self, model_output: str) -> None:
        self.model_output = model_output
        self.calls: list[
            tuple[list[dict[str, str]], str, dict[str, object] | None]
        ] = []

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, object] | None = None,
    ) -> str:
        self.calls.append((messages, model, options))
        return self.model_output


def test_reranker_calls_generation_once_and_reassigns_ranks() -> None:
    dense_results = [
        make_result(1, score=0.9),
        make_result(2, score=0.8),
        make_result(3, score=0.7),
    ]
    client = StubGenerationClient('{"ranking": ["C002", "C003"]}')

    outcome = rerank_search_results(
        "Question",
        dense_results,
        model="generation-model",
        client=client,
        context_size=32768,
        max_output_tokens=512,
    )

    assert len(client.calls) == 1
    assert client.calls[0][1] == "generation-model"
    assert client.calls[0][2] == {
        "num_ctx": 32768,
        "num_predict": 512,
        "temperature": 0,
    }
    assert tuple(result.chunk for result in outcome.search_results) == (
        dense_results[1].chunk,
        dense_results[2].chunk,
        dense_results[0].chunk,
    )
    assert tuple(result.rank for result in outcome.search_results) == (1, 2, 3)
    assert tuple(result.score for result in outcome.search_results) == (
        0.8,
        0.7,
        0.9,
    )
    assert outcome.prompt_character_count > 0


@pytest.mark.parametrize(
    ("question", "results", "model", "message"),
    [
        (" ", [make_result(1)], "model", "question"),
        ("Question", [], "model", "candidate pool"),
        ("Question", [make_result(1)], " ", "model"),
    ],
)
def test_reranker_rejects_invalid_inputs_before_generation(
    question: str,
    results: list[SearchResult],
    model: str,
    message: str,
) -> None:
    client = StubGenerationClient('{"ranking": ["C001"]}')

    with pytest.raises(ValueError, match=message):
        rerank_search_results(
            question,
            results,
            model=model,
            client=client,
            context_size=32768,
            max_output_tokens=512,
        )

    assert client.calls == []


def test_candidate_builder_rejects_duplicate_dense_ranks() -> None:
    with pytest.raises(ValueError, match="dense ranks must be unique"):
        build_rerank_candidates([make_result(1), make_result(1)])


@pytest.mark.parametrize(
    ("context_size", "max_output_tokens", "message"),
    [
        (0, 512, "context_size"),
        (32768, 0, "max_output_tokens"),
    ],
)
def test_reranker_rejects_invalid_generation_limits(
    context_size: int,
    max_output_tokens: int,
    message: str,
) -> None:
    client = StubGenerationClient('{"ranking": ["C001"]}')

    with pytest.raises(ValueError, match=message):
        rerank_search_results(
            "Question",
            [make_result(1)],
            model="generation-model",
            client=client,
            context_size=context_size,
            max_output_tokens=max_output_tokens,
        )

    assert client.calls == []


def test_reranker_accepts_client_with_existing_generation_interface() -> None:
    client: Any = StubGenerationClient('{"ranking": ["C001"]}')

    outcome = rerank_search_results(
        "Question",
        [make_result(1)],
        model="generation-model",
        client=client,
        context_size=32768,
        max_output_tokens=512,
    )

    assert outcome.search_results[0].rank == 1
