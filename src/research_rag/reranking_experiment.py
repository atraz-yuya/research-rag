from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from .chunker import split_pages_into_chunks
from .embedder import embed_chunks
from .evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    RetrievalEvaluationSummary,
    aggregate_retrieval_results,
    evaluate_retrieval,
)
from .experimental_llm_reranker import rerank_search_results
from .models import SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


DEFAULT_CANDIDATE_POOL_SIZE = 30
DEFAULT_RERANK_CONTEXT_SIZE = 32768
DEFAULT_RERANK_MAX_OUTPUT_TOKENS = 512
FINAL_TOP_K = 3


@dataclass(frozen=True)
class RerankingCaseResult:
    """Dense and reranked observations for one evaluation question."""

    question: str
    relevant_pages: tuple[int, ...]
    dense_first_relevant_rank: int | None
    candidate_pool_has_relevant_page: bool
    baseline_result: RetrievalEvaluationResult
    reranked_result: RetrievalEvaluationResult
    reranked_first_relevant_rank: int | None
    baseline_top_results: tuple[SearchResult, ...]
    candidate_pool: tuple[SearchResult, ...]
    reranked_results: tuple[SearchResult, ...]
    prompt_character_count: int
    reranking_seconds: float


@dataclass(frozen=True)
class RerankingExperimentReport:
    """Formal Baseline-versus-LLM-reranking experiment results."""

    embedding_model: str
    generation_model: str
    candidate_pool_size: int
    context_size: int
    max_output_tokens: int
    cases: tuple[RerankingCaseResult, ...]
    baseline_summary: RetrievalEvaluationSummary
    reranked_summary: RetrievalEvaluationSummary
    candidate_pool_recall_rate: float
    improved_cases: tuple[int, ...]
    regressed_cases: tuple[int, ...]
    total_reranking_seconds: float


def run_reranking_experiment(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str,
    generation_model: str,
    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
    context_size: int = DEFAULT_RERANK_CONTEXT_SIZE,
    max_output_tokens: int = DEFAULT_RERANK_MAX_OUTPUT_TOKENS,
    client: OllamaClient | None = None,
) -> RerankingExperimentReport:
    """Compare production dense Top 3 with experimental LLM reranking."""
    clean_embedding_model, clean_generation_model = _validate_inputs(
        cases,
        embedding_model,
        generation_model,
        candidate_pool_size,
        context_size,
        max_output_tokens,
    )

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    chunks = split_pages_into_chunks(pages)
    if not chunks:
        raise ValueError("no searchable chunks were generated from PDF")

    embedded_chunks = embed_chunks(
        chunks,
        clean_embedding_model,
        ollama_client,
    )
    if not embedded_chunks:
        raise ValueError("no chunk embeddings were generated")

    case_results: list[RerankingCaseResult] = []
    for case in cases:
        question_embeddings = ollama_client.embed_texts(
            [case.question],
            model=clean_embedding_model,
        )
        if len(question_embeddings) != 1:
            raise ValueError(
                "question embedding response must contain exactly one vector"
            )
        query_embedding = question_embeddings[0]

        baseline_top_results = retrieve_similar_chunks(
            query_embedding,
            embedded_chunks,
            top_k=FINAL_TOP_K,
        )
        candidate_pool = retrieve_similar_chunks(
            query_embedding,
            embedded_chunks,
            top_k=candidate_pool_size,
        )
        full_ranking = retrieve_similar_chunks(
            query_embedding,
            embedded_chunks,
            top_k=len(embedded_chunks),
        )

        reranking_started = perf_counter()
        outcome = rerank_search_results(
            case.question,
            candidate_pool,
            model=clean_generation_model,
            client=ollama_client,
            context_size=context_size,
            max_output_tokens=max_output_tokens,
        )
        reranking_seconds = perf_counter() - reranking_started

        baseline_result = evaluate_retrieval(case, baseline_top_results)
        reranked_results = outcome.search_results
        reranked_result = evaluate_retrieval(
            case,
            reranked_results[:FINAL_TOP_K],
        )
        dense_full_result = evaluate_retrieval(case, full_ranking)
        reranked_full_result = evaluate_retrieval(case, reranked_results)

        relevant_pages = set(case.relevant_pages)
        case_results.append(
            RerankingCaseResult(
                question=case.question,
                relevant_pages=case.relevant_pages,
                dense_first_relevant_rank=(
                    dense_full_result.first_relevant_rank
                ),
                candidate_pool_has_relevant_page=any(
                    result.chunk.page_number in relevant_pages
                    for result in candidate_pool
                ),
                baseline_result=baseline_result,
                reranked_result=reranked_result,
                reranked_first_relevant_rank=(
                    reranked_full_result.first_relevant_rank
                ),
                baseline_top_results=tuple(baseline_top_results),
                candidate_pool=tuple(candidate_pool),
                reranked_results=reranked_results,
                prompt_character_count=outcome.prompt_character_count,
                reranking_seconds=reranking_seconds,
            )
        )

    baseline_summary = aggregate_retrieval_results(
        tuple(result.baseline_result for result in case_results)
    )
    reranked_summary = aggregate_retrieval_results(
        tuple(result.reranked_result for result in case_results)
    )

    improved_cases: list[int] = []
    regressed_cases: list[int] = []
    for case_number, result in enumerate(case_results, start=1):
        comparison = _compare_top_three_results(
            result.baseline_result,
            result.reranked_result,
        )
        if comparison < 0:
            improved_cases.append(case_number)
        elif comparison > 0:
            regressed_cases.append(case_number)

    return RerankingExperimentReport(
        embedding_model=clean_embedding_model,
        generation_model=clean_generation_model,
        candidate_pool_size=candidate_pool_size,
        context_size=context_size,
        max_output_tokens=max_output_tokens,
        cases=tuple(case_results),
        baseline_summary=baseline_summary,
        reranked_summary=reranked_summary,
        candidate_pool_recall_rate=(
            sum(
                result.candidate_pool_has_relevant_page
                for result in case_results
            )
            / len(case_results)
        ),
        improved_cases=tuple(improved_cases),
        regressed_cases=tuple(regressed_cases),
        total_reranking_seconds=sum(
            result.reranking_seconds for result in case_results
        ),
    )


def format_reranking_experiment_report(
    report: RerankingExperimentReport,
) -> str:
    """Format aggregate metrics and per-case retrieval movement."""
    lines = [
        f"Embedding model: {report.embedding_model}",
        f"Generation model: {report.generation_model}",
        f"Candidate pool size: {report.candidate_pool_size}",
        f"Reranker context size: {report.context_size}",
        f"Reranker max output tokens: {report.max_output_tokens}",
        "",
    ]

    for case_number, result in enumerate(report.cases, start=1):
        lines.extend(
            [
                f"Case {case_number}",
                f"Question: {result.question}",
                f"Relevant pages: {result.relevant_pages}",
                (
                    "Dense first relevant rank: "
                    f"{result.dense_first_relevant_rank}"
                ),
                (
                    "Candidate-pool relevant-page recall: "
                    f"{result.candidate_pool_has_relevant_page}"
                ),
                (
                    "Baseline Top 3 pages: "
                    f"{_pages(result.baseline_top_results)}"
                ),
                (
                    "Baseline first relevant rank: "
                    f"{result.baseline_result.first_relevant_rank}"
                ),
                (
                    "Reranked Top 3 pages: "
                    f"{_pages(result.reranked_results[:FINAL_TOP_K])}"
                ),
                (
                    "Reranked first relevant rank: "
                    f"{result.reranked_first_relevant_rank}"
                ),
                f"Prompt characters: {result.prompt_character_count}",
                f"Reranking seconds: {result.reranking_seconds:.3f}",
                "",
            ]
        )

    lines.extend(
        [
            "Summary",
            (
                "Baseline Hit@1: "
                f"{report.baseline_summary.hit_at_1_rate:.4f}"
            ),
            (
                "Baseline Hit@3: "
                f"{report.baseline_summary.hit_at_3_rate:.4f}"
            ),
            f"Baseline MRR: {report.baseline_summary.mrr:.4f}",
            (
                "Reranked Hit@1: "
                f"{report.reranked_summary.hit_at_1_rate:.4f}"
            ),
            (
                "Reranked Hit@3: "
                f"{report.reranked_summary.hit_at_3_rate:.4f}"
            ),
            f"Reranked MRR: {report.reranked_summary.mrr:.4f}",
            (
                f"Candidate-pool recall@{report.candidate_pool_size}: "
                f"{report.candidate_pool_recall_rate:.4f}"
            ),
            f"Improved cases: {report.improved_cases}",
            f"Regressed cases: {report.regressed_cases}",
            (
                "Total reranking seconds: "
                f"{report.total_reranking_seconds:.3f}"
            ),
        ]
    )
    return "\n".join(lines)


def _validate_inputs(
    cases: Sequence[RetrievalEvaluationCase],
    embedding_model: str,
    generation_model: str,
    candidate_pool_size: int,
    context_size: int,
    max_output_tokens: int,
) -> tuple[str, str]:
    if not cases:
        raise ValueError("evaluation cases must not be empty")
    clean_embedding_model = embedding_model.strip()
    if not clean_embedding_model:
        raise ValueError("embedding_model must not be empty")
    clean_generation_model = generation_model.strip()
    if not clean_generation_model:
        raise ValueError("generation_model must not be empty")
    if candidate_pool_size < FINAL_TOP_K:
        raise ValueError(
            f"candidate_pool_size must be at least {FINAL_TOP_K}"
        )
    if context_size <= 0:
        raise ValueError("context_size must be greater than 0")
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be greater than 0")
    return clean_embedding_model, clean_generation_model


def _compare_top_three_results(
    baseline: RetrievalEvaluationResult,
    reranked: RetrievalEvaluationResult,
) -> int:
    missing_rank = FINAL_TOP_K + 1
    baseline_rank = baseline.first_relevant_rank or missing_rank
    reranked_rank = reranked.first_relevant_rank or missing_rank
    if reranked_rank < baseline_rank:
        return -1
    if reranked_rank > baseline_rank:
        return 1
    return 0


def _pages(results: Sequence[SearchResult]) -> tuple[int, ...]:
    return tuple(result.chunk.page_number for result in results)
