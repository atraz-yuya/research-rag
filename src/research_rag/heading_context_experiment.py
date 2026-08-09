from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .chunker import split_pages_into_chunks
from .chunking_experiment import (
    EXPERIMENT_EMBEDDING_MODEL,
    EXPERIMENT_TOP_K,
)
from .embedder import embed_chunks
from .evaluation import (
    RetrievalEvaluationCase,
    RetrievalEvaluationResult,
    RetrievalEvaluationSummary,
    aggregate_retrieval_results,
    evaluate_retrieval,
)
from .experimental_chunker_v2 import (
    split_pages_into_strict_heading_aware_chunks,
)
from .experimental_chunker_v3 import split_pages_into_heading_context_chunks
from .models import EmbeddedChunk
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


@dataclass(frozen=True)
class HeadingContextVariantResult:
    """Chunk count and retrieval metrics for one experiment variant."""

    total_chunk_count: int
    summary: RetrievalEvaluationSummary


@dataclass(frozen=True)
class HeadingContextMetricDelta:
    """Retrieval metric differences between two variants."""

    hit_at_1: float
    hit_at_3: float
    mrr: float


@dataclass(frozen=True)
class HeadingContextCaseComparison:
    """Per-case retrieval output for Baseline, Candidate v2, and v3."""

    question: str
    relevant_pages: tuple[int, ...]
    baseline_retrieved_pages: tuple[int, ...]
    candidate_v2_retrieved_pages: tuple[int, ...]
    candidate_v3_retrieved_pages: tuple[int, ...]
    baseline_first_relevant_rank: int | None
    candidate_v2_first_relevant_rank: int | None
    candidate_v3_first_relevant_rank: int | None


@dataclass(frozen=True)
class HeadingContextExperimentReport:
    """Aggregate and per-case heading-context comparison results."""

    comparisons: tuple[HeadingContextCaseComparison, ...]
    baseline: HeadingContextVariantResult
    candidate_v2: HeadingContextVariantResult
    candidate_v3: HeadingContextVariantResult

    @property
    def candidate_v2_minus_baseline(self) -> HeadingContextMetricDelta:
        return _calculate_delta(self.candidate_v2, self.baseline)

    @property
    def candidate_v3_minus_baseline(self) -> HeadingContextMetricDelta:
        return _calculate_delta(self.candidate_v3, self.baseline)

    @property
    def candidate_v3_minus_candidate_v2(self) -> HeadingContextMetricDelta:
        return _calculate_delta(self.candidate_v3, self.candidate_v2)


def run_heading_context_experiment(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str = EXPERIMENT_EMBEDDING_MODEL,
    client: OllamaClient | None = None,
) -> HeadingContextExperimentReport:
    """Compare Baseline, Candidate v2, and Candidate v3 fairly."""
    if not cases:
        raise ValueError("experiment cases must not be empty")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    baseline_chunks = split_pages_into_chunks(pages)
    candidate_v2_chunks = split_pages_into_strict_heading_aware_chunks(pages)
    candidate_v3_chunks = split_pages_into_heading_context_chunks(pages)
    _validate_items("baseline chunks", baseline_chunks)
    _validate_items("Candidate v2 chunks", candidate_v2_chunks)
    _validate_items("Candidate v3 chunks", candidate_v3_chunks)

    baseline_embedded = embed_chunks(
        baseline_chunks,
        clean_model,
        ollama_client,
    )
    candidate_v2_embedded = embed_chunks(
        candidate_v2_chunks,
        clean_model,
        ollama_client,
    )
    candidate_v3_embedded = embed_chunks(
        candidate_v3_chunks,
        clean_model,
        ollama_client,
    )
    _validate_items("baseline chunk embeddings", baseline_embedded)
    _validate_items("Candidate v2 chunk embeddings", candidate_v2_embedded)
    _validate_items("Candidate v3 chunk embeddings", candidate_v3_embedded)

    baseline_results: list[RetrievalEvaluationResult] = []
    candidate_v2_results: list[RetrievalEvaluationResult] = []
    candidate_v3_results: list[RetrievalEvaluationResult] = []
    comparisons: list[HeadingContextCaseComparison] = []

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

        baseline_result = _evaluate_variant(
            case,
            query_embedding,
            baseline_embedded,
        )
        candidate_v2_result = _evaluate_variant(
            case,
            query_embedding,
            candidate_v2_embedded,
        )
        candidate_v3_result = _evaluate_variant(
            case,
            query_embedding,
            candidate_v3_embedded,
        )
        baseline_results.append(baseline_result)
        candidate_v2_results.append(candidate_v2_result)
        candidate_v3_results.append(candidate_v3_result)
        comparisons.append(
            HeadingContextCaseComparison(
                question=case.question,
                relevant_pages=case.relevant_pages,
                baseline_retrieved_pages=baseline_result.retrieved_pages,
                candidate_v2_retrieved_pages=(
                    candidate_v2_result.retrieved_pages
                ),
                candidate_v3_retrieved_pages=(
                    candidate_v3_result.retrieved_pages
                ),
                baseline_first_relevant_rank=(
                    baseline_result.first_relevant_rank
                ),
                candidate_v2_first_relevant_rank=(
                    candidate_v2_result.first_relevant_rank
                ),
                candidate_v3_first_relevant_rank=(
                    candidate_v3_result.first_relevant_rank
                ),
            )
        )

    return HeadingContextExperimentReport(
        comparisons=tuple(comparisons),
        baseline=HeadingContextVariantResult(
            total_chunk_count=len(baseline_chunks),
            summary=aggregate_retrieval_results(baseline_results),
        ),
        candidate_v2=HeadingContextVariantResult(
            total_chunk_count=len(candidate_v2_chunks),
            summary=aggregate_retrieval_results(candidate_v2_results),
        ),
        candidate_v3=HeadingContextVariantResult(
            total_chunk_count=len(candidate_v3_chunks),
            summary=aggregate_retrieval_results(candidate_v3_results),
        ),
    )


def format_heading_context_experiment_report(
    report: HeadingContextExperimentReport,
) -> str:
    """Format metrics, deltas, and per-case retrieval results."""
    lines: list[str] = []
    _append_variant(lines, "Baseline", report.baseline)
    _append_variant(lines, "Candidate v2", report.candidate_v2)
    _append_variant(lines, "Candidate v3", report.candidate_v3)
    _append_delta(
        lines,
        "Candidate v2 - Baseline",
        report.candidate_v2_minus_baseline,
    )
    _append_delta(
        lines,
        "Candidate v3 - Baseline",
        report.candidate_v3_minus_baseline,
    )
    _append_delta(
        lines,
        "Candidate v3 - Candidate v2",
        report.candidate_v3_minus_candidate_v2,
    )
    lines.append("Per-case comparison")

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
                    "Candidate v2 retrieved_pages: "
                    f"{comparison.candidate_v2_retrieved_pages}"
                ),
                (
                    "Candidate v3 retrieved_pages: "
                    f"{comparison.candidate_v3_retrieved_pages}"
                ),
                (
                    "baseline first_relevant_rank: "
                    f"{comparison.baseline_first_relevant_rank}"
                ),
                (
                    "Candidate v2 first_relevant_rank: "
                    f"{comparison.candidate_v2_first_relevant_rank}"
                ),
                (
                    "Candidate v3 first_relevant_rank: "
                    f"{comparison.candidate_v3_first_relevant_rank}"
                ),
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _evaluate_variant(
    case: RetrievalEvaluationCase,
    query_embedding: Sequence[float],
    embedded_chunks: Sequence[EmbeddedChunk],
) -> RetrievalEvaluationResult:
    return evaluate_retrieval(
        case,
        retrieve_similar_chunks(
            query_embedding,
            embedded_chunks,
            top_k=EXPERIMENT_TOP_K,
        ),
    )


def _calculate_delta(
    left: HeadingContextVariantResult,
    right: HeadingContextVariantResult,
) -> HeadingContextMetricDelta:
    return HeadingContextMetricDelta(
        hit_at_1=(
            left.summary.hit_at_1_rate - right.summary.hit_at_1_rate
        ),
        hit_at_3=(
            left.summary.hit_at_3_rate - right.summary.hit_at_3_rate
        ),
        mrr=left.summary.mrr - right.summary.mrr,
    )


def _append_variant(
    lines: list[str],
    label: str,
    result: HeadingContextVariantResult,
) -> None:
    lines.extend(
        [
            label,
            f"total chunk count: {result.total_chunk_count}",
            f"Hit@1 rate: {result.summary.hit_at_1_rate:.4f}",
            f"Hit@3 rate: {result.summary.hit_at_3_rate:.4f}",
            f"MRR: {result.summary.mrr:.4f}",
            "",
        ]
    )


def _append_delta(
    lines: list[str],
    label: str,
    delta: HeadingContextMetricDelta,
) -> None:
    lines.extend(
        [
            label,
            f"Hit@1 delta: {delta.hit_at_1:+.4f}",
            f"Hit@3 delta: {delta.hit_at_3:+.4f}",
            f"MRR delta: {delta.mrr:+.4f}",
            "",
        ]
    )


def _validate_items(label: str, items: Sequence[object]) -> None:
    if not items:
        raise ValueError(f"{label} must not be empty")
