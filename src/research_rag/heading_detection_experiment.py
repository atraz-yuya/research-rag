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
from .experimental_chunker import split_pages_into_heading_aware_chunks
from .experimental_chunker_v2 import (
    split_pages_into_strict_heading_aware_chunks,
)
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


@dataclass(frozen=True)
class HeadingVariantResult:
    """Chunk count and retrieval metrics for one chunking variant."""

    total_chunk_count: int
    summary: RetrievalEvaluationSummary


@dataclass(frozen=True)
class HeadingMetricDelta:
    """Retrieval metric differences between two variants."""

    hit_at_1: float
    hit_at_3: float
    mrr: float


@dataclass(frozen=True)
class HeadingDetectionCaseComparison:
    """Per-case retrieval output for baseline, Candidate v1, and v2."""

    question: str
    relevant_pages: tuple[int, ...]
    baseline_retrieved_pages: tuple[int, ...]
    candidate_v1_retrieved_pages: tuple[int, ...]
    candidate_v2_retrieved_pages: tuple[int, ...]
    baseline_first_relevant_rank: int | None
    candidate_v1_first_relevant_rank: int | None
    candidate_v2_first_relevant_rank: int | None


@dataclass(frozen=True)
class HeadingDetectionExperimentReport:
    """Three-way heading detection comparison results."""

    comparisons: tuple[HeadingDetectionCaseComparison, ...]
    baseline: HeadingVariantResult
    candidate_v1: HeadingVariantResult
    candidate_v2: HeadingVariantResult

    @property
    def candidate_v1_minus_baseline(self) -> HeadingMetricDelta:
        return _calculate_delta(self.candidate_v1, self.baseline)

    @property
    def candidate_v2_minus_baseline(self) -> HeadingMetricDelta:
        return _calculate_delta(self.candidate_v2, self.baseline)

    @property
    def candidate_v2_minus_candidate_v1(self) -> HeadingMetricDelta:
        return _calculate_delta(self.candidate_v2, self.candidate_v1)


def run_heading_detection_experiment(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str = EXPERIMENT_EMBEDDING_MODEL,
    client: OllamaClient | None = None,
) -> HeadingDetectionExperimentReport:
    """Compare baseline and two heading detectors under equal conditions."""
    if not cases:
        raise ValueError("experiment cases must not be empty")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)

    baseline_chunks = split_pages_into_chunks(pages)
    candidate_v1_chunks = split_pages_into_heading_aware_chunks(pages)
    candidate_v2_chunks = split_pages_into_strict_heading_aware_chunks(pages)
    _validate_chunks("baseline", baseline_chunks)
    _validate_chunks("Candidate v1", candidate_v1_chunks)
    _validate_chunks("Candidate v2", candidate_v2_chunks)

    baseline_embedded = embed_chunks(
        baseline_chunks,
        clean_model,
        ollama_client,
    )
    candidate_v1_embedded = embed_chunks(
        candidate_v1_chunks,
        clean_model,
        ollama_client,
    )
    candidate_v2_embedded = embed_chunks(
        candidate_v2_chunks,
        clean_model,
        ollama_client,
    )
    _validate_embeddings("baseline", baseline_embedded)
    _validate_embeddings("Candidate v1", candidate_v1_embedded)
    _validate_embeddings("Candidate v2", candidate_v2_embedded)

    baseline_results: list[RetrievalEvaluationResult] = []
    candidate_v1_results: list[RetrievalEvaluationResult] = []
    candidate_v2_results: list[RetrievalEvaluationResult] = []
    comparisons: list[HeadingDetectionCaseComparison] = []

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

        baseline_result = evaluate_retrieval(
            case,
            retrieve_similar_chunks(
                query_embedding,
                baseline_embedded,
                top_k=EXPERIMENT_TOP_K,
            ),
        )
        candidate_v1_result = evaluate_retrieval(
            case,
            retrieve_similar_chunks(
                query_embedding,
                candidate_v1_embedded,
                top_k=EXPERIMENT_TOP_K,
            ),
        )
        candidate_v2_result = evaluate_retrieval(
            case,
            retrieve_similar_chunks(
                query_embedding,
                candidate_v2_embedded,
                top_k=EXPERIMENT_TOP_K,
            ),
        )

        baseline_results.append(baseline_result)
        candidate_v1_results.append(candidate_v1_result)
        candidate_v2_results.append(candidate_v2_result)
        comparisons.append(
            _build_case_comparison(
                case,
                baseline_result,
                candidate_v1_result,
                candidate_v2_result,
            )
        )

    return HeadingDetectionExperimentReport(
        comparisons=tuple(comparisons),
        baseline=HeadingVariantResult(
            len(baseline_chunks),
            aggregate_retrieval_results(baseline_results),
        ),
        candidate_v1=HeadingVariantResult(
            len(candidate_v1_chunks),
            aggregate_retrieval_results(candidate_v1_results),
        ),
        candidate_v2=HeadingVariantResult(
            len(candidate_v2_chunks),
            aggregate_retrieval_results(candidate_v2_results),
        ),
    )


def format_heading_detection_experiment_report(
    report: HeadingDetectionExperimentReport,
) -> str:
    """Format variant metrics, three deltas, and per-case results."""
    lines: list[str] = []
    _append_variant(lines, "Baseline", report.baseline)
    _append_variant(lines, "Candidate v1", report.candidate_v1)
    _append_variant(lines, "Candidate v2", report.candidate_v2)
    _append_delta(
        lines,
        "Candidate v1 - Baseline",
        report.candidate_v1_minus_baseline,
    )
    _append_delta(
        lines,
        "Candidate v2 - Baseline",
        report.candidate_v2_minus_baseline,
    )
    _append_delta(
        lines,
        "Candidate v2 - Candidate v1",
        report.candidate_v2_minus_candidate_v1,
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
                    "Candidate v1 retrieved_pages: "
                    f"{comparison.candidate_v1_retrieved_pages}"
                ),
                (
                    "Candidate v2 retrieved_pages: "
                    f"{comparison.candidate_v2_retrieved_pages}"
                ),
                (
                    "baseline first_relevant_rank: "
                    f"{comparison.baseline_first_relevant_rank}"
                ),
                (
                    "Candidate v1 first_relevant_rank: "
                    f"{comparison.candidate_v1_first_relevant_rank}"
                ),
                (
                    "Candidate v2 first_relevant_rank: "
                    f"{comparison.candidate_v2_first_relevant_rank}"
                ),
                "",
            ]
        )

    return "\n".join(lines).rstrip()


def _calculate_delta(
    left: HeadingVariantResult,
    right: HeadingVariantResult,
) -> HeadingMetricDelta:
    return HeadingMetricDelta(
        hit_at_1=(
            left.summary.hit_at_1_rate - right.summary.hit_at_1_rate
        ),
        hit_at_3=(
            left.summary.hit_at_3_rate - right.summary.hit_at_3_rate
        ),
        mrr=left.summary.mrr - right.summary.mrr,
    )


def _build_case_comparison(
    case: RetrievalEvaluationCase,
    baseline: RetrievalEvaluationResult,
    candidate_v1: RetrievalEvaluationResult,
    candidate_v2: RetrievalEvaluationResult,
) -> HeadingDetectionCaseComparison:
    return HeadingDetectionCaseComparison(
        question=case.question,
        relevant_pages=case.relevant_pages,
        baseline_retrieved_pages=baseline.retrieved_pages,
        candidate_v1_retrieved_pages=candidate_v1.retrieved_pages,
        candidate_v2_retrieved_pages=candidate_v2.retrieved_pages,
        baseline_first_relevant_rank=baseline.first_relevant_rank,
        candidate_v1_first_relevant_rank=candidate_v1.first_relevant_rank,
        candidate_v2_first_relevant_rank=candidate_v2.first_relevant_rank,
    )


def _append_variant(
    lines: list[str],
    label: str,
    result: HeadingVariantResult,
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
    delta: HeadingMetricDelta,
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


def _validate_chunks(label: str, chunks: Sequence[object]) -> None:
    if not chunks:
        raise ValueError(f"{label} chunker generated no searchable chunks")


def _validate_embeddings(label: str, embeddings: Sequence[object]) -> None:
    if not embeddings:
        raise ValueError(f"no {label} chunk embeddings were generated")
