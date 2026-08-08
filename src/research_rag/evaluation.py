import math
from collections.abc import Sequence
from dataclasses import dataclass

from .models import SearchResult


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    """A retrieval question and its acceptable 1-based PDF pages."""

    question: str
    relevant_pages: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if not self.relevant_pages:
            raise ValueError("relevant_pages must not be empty")
        if any(page_number <= 0 for page_number in self.relevant_pages):
            raise ValueError(
                "relevant_pages must contain 1-based page numbers"
            )


@dataclass(frozen=True)
class RetrievalEvaluationResult:
    """Per-question page-level retrieval metrics."""

    question: str
    relevant_pages: tuple[int, ...]
    retrieved_pages: tuple[int, ...]
    hit_at_1: bool
    hit_at_3: bool
    first_relevant_rank: int | None


@dataclass(frozen=True)
class RetrievalEvaluationSummary:
    """Aggregate retrieval metrics for multiple evaluation cases."""

    case_count: int
    hit_at_1_rate: float
    hit_at_3_rate: float
    mrr: float


def evaluate_retrieval(
    case: RetrievalEvaluationCase,
    search_results: Sequence[SearchResult],
) -> RetrievalEvaluationResult:
    """Compare ranked search results with the case's relevant PDF pages."""
    ordered_results = sorted(search_results, key=lambda result: result.rank)
    relevant_pages = set(case.relevant_pages)
    first_relevant_rank = next(
        (
            result.rank
            for result in ordered_results
            if result.chunk.page_number in relevant_pages
        ),
        None,
    )

    return RetrievalEvaluationResult(
        question=case.question,
        relevant_pages=case.relevant_pages,
        retrieved_pages=tuple(
            result.chunk.page_number for result in ordered_results
        ),
        hit_at_1=first_relevant_rank == 1,
        hit_at_3=(
            first_relevant_rank is not None and first_relevant_rank <= 3
        ),
        first_relevant_rank=first_relevant_rank,
    )


def aggregate_retrieval_results(
    results: Sequence[RetrievalEvaluationResult],
) -> RetrievalEvaluationSummary:
    """Calculate Hit@1, Hit@3, and MRR means across evaluation results."""
    if not results:
        raise ValueError("evaluation results must not be empty")

    case_count = len(results)
    return RetrievalEvaluationSummary(
        case_count=case_count,
        hit_at_1_rate=(
            math.fsum(1.0 for result in results if result.hit_at_1)
            / case_count
        ),
        hit_at_3_rate=(
            math.fsum(1.0 for result in results if result.hit_at_3)
            / case_count
        ),
        mrr=(
            math.fsum(
                0.0
                if result.first_relevant_rank is None
                else 1.0 / result.first_relevant_rank
                for result in results
            )
            / case_count
        ),
    )
