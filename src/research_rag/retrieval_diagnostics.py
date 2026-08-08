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
class RetrievalDiagnostic:
    """Full-ranking observations for one retrieval evaluation case."""

    question: str
    relevant_pages: tuple[int, ...]
    first_relevant_rank: int | None
    top_results: tuple[SearchResult, ...]
    relevant_matches: tuple[SearchResult, ...]


@dataclass(frozen=True)
class RetrievalDiagnosticsReport:
    """Retrieval diagnostics for multiple evaluation cases."""

    diagnostics: tuple[RetrievalDiagnostic, ...]


def build_retrieval_diagnostic(
    case: RetrievalEvaluationCase,
    full_ranking: Sequence[SearchResult],
    *,
    top_n: int = 10,
) -> RetrievalDiagnostic:
    """Extract top results and all relevant-page matches from a ranking."""
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")

    ordered_results = tuple(sorted(full_ranking, key=lambda result: result.rank))
    relevant_pages = set(case.relevant_pages)
    relevant_matches = tuple(
        result
        for result in ordered_results
        if result.chunk.page_number in relevant_pages
    )

    return RetrievalDiagnostic(
        question=case.question,
        relevant_pages=case.relevant_pages,
        first_relevant_rank=(
            relevant_matches[0].rank if relevant_matches else None
        ),
        top_results=ordered_results[:top_n],
        relevant_matches=relevant_matches,
    )


def run_retrieval_diagnostics(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str,
    top_n: int = 10,
    client: OllamaClient | None = None,
) -> RetrievalDiagnosticsReport:
    """Diagnose cases while reusing one PDF chunk-embedding pass."""
    if top_n <= 0:
        raise ValueError("top_n must be greater than 0")
    if not cases:
        raise ValueError("diagnostic cases must not be empty")

    clean_model = embedding_model.strip()
    if not clean_model:
        raise ValueError("embedding_model must not be empty")

    ollama_client = client if client is not None else OllamaClient()
    pages = extract_page_texts(pdf_path)
    chunks = split_pages_into_chunks(pages)
    if not chunks:
        raise ValueError("no searchable chunks were generated from PDF")

    embedded_chunks = embed_chunks(chunks, clean_model, ollama_client)
    if not embedded_chunks:
        raise ValueError("no chunk embeddings were generated")

    diagnostics: list[RetrievalDiagnostic] = []
    for case in cases:
        question_embeddings = ollama_client.embed_texts(
            [case.question],
            model=clean_model,
        )
        if len(question_embeddings) != 1:
            raise ValueError(
                "question embedding response must contain exactly one vector"
            )

        full_ranking = retrieve_similar_chunks(
            question_embeddings[0],
            embedded_chunks,
            top_k=len(embedded_chunks),
        )
        diagnostics.append(
            build_retrieval_diagnostic(case, full_ranking, top_n=top_n)
        )

    return RetrievalDiagnosticsReport(tuple(diagnostics))


def format_retrieval_diagnostics_report(
    report: RetrievalDiagnosticsReport,
) -> str:
    """Format full-ranking observations for human review."""
    lines: list[str] = []

    for case_index, diagnostic in enumerate(report.diagnostics, start=1):
        lines.extend(
            [
                f"Diagnostic case {case_index}",
                f"question: {diagnostic.question}",
                f"relevant_pages: {diagnostic.relevant_pages}",
                f"first_relevant_rank: {diagnostic.first_relevant_rank}",
                "Top results:",
            ]
        )
        _append_search_results(lines, diagnostic.top_results)
        lines.append("Relevant matches:")
        _append_search_results(lines, diagnostic.relevant_matches)
        lines.append("")

    return "\n".join(lines).rstrip()


def _append_search_results(
    lines: list[str],
    results: Sequence[SearchResult],
) -> None:
    if not results:
        lines.append("  (none)")
        return

    for result in results:
        lines.extend(
            [
                (
                    f"  rank={result.rank} "
                    f"document_name={result.chunk.document_name} "
                    f"page_number={result.chunk.page_number} "
                    f"chunk_index={result.chunk.chunk_index} "
                    f"score={result.score:.6f}"
                ),
                f"  text: {result.chunk.text}",
            ]
        )
