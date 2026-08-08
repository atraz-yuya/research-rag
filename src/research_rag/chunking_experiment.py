from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .chunker import split_pages_into_chunks
from .embedder import embed_chunks
from .evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    RetrievalEvaluationSummary,
    aggregate_retrieval_results,
    evaluate_retrieval,
)
from .experimental_chunker import split_pages_into_heading_aware_chunks
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


EXPERIMENT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
EXPERIMENT_TOP_K = 3


@dataclass(frozen=True)
class ChunkingCaseComparison:
    """Baseline and candidate retrieval observations for one case."""

    question: str
    relevant_pages: tuple[int, ...]
    baseline_retrieved_pages: tuple[int, ...]
    candidate_retrieved_pages: tuple[int, ...]
    baseline_first_relevant_rank: int | None
    candidate_first_relevant_rank: int | None


@dataclass(frozen=True)
class ChunkingExperimentReport:
    """Aggregate and per-case results for a chunking comparison."""

    comparisons: tuple[ChunkingCaseComparison, ...]
    baseline_summary: RetrievalEvaluationSummary
    candidate_summary: RetrievalEvaluationSummary

    @property
    def hit_at_1_delta(self) -> float:
        return (
            self.candidate_summary.hit_at_1_rate
            - self.baseline_summary.hit_at_1_rate
        )

    @property
    def hit_at_3_delta(self) -> float:
        return (
            self.candidate_summary.hit_at_3_rate
            - self.baseline_summary.hit_at_3_rate
        )

    @property
    def mrr_delta(self) -> float:
        return self.candidate_summary.mrr - self.baseline_summary.mrr


def run_chunking_experiment(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str = EXPERIMENT_EMBEDDING_MODEL,
    client: OllamaClient | None = None,
) -> ChunkingExperimentReport:
    """Compare baseline and heading-aware chunks under equal conditions."""
    if not cases:
        raise ValueError("experiment cases must not be empty")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)

    baseline_chunks = split_pages_into_chunks(pages)
    if not baseline_chunks:
        raise ValueError("baseline chunker generated no searchable chunks")

    candidate_chunks = split_pages_into_heading_aware_chunks(pages)
    if not candidate_chunks:
        raise ValueError("candidate chunker generated no searchable chunks")

    baseline_embedded_chunks = embed_chunks(
        baseline_chunks,
        clean_model,
        ollama_client,
    )
    if not baseline_embedded_chunks:
        raise ValueError("no baseline chunk embeddings were generated")

    candidate_embedded_chunks = embed_chunks(
        candidate_chunks,
        clean_model,
        ollama_client,
    )
    if not candidate_embedded_chunks:
        raise ValueError("no candidate chunk embeddings were generated")

    baseline_results: list[RetrievalEvaluationResult] = []
    candidate_results: list[RetrievalEvaluationResult] = []
    comparisons: list[ChunkingCaseComparison] = []

    for case in cases:
        question_embeddings = ollama_client.embed_texts(
            [case.question],
            model=clean_model,
        )
        if len(question_embeddings) != 1:
            raise ValueError(
                "question embedding response must contain exactly one vector"
            )
        query_embedding = question_embeddings[0]

        baseline_search_results = retrieve_similar_chunks(
            query_embedding,
            baseline_embedded_chunks,
            top_k=EXPERIMENT_TOP_K,
        )
        candidate_search_results = retrieve_similar_chunks(
            query_embedding,
            candidate_embedded_chunks,
            top_k=EXPERIMENT_TOP_K,
        )

        baseline_result = evaluate_retrieval(case, baseline_search_results)
        candidate_result = evaluate_retrieval(case, candidate_search_results)
        baseline_results.append(baseline_result)
        candidate_results.append(candidate_result)
        comparisons.append(
            _build_case_comparison(
                case,
                baseline_result,
                candidate_result,
            )
        )

    return ChunkingExperimentReport(
        comparisons=tuple(comparisons),
        baseline_summary=aggregate_retrieval_results(baseline_results),
        candidate_summary=aggregate_retrieval_results(candidate_results),
    )


def format_chunking_experiment_report(
    report: ChunkingExperimentReport,
) -> str:
    """Format aggregate metrics, deltas, and per-case comparisons."""
    lines = [
        "Baseline",
        f"Hit@1 rate: {report.baseline_summary.hit_at_1_rate:.4f}",
        f"Hit@3 rate: {report.baseline_summary.hit_at_3_rate:.4f}",
        f"MRR: {report.baseline_summary.mrr:.4f}",
        "",
        "Candidate",
        f"Hit@1 rate: {report.candidate_summary.hit_at_1_rate:.4f}",
        f"Hit@3 rate: {report.candidate_summary.hit_at_3_rate:.4f}",
        f"MRR: {report.candidate_summary.mrr:.4f}",
        "",
        "Delta (Candidate - Baseline)",
        f"Hit@1 delta: {report.hit_at_1_delta:+.4f}",
        f"Hit@3 delta: {report.hit_at_3_delta:+.4f}",
        f"MRR delta: {report.mrr_delta:+.4f}",
        "",
        "Per-case comparison",
    ]

    for case_index, comparison in enumerate(report.comparisons, start=1):
        lines.extend(
            [
                f"Case {case_index}",
                f"question: {comparison.question}",
                f"relevant_pages: {comparison.relevant_pages}",
                (
                    "baseline retrieved_pages: "
                    f"{comparison.baseline_retrieved_pages}"
                ),
                (
                    "candidate retrieved_pages: "
                    f"{comparison.candidate_retrieved_pages}"
                ),
                (
                    "baseline first_relevant_rank: "
                    f"{comparison.baseline_first_relevant_rank}"
                ),
                (
                    "candidate first_relevant_rank: "
                    f"{comparison.candidate_first_relevant_rank}"
                ),
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _build_case_comparison(
    case: RetrievalEvaluationCase,
    baseline_result: RetrievalEvaluationResult,
    candidate_result: RetrievalEvaluationResult,
) -> ChunkingCaseComparison:
    return ChunkingCaseComparison(
        question=case.question,
        relevant_pages=case.relevant_pages,
        baseline_retrieved_pages=baseline_result.retrieved_pages,
        candidate_retrieved_pages=candidate_result.retrieved_pages,
        baseline_first_relevant_rank=baseline_result.first_relevant_rank,
        candidate_first_relevant_rank=candidate_result.first_relevant_rank,
    )
