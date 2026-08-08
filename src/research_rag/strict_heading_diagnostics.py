from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .chunker import split_pages_into_chunks
from .chunking_experiment import EXPERIMENT_EMBEDDING_MODEL
from .embedder import embed_chunks
from .evaluation import RetrievalEvaluationCase
from .experimental_chunker_v2 import (
    _find_heading_starts,
    split_pages_into_strict_heading_aware_chunks,
)
from .models import Chunk, SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retrieval_diagnostics import build_retrieval_diagnostic
from .retriever import retrieve_similar_chunks


@dataclass(frozen=True)
class StrictHeadingChunkObservation:
    """Ranking and boundary metadata for one diagnostic chunk."""

    rank: int
    document_name: str
    page_number: int
    chunk_index: int
    score: float
    character_count: int
    text: str
    starts_with_heading: bool


@dataclass(frozen=True)
class RelevantPageChunkComparison:
    """All ranked chunks generated for one relevant page."""

    page_number: int
    chunks: tuple[StrictHeadingChunkObservation, ...]


@dataclass(frozen=True)
class StrictHeadingVariantDiagnostic:
    """Full-ranking observations for one chunking variant."""

    first_relevant_rank: int | None
    best_relevant_score: float | None
    top_results: tuple[StrictHeadingChunkObservation, ...]
    relevant_page_chunks: tuple[RelevantPageChunkComparison, ...]


@dataclass(frozen=True)
class StrictHeadingCaseDiagnostic:
    """Baseline and Candidate v2 observations for one question."""

    question: str
    relevant_pages: tuple[int, ...]
    baseline: StrictHeadingVariantDiagnostic
    candidate_v2: StrictHeadingVariantDiagnostic


@dataclass(frozen=True)
class StrictHeadingDiagnosticsReport:
    """Strict-heading regression diagnostics for multiple questions."""

    cases: tuple[StrictHeadingCaseDiagnostic, ...]


def starts_with_strict_heading(text: str) -> bool:
    """Return whether Candidate v2 recognizes a heading at text offset zero."""
    heading_starts = _find_heading_starts(text)
    return bool(heading_starts) and heading_starts[0] == 0


def build_strict_heading_variant_diagnostic(
    case: RetrievalEvaluationCase,
    full_ranking: Sequence[SearchResult],
    chunks: Sequence[Chunk],
    *,
    top_n: int = 5,
) -> StrictHeadingVariantDiagnostic:
    """Combine a full ranking with every chunk on each relevant page."""
    ranking = build_retrieval_diagnostic(case, full_ranking, top_n=top_n)
    ranked_by_chunk = {
        _chunk_key(result.chunk): result for result in full_ranking
    }

    relevant_page_chunks: list[RelevantPageChunkComparison] = []
    for page_number in case.relevant_pages:
        page_chunks = sorted(
            (
                chunk
                for chunk in chunks
                if chunk.page_number == page_number
            ),
            key=lambda chunk: chunk.chunk_index,
        )
        observations: list[StrictHeadingChunkObservation] = []
        for chunk in page_chunks:
            result = ranked_by_chunk.get(_chunk_key(chunk))
            if result is None:
                raise ValueError(
                    "full ranking does not contain every relevant-page chunk"
                )
            observations.append(_to_chunk_observation(result))
        relevant_page_chunks.append(
            RelevantPageChunkComparison(
                page_number=page_number,
                chunks=tuple(observations),
            )
        )

    relevant_pages = set(case.relevant_pages)
    relevant_results = tuple(
        result
        for result in full_ranking
        if result.chunk.page_number in relevant_pages
    )
    return StrictHeadingVariantDiagnostic(
        first_relevant_rank=ranking.first_relevant_rank,
        best_relevant_score=(
            max(result.score for result in relevant_results)
            if relevant_results
            else None
        ),
        top_results=tuple(
            _to_chunk_observation(result) for result in ranking.top_results
        ),
        relevant_page_chunks=tuple(relevant_page_chunks),
    )


def run_strict_heading_diagnostics(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str = EXPERIMENT_EMBEDDING_MODEL,
    top_n: int = 5,
    client: OllamaClient | None = None,
) -> StrictHeadingDiagnosticsReport:
    """Compare Baseline and Candidate v2 with one shared query per case."""
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")
    if not cases:
        raise ValueError("diagnostic cases must not be empty")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    baseline_chunks = split_pages_into_chunks(pages)
    if not baseline_chunks:
        raise ValueError("baseline chunker generated no searchable chunks")
    candidate_v2_chunks = split_pages_into_strict_heading_aware_chunks(pages)
    if not candidate_v2_chunks:
        raise ValueError("Candidate v2 generated no searchable chunks")

    baseline_embedded = embed_chunks(
        baseline_chunks,
        clean_model,
        ollama_client,
    )
    if not baseline_embedded:
        raise ValueError("no baseline chunk embeddings were generated")
    candidate_v2_embedded = embed_chunks(
        candidate_v2_chunks,
        clean_model,
        ollama_client,
    )
    if not candidate_v2_embedded:
        raise ValueError("no Candidate v2 chunk embeddings were generated")

    diagnostics: list[StrictHeadingCaseDiagnostic] = []
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

        baseline_ranking = retrieve_similar_chunks(
            query_embedding,
            baseline_embedded,
            top_k=len(baseline_embedded),
        )
        candidate_v2_ranking = retrieve_similar_chunks(
            query_embedding,
            candidate_v2_embedded,
            top_k=len(candidate_v2_embedded),
        )
        diagnostics.append(
            StrictHeadingCaseDiagnostic(
                question=case.question,
                relevant_pages=case.relevant_pages,
                baseline=build_strict_heading_variant_diagnostic(
                    case,
                    baseline_ranking,
                    baseline_chunks,
                    top_n=top_n,
                ),
                candidate_v2=build_strict_heading_variant_diagnostic(
                    case,
                    candidate_v2_ranking,
                    candidate_v2_chunks,
                    top_n=top_n,
                ),
            )
        )

    return StrictHeadingDiagnosticsReport(cases=tuple(diagnostics))


def format_strict_heading_diagnostics_report(
    report: StrictHeadingDiagnosticsReport,
) -> str:
    """Format rankings and relevant-page boundaries for human comparison."""
    lines: list[str] = []
    for case_index, case in enumerate(report.cases, start=1):
        lines.extend(
            [
                f"Diagnostic {case_index}",
                f"question: {case.question}",
                f"relevant_pages: {case.relevant_pages}",
            ]
        )
        _append_variant(lines, "Baseline", case.baseline)
        _append_variant(lines, "Candidate v2", case.candidate_v2)
        lines.append("")

    return "\n".join(lines).rstrip()


def _chunk_key(chunk: Chunk) -> tuple[str, int, int, str]:
    return (
        chunk.document_name,
        chunk.page_number,
        chunk.chunk_index,
        chunk.text,
    )


def _to_chunk_observation(
    result: SearchResult,
) -> StrictHeadingChunkObservation:
    chunk = result.chunk
    return StrictHeadingChunkObservation(
        rank=result.rank,
        document_name=chunk.document_name,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        score=result.score,
        character_count=len(chunk.text),
        text=chunk.text,
        starts_with_heading=starts_with_strict_heading(chunk.text),
    )


def _append_variant(
    lines: list[str],
    label: str,
    diagnostic: StrictHeadingVariantDiagnostic,
) -> None:
    best_score = (
        "None"
        if diagnostic.best_relevant_score is None
        else f"{diagnostic.best_relevant_score:.6f}"
    )
    lines.extend(
        [
            f"{label}:",
            f"  first_relevant_rank: {diagnostic.first_relevant_rank}",
            f"  best_relevant_score: {best_score}",
            "  Top results:",
        ]
    )
    _append_observations(lines, diagnostic.top_results, indent="    ")
    lines.append("  Relevant page chunks:")
    for page in diagnostic.relevant_page_chunks:
        lines.append(f"    Page {page.page_number}: {len(page.chunks)} chunks")
        _append_observations(lines, page.chunks, indent="      ")


def _append_observations(
    lines: list[str],
    chunks: Sequence[StrictHeadingChunkObservation],
    *,
    indent: str,
) -> None:
    if not chunks:
        lines.append(f"{indent}(none)")
        return

    for chunk in chunks:
        lines.extend(
            [
                (
                    f"{indent}rank={chunk.rank} "
                    f"document_name={chunk.document_name} "
                    f"page_number={chunk.page_number} "
                    f"chunk_index={chunk.chunk_index} "
                    f"score={chunk.score:.6f} "
                    f"character_count={chunk.character_count} "
                    f"starts_with_heading={chunk.starts_with_heading}"
                ),
                f"{indent}text: {chunk.text}",
            ]
        )
