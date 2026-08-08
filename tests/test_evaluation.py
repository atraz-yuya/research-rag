from pathlib import Path
from typing import Any

import pytest

from research_rag import evaluation_runner
from research_rag.evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    aggregate_retrieval_results,
    evaluate_retrieval,
)
from research_rag.evaluation_runner import (
    BASELINE_EVALUATION_CASES,
    RetrievalEvaluationReport,
    format_retrieval_evaluation_report,
    run_retrieval_evaluation,
)
from research_rag.models import Chunk, EmbeddedChunk, PageText, SearchResult


def make_search_result(
    page_number: int,
    rank: int,
    *,
    chunk_index: int = 0,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=page_number,
            chunk_index=chunk_index,
            text=f"Page {page_number}, chunk {chunk_index}",
        ),
        score=1.0 / rank,
        rank=rank,
    )


def evaluate_at_rank(rank: int) -> RetrievalEvaluationResult:
    results = [
        make_search_result(page_number=page, rank=page)
        for page in range(1, rank)
    ]
    results.append(make_search_result(page_number=12, rank=rank))
    case = RetrievalEvaluationCase(
        question="Which datasets are used?",
        relevant_pages=(12,),
    )
    return evaluate_retrieval(case, results)


def test_relevant_page_at_rank_1_is_hit_at_1() -> None:
    result = evaluate_at_rank(1)

    assert result.hit_at_1 is True
    assert result.hit_at_3 is True
    assert result.first_relevant_rank == 1


def test_relevant_page_at_rank_2_is_only_hit_at_3() -> None:
    result = evaluate_at_rank(2)

    assert result.hit_at_1 is False
    assert result.hit_at_3 is True
    assert result.first_relevant_rank == 2


def test_relevant_page_at_rank_3_is_hit_at_3() -> None:
    result = evaluate_at_rank(3)

    assert result.hit_at_1 is False
    assert result.hit_at_3 is True
    assert result.first_relevant_rank == 3


def test_relevant_page_at_rank_4_is_not_hit_at_3() -> None:
    result = evaluate_at_rank(4)

    assert result.hit_at_1 is False
    assert result.hit_at_3 is False
    assert result.first_relevant_rank == 4


def test_missing_relevant_page_has_no_first_relevant_rank() -> None:
    case = RetrievalEvaluationCase("Question", (12,))

    result = evaluate_retrieval(
        case,
        [make_search_result(8, 1), make_search_result(4, 2)],
    )

    assert result.hit_at_1 is False
    assert result.hit_at_3 is False
    assert result.first_relevant_rank is None


def test_any_of_multiple_relevant_pages_counts_as_a_hit() -> None:
    case = RetrievalEvaluationCase("Question", (4, 12))

    result = evaluate_retrieval(
        case,
        [make_search_result(8, 1), make_search_result(12, 2)],
    )

    assert result.hit_at_3 is True
    assert result.first_relevant_rank == 2


def test_multiple_chunks_from_same_page_use_first_matching_rank() -> None:
    case = RetrievalEvaluationCase("Question", (12,))
    search_results = [
        make_search_result(8, 1),
        make_search_result(12, 2, chunk_index=0),
        make_search_result(12, 3, chunk_index=1),
    ]

    result = evaluate_retrieval(case, search_results)

    assert result.retrieved_pages == (8, 12, 12)
    assert result.hit_at_3 is True
    assert result.first_relevant_rank == 2


def test_retrieved_pages_are_stored_in_rank_order() -> None:
    case = RetrievalEvaluationCase("Question", (2,))
    unordered_results = [
        make_search_result(30, 3),
        make_search_result(10, 1),
        make_search_result(20, 2),
    ]

    result = evaluate_retrieval(case, unordered_results)

    assert result.retrieved_pages == (10, 20, 30)
    assert result.first_relevant_rank is None


def sample_evaluation_results() -> list[RetrievalEvaluationResult]:
    return [
        evaluate_at_rank(1),
        evaluate_at_rank(2),
        evaluate_retrieval(
            RetrievalEvaluationCase("Missing", (12,)),
            [make_search_result(8, 1)],
        ),
    ]


def test_aggregate_calculates_hit_at_1_rate() -> None:
    summary = aggregate_retrieval_results(sample_evaluation_results())

    assert summary.case_count == 3
    assert summary.hit_at_1_rate == pytest.approx(1.0 / 3.0)


def test_aggregate_calculates_hit_at_3_rate() -> None:
    summary = aggregate_retrieval_results(sample_evaluation_results())

    assert summary.hit_at_3_rate == pytest.approx(2.0 / 3.0)


def test_aggregate_calculates_mean_reciprocal_rank() -> None:
    summary = aggregate_retrieval_results(sample_evaluation_results())

    assert summary.mrr == pytest.approx((1.0 + 0.5 + 0.0) / 3.0)


def test_aggregate_rejects_empty_results() -> None:
    with pytest.raises(ValueError, match="evaluation results must not be empty"):
        aggregate_retrieval_results([])


@pytest.mark.parametrize(
    ("question", "relevant_pages", "message"),
    [
        ("   ", (1,), "question must not be empty"),
        ("Question", (), "relevant_pages must not be empty"),
        ("Question", (0,), "relevant_pages must contain 1-based page numbers"),
    ],
)
def test_evaluation_case_rejects_invalid_input(
    question: str,
    relevant_pages: tuple[int, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        RetrievalEvaluationCase(question, relevant_pages)


class StubEvaluationClient:
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
        self.events.append(("question_embedding", texts, model))
        return [self.embeddings[texts[0]]]


def test_runner_reuses_pdf_and_chunk_embeddings_across_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = Path("paper.pdf")
    cases = (
        RetrievalEvaluationCase("Question one", (2,)),
        RetrievalEvaluationCase("Question two", (9,)),
    )
    pages = [PageText("paper.pdf", 1, "Page text")]
    chunks = [Chunk("paper.pdf", 1, 0, "Chunk text")]
    embedded_chunks = [EmbeddedChunk(chunks[0], (1.0, 0.0))]
    first_search_results = [make_search_result(2, 1)]
    second_search_results = [
        make_search_result(8, 1),
        make_search_result(9, 2),
    ]
    events: list[tuple[Any, ...]] = []
    client = StubEvaluationClient(
        {
            "Question one": [1.0, 0.0],
            "Question two": [0.0, 1.0],
        },
        events,
    )
    real_evaluate_retrieval = evaluate_retrieval
    real_aggregate_results = aggregate_retrieval_results

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
            ("chunk_embedding", received_chunks, model, received_client)
        )
        return embedded_chunks

    def fake_retrieve_similar_chunks(
        query_embedding: list[float],
        received_chunks: list[EmbeddedChunk],
    ) -> list[SearchResult]:
        events.append(("retriever", query_embedding, received_chunks))
        if query_embedding == [1.0, 0.0]:
            return first_search_results
        return second_search_results

    def fake_evaluate_retrieval(
        case: RetrievalEvaluationCase,
        search_results: list[SearchResult],
    ) -> RetrievalEvaluationResult:
        events.append(("evaluation", case, search_results))
        return real_evaluate_retrieval(case, search_results)

    def fake_aggregate_retrieval_results(
        results: list[RetrievalEvaluationResult],
    ) -> Any:
        events.append(("aggregate", results))
        return real_aggregate_results(results)

    monkeypatch.setattr(
        evaluation_runner,
        "extract_page_texts",
        fake_extract_page_texts,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "split_pages_into_chunks",
        fake_split_pages_into_chunks,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "embed_chunks",
        fake_embed_chunks,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "retrieve_similar_chunks",
        fake_retrieve_similar_chunks,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "evaluate_retrieval",
        fake_evaluate_retrieval,
    )
    monkeypatch.setattr(
        evaluation_runner,
        "aggregate_retrieval_results",
        fake_aggregate_retrieval_results,
    )

    report = run_retrieval_evaluation(
        pdf_path,
        cases,
        embedding_model="embedding-model",
        client=client,
    )

    assert report.results[0].retrieved_pages == (2,)
    assert report.results[1].retrieved_pages == (8, 9)
    assert report.summary.hit_at_1_rate == pytest.approx(0.5)
    assert report.summary.hit_at_3_rate == pytest.approx(1.0)
    assert report.summary.mrr == pytest.approx(0.75)
    assert events == [
        ("pdf_reader", pdf_path),
        ("chunker", pages),
        ("chunk_embedding", chunks, "embedding-model", client),
        ("question_embedding", ["Question one"], "embedding-model"),
        ("retriever", [1.0, 0.0], embedded_chunks),
        ("evaluation", cases[0], first_search_results),
        ("question_embedding", ["Question two"], "embedding-model"),
        ("retriever", [0.0, 1.0], embedded_chunks),
        ("evaluation", cases[1], second_search_results),
        ("aggregate", list(report.results)),
    ]


def test_runner_rejects_empty_cases_before_pdf_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_extract(pdf_path: Path) -> list[PageText]:
        raise AssertionError("PDF must not be processed")

    monkeypatch.setattr(evaluation_runner, "extract_page_texts", fail_extract)

    with pytest.raises(ValueError, match="evaluation cases must not be empty"):
        run_retrieval_evaluation(
            Path("paper.pdf"),
            [],
            embedding_model="embedding-model",
        )


def test_baseline_contains_the_twelve_confirmed_cases() -> None:
    assert BASELINE_EVALUATION_CASES == (
        RetrievalEvaluationCase("資金洗浄の3つの段階は何ですか？", (2,)),
        RetrievalEvaluationCase(
            "What are the three stages of money laundering?",
            (2,),
        ),
        RetrievalEvaluationCase(
            "この文献レビューでは、論文をどの7つの基準で分類していますか？",
            (3,),
        ),
        RetrievalEvaluationCase(
            "文献レビューの83本の非レビュー論文について、"
            "最も多く利用されている学習方法は何ですか？",
            (9,),
        ),
        RetrievalEvaluationCase(
            "2018年以降に利用が増え始めたネットワーク分析手法は何ですか？",
            (9,),
        ),
        RetrievalEvaluationCase(
            "AUC-PRがAUC-ROCよりAMLの評価に適している理由は何ですか？",
            (23,),
        ),
        RetrievalEvaluationCase(
            "最も多くの研究で利用されているオープンソースデータセットは何で、"
            "何本の論文で使われていますか？",
            (11, 12),
        ),
        RetrievalEvaluationCase(
            "実験評価ではどの2つのデータセットを使用していますか？",
            (20,),
        ),
        RetrievalEvaluationCase(
            "Ellipticデータセットには何個のノードとエッジがありますか？",
            (20,),
        ),
        RetrievalEvaluationCase(
            "Ellipticの教師あり学習でAUC-PRが最も高かったモデルは何ですか？",
            (24,),
        ),
        RetrievalEvaluationCase(
            "EllipticとIBM-AMLで教師なし学習の結果が大きく異なった理由として、"
            "著者らは何を挙げていますか？",
            (25, 26),
        ),
        RetrievalEvaluationCase(
            "著者らがsynthetic dataを使ったAML評価について注意すべきだと"
            "結論づけている理由は何ですか？",
            (26, 29),
        ),
    )


def test_report_format_includes_case_metrics_and_summary() -> None:
    result = evaluate_at_rank(2)
    summary = aggregate_retrieval_results([result])
    report = RetrievalEvaluationReport((result,), summary)

    output = format_retrieval_evaluation_report(report)

    assert "question: Which datasets are used?" in output
    assert "relevant_pages: (12,)" in output
    assert "retrieved_pages: (1, 12)" in output
    assert "first_relevant_rank: 2" in output
    assert "Hit@1: False" in output
    assert "Hit@3: True" in output
    assert "Hit@1 rate: 0.0000" in output
    assert "Hit@3 rate: 1.0000" in output
    assert "MRR: 0.5000" in output
