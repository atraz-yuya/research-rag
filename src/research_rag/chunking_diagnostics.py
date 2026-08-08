import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .chunker import split_pages_into_chunks
from .chunking_experiment import EXPERIMENT_EMBEDDING_MODEL
from .embedder import embed_chunks
from .evaluation import RetrievalEvaluationCase
from .experimental_chunker import split_pages_into_heading_aware_chunks
from .models import Chunk, SearchResult
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retrieval_diagnostics import build_retrieval_diagnostic
from .retriever import retrieve_similar_chunks


@dataclass(frozen=True)
class RankedChunkObservation:
    """Display-ready metadata for one ranked chunk."""

    rank: int
    page_number: int
    chunk_index: int
    score: float
    character_count: int
    text: str


@dataclass(frozen=True)
class RelevantPageChunkStructure:
    """All chunks generated for one relevant page."""

    page_number: int
    chunks: tuple[Chunk, ...]


@dataclass(frozen=True)
class ChunkCollectionStatistics:
    """Character-length statistics for one document chunk collection."""

    total_chunk_count: int
    minimum_chunk_length: int
    maximum_chunk_length: int
    mean_chunk_length: float
    median_chunk_length: float


@dataclass(frozen=True)
class ChunkingVariantDiagnostic:
    """Ranking and relevant-page structure for one chunking variant."""

    first_relevant_rank: int | None
    best_relevant_score: float | None
    top_results: tuple[RankedChunkObservation, ...]
    relevant_matches: tuple[RankedChunkObservation, ...]
    relevant_page_chunks: tuple[RelevantPageChunkStructure, ...]


@dataclass(frozen=True)
class ChunkingCaseDiagnostic:
    """Baseline and candidate diagnostics for one evaluation question."""

    question: str
    relevant_pages: tuple[int, ...]
    baseline: ChunkingVariantDiagnostic
    candidate: ChunkingVariantDiagnostic


@dataclass(frozen=True)
class ChunkingDiagnosticsReport:
    """Document statistics and per-case chunking diagnostics."""

    baseline_statistics: ChunkCollectionStatistics
    candidate_statistics: ChunkCollectionStatistics
    cases: tuple[ChunkingCaseDiagnostic, ...]


def calculate_chunk_statistics(
    chunks: Sequence[Chunk],
) -> ChunkCollectionStatistics:
    """Calculate document-level character-length statistics for chunks."""
    if not chunks:
        raise ValueError("chunks must not be empty")

    lengths = [len(chunk.text) for chunk in chunks]
    return ChunkCollectionStatistics(
        total_chunk_count=len(lengths),
        minimum_chunk_length=min(lengths),
        maximum_chunk_length=max(lengths),
        mean_chunk_length=statistics.fmean(lengths),
        median_chunk_length=float(statistics.median(lengths)),
    )


def build_chunking_variant_diagnostic(
    case: RetrievalEvaluationCase,
    full_ranking: Sequence[SearchResult],
    chunks: Sequence[Chunk],
    *,
    top_n: int = 5,
) -> ChunkingVariantDiagnostic:
    """Build ranking and relevant-page observations for one variant."""
    ranking = build_retrieval_diagnostic(
        case,
        full_ranking,
        top_n=top_n,
    )
    relevant_matches = tuple(
        _to_ranked_observation(result)
        for result in ranking.relevant_matches
    )

    return ChunkingVariantDiagnostic(
        first_relevant_rank=ranking.first_relevant_rank,
        best_relevant_score=(
            max(match.score for match in relevant_matches)
            if relevant_matches
            else None
        ),
        top_results=tuple(
            _to_ranked_observation(result) for result in ranking.top_results
        ),
        relevant_matches=relevant_matches,
        relevant_page_chunks=tuple(
            RelevantPageChunkStructure(
                page_number=page_number,
                chunks=tuple(
                    sorted(
                        (
                            chunk
                            for chunk in chunks
                            if chunk.page_number == page_number
                        ),
                        key=lambda chunk: chunk.chunk_index,
                    )
                ),
            )
            for page_number in case.relevant_pages
        ),
    )


def run_chunking_diagnostics(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str = EXPERIMENT_EMBEDDING_MODEL,
    top_n: int = 5,
    client: OllamaClient | None = None,
) -> ChunkingDiagnosticsReport:
    """Diagnose baseline and candidate chunking using full rankings."""
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

    case_diagnostics: list[ChunkingCaseDiagnostic] = []
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

        baseline_full_ranking = retrieve_similar_chunks(
            query_embedding,
            baseline_embedded_chunks,
            top_k=len(baseline_embedded_chunks),
        )
        candidate_full_ranking = retrieve_similar_chunks(
            query_embedding,
            candidate_embedded_chunks,
            top_k=len(candidate_embedded_chunks),
        )
        case_diagnostics.append(
            ChunkingCaseDiagnostic(
                question=case.question,
                relevant_pages=case.relevant_pages,
                baseline=build_chunking_variant_diagnostic(
                    case,
                    baseline_full_ranking,
                    baseline_chunks,
                    top_n=top_n,
                ),
                candidate=build_chunking_variant_diagnostic(
                    case,
                    candidate_full_ranking,
                    candidate_chunks,
                    top_n=top_n,
                ),
            )
        )

    return ChunkingDiagnosticsReport(
        baseline_statistics=calculate_chunk_statistics(baseline_chunks),
        candidate_statistics=calculate_chunk_statistics(candidate_chunks),
        cases=tuple(case_diagnostics),
    )


def format_chunking_diagnostics_report(
    report: ChunkingDiagnosticsReport,
) -> str:
    """Format statistics, rankings, and relevant-page chunk structures."""
    lines = ["Chunk statistics"]
    _append_statistics(lines, "Baseline", report.baseline_statistics)
    _append_statistics(lines, "Candidate", report.candidate_statistics)

    for case_index, case in enumerate(report.cases, start=1):
        lines.extend(
            [
                "",
                f"Diagnostic {case_index}",
                f"question: {case.question}",
                f"relevant_pages: {case.relevant_pages}",
            ]
        )
        _append_variant(lines, "Baseline", case.baseline)
        _append_variant(lines, "Candidate", case.candidate)

    return "\n".join(lines)


def _to_ranked_observation(result: SearchResult) -> RankedChunkObservation:
    return RankedChunkObservation(
        rank=result.rank,
        page_number=result.chunk.page_number,
        chunk_index=result.chunk.chunk_index,
        score=result.score,
        character_count=len(result.chunk.text),
        text=result.chunk.text,
    )


def _append_statistics(
    lines: list[str],
    label: str,
    chunk_statistics: ChunkCollectionStatistics,
) -> None:
    lines.extend(
        [
            f"{label}:",
            f"  total_chunk_count: {chunk_statistics.total_chunk_count}",
            f"  minimum_chunk_length: {chunk_statistics.minimum_chunk_length}",
            f"  maximum_chunk_length: {chunk_statistics.maximum_chunk_length}",
            f"  mean_chunk_length: {chunk_statistics.mean_chunk_length:.2f}",
            f"  median_chunk_length: {chunk_statistics.median_chunk_length:.2f}",
        ]
    )


def _append_variant(
    lines: list[str],
    label: str,
    diagnostic: ChunkingVariantDiagnostic,
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
    _append_ranked_chunks(lines, diagnostic.top_results, indent="    ")
    lines.append("  Relevant matches:")
    _append_ranked_chunks(lines, diagnostic.relevant_matches, indent="    ")
    lines.append("  Relevant page chunks:")
    _append_relevant_page_chunks(lines, diagnostic.relevant_page_chunks)


def _append_ranked_chunks(
    lines: list[str],
    chunks: Sequence[RankedChunkObservation],
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
                    f"page_number={chunk.page_number} "
                    f"chunk_index={chunk.chunk_index} "
                    f"score={chunk.score:.6f} "
                    f"character_count={chunk.character_count}"
                ),
                f"{indent}text: {chunk.text}",
            ]
        )


def _append_relevant_page_chunks(
    lines: list[str],
    pages: Sequence[RelevantPageChunkStructure],
) -> None:
    for page in pages:
        lines.append(f"    Page {page.page_number}: {len(page.chunks)} chunks")
        if not page.chunks:
            lines.append("      (none)")
            continue

        for chunk in page.chunks:
            lines.extend(
                [
                    (
                        f"      chunk_index={chunk.chunk_index} "
                        f"character_count={len(chunk.text)}"
                    ),
                    f"      text: {chunk.text}",
                ]
            )
