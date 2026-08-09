from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .chunker import split_pages_into_chunks
from .embedder import embed_chunks
from .evaluation import RetrievalEvaluationCase
from .models import SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


@dataclass(frozen=True)
class RetrievalQueryVariant:
    """One query wording used in a retrieval sensitivity diagnosis."""

    label: str
    query: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("query variant label must not be empty")
        if not self.query.strip():
            raise ValueError("query variant query must not be empty")


@dataclass(frozen=True)
class RetrievalQueryVariantCase:
    """An evaluation case and the query wordings to compare for it."""

    evaluation_case: RetrievalEvaluationCase
    variants: tuple[RetrievalQueryVariant, ...]


@dataclass(frozen=True)
class RankedChunkObservation:
    """Human-reviewable fields from one ranked retrieval result."""

    rank: int
    document_name: str
    page_number: int
    chunk_index: int
    score: float
    character_count: int
    text: str


@dataclass(frozen=True)
class QueryVariantDiagnostic:
    """Full-ranking observations for one query variant."""

    variant_label: str
    query: str
    relevant_pages: tuple[int, ...]
    first_relevant_rank: int | None
    best_relevant_score: float | None
    hit_at_3: bool
    top_n: int
    top_results: tuple[RankedChunkObservation, ...]
    relevant_chunks: tuple[RankedChunkObservation, ...]


@dataclass(frozen=True)
class QueryVariantComparison:
    """Retrieval changes from a reference wording to another wording."""

    reference_label: str
    variant_label: str
    reference_first_relevant_rank: int | None
    variant_first_relevant_rank: int | None
    reference_best_relevant_score: float | None
    variant_best_relevant_score: float | None
    best_relevant_score_delta: float | None
    reference_hit_at_3: bool
    variant_hit_at_3: bool
    top_n: int
    top_n_page_overlap: tuple[int, ...]
    removed_top_n_pages: tuple[int, ...]
    added_top_n_pages: tuple[int, ...]


@dataclass(frozen=True)
class QueryVariantCaseDiagnostic:
    """All query-variant observations and comparisons for one case."""

    question: str
    relevant_pages: tuple[int, ...]
    variants: tuple[QueryVariantDiagnostic, ...]
    comparisons: tuple[QueryVariantComparison, ...]


@dataclass(frozen=True)
class RetrievalQueryVariantDiagnosticsReport:
    """Query-language and scope diagnostics for multiple cases."""

    cases: tuple[QueryVariantCaseDiagnostic, ...]


def build_query_variant_diagnostic(
    case: RetrievalEvaluationCase,
    variant: RetrievalQueryVariant,
    full_ranking: Sequence[SearchResult],
    *,
    top_n: int = 5,
) -> QueryVariantDiagnostic:
    """Build one variant's observations from an existing full ranking."""
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")

    ordered_results = tuple(sorted(full_ranking, key=lambda result: result.rank))
    relevant_pages = set(case.relevant_pages)
    relevant_results = tuple(
        result
        for result in ordered_results
        if result.chunk.page_number in relevant_pages
    )

    return QueryVariantDiagnostic(
        variant_label=variant.label,
        query=variant.query,
        relevant_pages=case.relevant_pages,
        first_relevant_rank=(
            relevant_results[0].rank if relevant_results else None
        ),
        best_relevant_score=(
            max(result.score for result in relevant_results)
            if relevant_results
            else None
        ),
        hit_at_3=(
            bool(relevant_results) and relevant_results[0].rank <= 3
        ),
        top_n=top_n,
        top_results=tuple(
            _to_observation(result) for result in ordered_results[:top_n]
        ),
        relevant_chunks=tuple(
            _to_observation(result) for result in relevant_results
        ),
    )


def compare_query_variant_diagnostics(
    reference: QueryVariantDiagnostic,
    variant: QueryVariantDiagnostic,
) -> QueryVariantComparison:
    """Compare ranking outcomes and top-result pages across two variants."""
    if reference.relevant_pages != variant.relevant_pages:
        raise ValueError("query variants must use the same relevant_pages")
    if reference.top_n != variant.top_n:
        raise ValueError("query variants must use the same top_n")

    reference_pages = _unique_pages(reference.top_results)
    variant_pages = _unique_pages(variant.top_results)
    variant_page_set = set(variant_pages)
    reference_page_set = set(reference_pages)

    score_delta: float | None = None
    if (
        reference.best_relevant_score is not None
        and variant.best_relevant_score is not None
    ):
        score_delta = (
            variant.best_relevant_score - reference.best_relevant_score
        )

    return QueryVariantComparison(
        reference_label=reference.variant_label,
        variant_label=variant.variant_label,
        reference_first_relevant_rank=reference.first_relevant_rank,
        variant_first_relevant_rank=variant.first_relevant_rank,
        reference_best_relevant_score=reference.best_relevant_score,
        variant_best_relevant_score=variant.best_relevant_score,
        best_relevant_score_delta=score_delta,
        reference_hit_at_3=reference.hit_at_3,
        variant_hit_at_3=variant.hit_at_3,
        top_n=reference.top_n,
        top_n_page_overlap=tuple(
            page for page in reference_pages if page in variant_page_set
        ),
        removed_top_n_pages=tuple(
            page for page in reference_pages if page not in variant_page_set
        ),
        added_top_n_pages=tuple(
            page for page in variant_pages if page not in reference_page_set
        ),
    )


def run_query_variant_diagnostics(
    pdf_path: Path,
    cases: Sequence[RetrievalQueryVariantCase],
    *,
    embedding_model: str,
    top_n: int = 5,
    client: OllamaClient | None = None,
) -> RetrievalQueryVariantDiagnosticsReport:
    """Run variants while reusing one production-chunker embedding pass."""
    clean_model = _validate_runner_inputs(cases, embedding_model, top_n)

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    chunks = split_pages_into_chunks(pages)
    if not chunks:
        raise ValueError("no searchable chunks were generated from PDF")

    embedded_chunks = embed_chunks(chunks, clean_model, ollama_client)
    if not embedded_chunks:
        raise ValueError("no chunk embeddings were generated")

    case_diagnostics: list[QueryVariantCaseDiagnostic] = []
    for variant_case in cases:
        diagnostics: list[QueryVariantDiagnostic] = []
        for variant in variant_case.variants:
            question_embeddings = ollama_client.embed_texts(
                [variant.query],
                model=clean_model,
            )
            if len(question_embeddings) != 1:
                raise ValueError(
                    "query embedding response must contain exactly one vector"
                )

            full_ranking = retrieve_similar_chunks(
                question_embeddings[0],
                embedded_chunks,
                top_k=len(embedded_chunks),
            )
            diagnostics.append(
                build_query_variant_diagnostic(
                    variant_case.evaluation_case,
                    variant,
                    full_ranking,
                    top_n=top_n,
                )
            )

        reference = diagnostics[0]
        case_diagnostics.append(
            QueryVariantCaseDiagnostic(
                question=variant_case.evaluation_case.question,
                relevant_pages=variant_case.evaluation_case.relevant_pages,
                variants=tuple(diagnostics),
                comparisons=tuple(
                    compare_query_variant_diagnostics(reference, diagnostic)
                    for diagnostic in diagnostics[1:]
                ),
            )
        )

    return RetrievalQueryVariantDiagnosticsReport(tuple(case_diagnostics))


def format_query_variant_diagnostics_report(
    report: RetrievalQueryVariantDiagnosticsReport,
) -> str:
    """Format query-variant diagnostics for human inspection."""
    lines: list[str] = []

    for case_index, case in enumerate(report.cases, start=1):
        lines.extend(
            [
                f"Diagnostic case {case_index}",
                f"evaluation_question: {case.question}",
                f"relevant_pages: {case.relevant_pages}",
            ]
        )
        for diagnostic in case.variants:
            lines.extend(
                [
                    f"Variant: {diagnostic.variant_label}",
                    f"query: {diagnostic.query}",
                    (
                        "first_relevant_rank: "
                        f"{diagnostic.first_relevant_rank}"
                    ),
                    (
                        "best_relevant_score: "
                        f"{_format_score(diagnostic.best_relevant_score)}"
                    ),
                    f"Hit@3: {diagnostic.hit_at_3}",
                    f"Top {diagnostic.top_n} results:",
                ]
            )
            _append_observations(lines, diagnostic.top_results)
            lines.append("Relevant page chunks:")
            _append_observations(lines, diagnostic.relevant_chunks)

        if case.comparisons:
            lines.append("Variant comparisons:")
        for comparison in case.comparisons:
            lines.extend(
                [
                    (
                        f"  {comparison.reference_label} -> "
                        f"{comparison.variant_label}"
                    ),
                    (
                        "  first relevant rank: "
                        f"{comparison.reference_first_relevant_rank} -> "
                        f"{comparison.variant_first_relevant_rank}"
                    ),
                    (
                        "  best relevant score: "
                        f"{_format_score(comparison.reference_best_relevant_score)}"
                        " -> "
                        f"{_format_score(comparison.variant_best_relevant_score)}"
                        " (delta="
                        f"{_format_signed_score(comparison.best_relevant_score_delta)})"
                    ),
                    (
                        "  Hit@3: "
                        f"{comparison.reference_hit_at_3} -> "
                        f"{comparison.variant_hit_at_3}"
                    ),
                    (
                        f"  Top {comparison.top_n} page overlap: "
                        f"{comparison.top_n_page_overlap}"
                    ),
                    (
                        "  removed competitor pages: "
                        f"{comparison.removed_top_n_pages}"
                    ),
                    (
                        "  added competitor pages: "
                        f"{comparison.added_top_n_pages}"
                    ),
                ]
            )
        lines.append("")

    return "\n".join(lines).rstrip()


def _validate_runner_inputs(
    cases: Sequence[RetrievalQueryVariantCase],
    embedding_model: str,
    top_n: int,
) -> str:
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")
    if not cases:
        raise ValueError("diagnostic cases must not be empty")

    for case in cases:
        if not case.variants:
            raise ValueError("query variants must not be empty")
        labels = tuple(variant.label for variant in case.variants)
        if len(set(labels)) != len(labels):
            raise ValueError("query variant labels must be unique within a case")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")
    return clean_model


def _to_observation(result: SearchResult) -> RankedChunkObservation:
    chunk = result.chunk
    return RankedChunkObservation(
        rank=result.rank,
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        score=result.score,
        character_count=len(chunk.text),
        text=chunk.text,
    )


def _unique_pages(
    observations: Sequence[RankedChunkObservation],
) -> tuple[int, ...]:
    return tuple(dict.fromkeys(item.page_number for item in observations))


def _append_observations(
    lines: list[str],
    observations: Sequence[RankedChunkObservation],
) -> None:
    if not observations:
        lines.append("  (none)")
        return

    for item in observations:
        lines.extend(
            [
                (
                    f"  rank={item.rank} "
                    f"document_name={item.document_name} "
                    f"page_number={item.page_number} "
                    f"chunk_index={item.chunk_index} "
                    f"score={item.score:.6f} "
                    f"character_count={item.character_count}"
                ),
                f"  text: {item.text}",
            ]
        )


def _format_score(score: float | None) -> str:
    return "None" if score is None else f"{score:.6f}"


def _format_signed_score(score: float | None) -> str:
    return "None" if score is None else f"{score:+.6f}"
