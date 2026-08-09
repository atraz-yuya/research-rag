from pathlib import Path
from typing import Any

import pytest

from research_rag import reranking_experiment
from research_rag.evaluation import RetrievalEvaluationCase
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult
from research_rag.reranking_experiment import (
    RerankingExperimentReport,
    format_reranking_experiment_report,
    run_reranking_experiment,
)


def make_result(
    chunk: Chunk,
    rank: int,
    *,
    score: float | None = None,
) -> SearchResult:
    return SearchResult(
        chunk=chunk,
        score=score if score is not None else 1.0 / rank,
        rank=rank,
    )


class StubExperimentClient:
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

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        options: dict[str, object] | None = None,
    ) -> str:
        self.events.append(("generation", messages, model, options))
        if "Question one" in messages[1]["content"]:
            return '{"ranking": ["C004", "C001", "C002", "C003"]}'
        return '{"ranking": ["C002", "C003", "C004", "C001"]}'


def test_runner_reuses_document_work_and_query_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (3,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [
        Chunk("paper.pdf", 10, 0, "First competitor"),
        Chunk("paper.pdf", 11, 0, "Second competitor"),
        Chunk("paper.pdf", 12, 0, "Third competitor"),
        Chunk("paper.pdf", 2, 0, "Answer to question one"),
    ]
    embedded_chunks = [
        EmbeddedChunk(chunk, (float(index), 1.0))
        for index, chunk in enumerate(chunks, start=1)
    ]
    query_embeddings = {
        "Question one": [1.0, 0.0],
        "Question two": [0.0, 1.0],
    }
    events: list[tuple[Any, ...]] = []
    client = StubExperimentClient(query_embeddings, events)

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
        if query_embedding is query_embeddings["Question one"]:
            ordered_chunks = chunks
        else:
            ordered_chunks = (
                Chunk("paper.pdf", 3, 0, "Answer to question two"),
                chunks[0],
                chunks[1],
                chunks[2],
            )
        return [
            make_result(chunk, rank)
            for rank, chunk in enumerate(ordered_chunks[:top_k], start=1)
        ]

    monkeypatch.setattr(reranking_experiment, "extract_page_texts", fake_extract)
    monkeypatch.setattr(
        reranking_experiment,
        "split_pages_into_chunks",
        fake_split,
    )
    monkeypatch.setattr(reranking_experiment, "embed_chunks", fake_embed)
    monkeypatch.setattr(
        reranking_experiment,
        "retrieve_similar_chunks",
        fake_retrieve,
    )

    report = run_reranking_experiment(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        generation_model="generation-model",
        candidate_pool_size=30,
        client=client,
    )

    assert len(report.cases) == 2
    assert events.count(("pdf", pdf_path)) == 1
    assert events.count(("chunk", pages)) == 1
    assert events.count(
        ("document_embedding", chunks, "embedding-model")
    ) == 1
    question_events = [event for event in events if event[0] == "question_embedding"]
    assert [event[1] for event in question_events] == [
        ["Question one"],
        ["Question two"],
    ]
    assert len(question_events) == 2
    generation_events = [event for event in events if event[0] == "generation"]
    assert len(generation_events) == 2
    assert all(event[2] == "generation-model" for event in generation_events)
    assert all(
        event[3]
        == {"num_ctx": 32768, "num_predict": 512, "temperature": 0}
        for event in generation_events
    )

    retriever_events = [event for event in events if event[0] == "retriever"]
    assert [event[2] for event in retriever_events] == [3, 30, 4, 3, 30, 4]
    assert all(
        event[1] is query_embeddings["Question one"]
        for event in retriever_events[:3]
    )
    assert all(
        event[1] is query_embeddings["Question two"]
        for event in retriever_events[3:]
    )

    first_case = report.cases[0]
    assert first_case.dense_first_relevant_rank == 4
    assert first_case.candidate_pool_has_relevant_page is True
    assert first_case.baseline_result.first_relevant_rank is None
    assert first_case.reranked_first_relevant_rank == 1
    assert first_case.reranked_result.first_relevant_rank == 1
    assert first_case.reranked_results[0].chunk.page_number == 2
    assert first_case.prompt_character_count > 0
    assert first_case.reranking_seconds >= 0.0

    second_case = report.cases[1]
    assert second_case.dense_first_relevant_rank == 1
    assert second_case.baseline_result.first_relevant_rank == 1
    assert second_case.reranked_first_relevant_rank == 4
    assert second_case.reranked_result.first_relevant_rank is None
    assert report.candidate_pool_recall_rate == pytest.approx(1.0)
    assert report.improved_cases == (1,)
    assert report.regressed_cases == (2,)


def test_report_contains_metrics_pool_recall_and_per_case_movement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    client = StubExperimentClient({"Question": [1.0, 0.0]}, events)
    chunks = [
        Chunk("paper.pdf", 10, 0, "Competitor"),
        Chunk("paper.pdf", 20, 1, "Direct answer"),
        Chunk("paper.pdf", 30, 0, "Other"),
    ]
    embedded = [EmbeddedChunk(chunk, (1.0, 0.0)) for chunk in chunks]

    monkeypatch.setattr(
        reranking_experiment,
        "extract_page_texts",
        lambda _: [PageText("paper.pdf", 1, "Page")],
    )
    monkeypatch.setattr(
        reranking_experiment,
        "split_pages_into_chunks",
        lambda _: chunks,
    )
    monkeypatch.setattr(
        reranking_experiment,
        "embed_chunks",
        lambda *_: embedded,
    )
    monkeypatch.setattr(
        reranking_experiment,
        "retrieve_similar_chunks",
        lambda _query, _chunks, top_k: [
            make_result(chunk, rank)
            for rank, chunk in enumerate(chunks[:top_k], start=1)
        ],
    )
    monkeypatch.setattr(
        client,
        "generate_chat",
        lambda messages, model, options=None: (
            '{"ranking": ["C002", "C001", "C003"]}'
        ),
    )

    report = run_reranking_experiment(
        Path("paper.pdf"),
        (RetrievalEvaluationCase("Question", (20,)),),
        embedding_model="embedding-model",
        generation_model="generation-model",
        client=client,
    )
    output = format_reranking_experiment_report(report)

    assert isinstance(report, RerankingExperimentReport)
    assert "Embedding model: embedding-model" in output
    assert "Generation model: generation-model" in output
    assert "Candidate pool size: 30" in output
    assert "Reranker context size: 32768" in output
    assert "Reranker max output tokens: 512" in output
    assert "Dense first relevant rank: 2" in output
    assert "Candidate-pool relevant-page recall: True" in output
    assert "Baseline Top 3 pages: (10, 20, 30)" in output
    assert "Reranked Top 3 pages: (20, 10, 30)" in output
    assert "Reranked first relevant rank: 1" in output
    assert "Baseline Hit@1:" in output
    assert "Reranked Hit@3:" in output
    assert "Candidate-pool recall@30:" in output
    assert "Improved cases: (1,)" in output
    assert "Regressed cases: ()" in output


@pytest.mark.parametrize(
    (
        "cases",
        "embedding_model",
        "generation_model",
        "candidate_pool_size",
        "message",
    ),
    [
        ((), "embed", "generate", 30, "cases"),
        (
            (RetrievalEvaluationCase("Question", (1,)),),
            " ",
            "generate",
            30,
            "embedding_model",
        ),
        (
            (RetrievalEvaluationCase("Question", (1,)),),
            "embed",
            " ",
            30,
            "generation_model",
        ),
        (
            (RetrievalEvaluationCase("Question", (1,)),),
            "embed",
            "generate",
            2,
            "candidate_pool_size",
        ),
    ],
)
def test_runner_rejects_invalid_inputs_before_pdf_work(
    monkeypatch: pytest.MonkeyPatch,
    cases: tuple[RetrievalEvaluationCase, ...],
    embedding_model: str,
    generation_model: str,
    candidate_pool_size: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        reranking_experiment,
        "extract_page_texts",
        lambda _: pytest.fail("PDF processing must not start"),
    )

    with pytest.raises(ValueError, match=message):
        run_reranking_experiment(
            Path("paper.pdf"),
            cases,
            embedding_model=embedding_model,
            generation_model=generation_model,
            candidate_pool_size=candidate_pool_size,
        )


@pytest.mark.parametrize(
    ("context_size", "max_output_tokens", "message"),
    [
        (0, 512, "context_size"),
        (32768, 0, "max_output_tokens"),
    ],
)
def test_runner_rejects_invalid_generation_limits_before_pdf_work(
    monkeypatch: pytest.MonkeyPatch,
    context_size: int,
    max_output_tokens: int,
    message: str,
) -> None:
    monkeypatch.setattr(
        reranking_experiment,
        "extract_page_texts",
        lambda _: pytest.fail("PDF processing must not start"),
    )

    with pytest.raises(ValueError, match=message):
        run_reranking_experiment(
            Path("paper.pdf"),
            (RetrievalEvaluationCase("Question", (1,)),),
            embedding_model="embedding-model",
            generation_model="generation-model",
            context_size=context_size,
            max_output_tokens=max_output_tokens,
        )
