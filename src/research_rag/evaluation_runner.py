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
from .ollama_client import OllamaClient
from .pdf_reader import extract_page_texts
from .retriever import retrieve_similar_chunks


BASELINE_EVALUATION_CASES: tuple[RetrievalEvaluationCase, ...] = (
    RetrievalEvaluationCase(
        question="資金洗浄の3つの段階は何ですか？",
        relevant_pages=(2,),
    ),
    RetrievalEvaluationCase(
        question="What are the three stages of money laundering?",
        relevant_pages=(2,),
    ),
    RetrievalEvaluationCase(
        question="この文献レビューでは、論文をどの7つの基準で分類していますか？",
        relevant_pages=(3,),
    ),
    RetrievalEvaluationCase(
        question=(
            "文献レビューの83本の非レビュー論文について、"
            "最も多く利用されている学習方法は何ですか？"
        ),
        relevant_pages=(9,),
    ),
    RetrievalEvaluationCase(
        question="2018年以降に利用が増え始めたネットワーク分析手法は何ですか？",
        relevant_pages=(9,),
    ),
    RetrievalEvaluationCase(
        question="AUC-PRがAUC-ROCよりAMLの評価に適している理由は何ですか？",
        relevant_pages=(23,),
    ),
    RetrievalEvaluationCase(
        question=(
            "最も多くの研究で利用されているオープンソースデータセットは何で、"
            "何本の論文で使われていますか？"
        ),
        relevant_pages=(11, 12),
    ),
    RetrievalEvaluationCase(
        question="実験評価ではどの2つのデータセットを使用していますか？",
        relevant_pages=(20,),
    ),
    RetrievalEvaluationCase(
        question="Ellipticデータセットには何個のノードとエッジがありますか？",
        relevant_pages=(20,),
    ),
    RetrievalEvaluationCase(
        question="Ellipticの教師あり学習でAUC-PRが最も高かったモデルは何ですか？",
        relevant_pages=(24,),
    ),
    RetrievalEvaluationCase(
        question=(
            "EllipticとIBM-AMLで教師なし学習の結果が大きく異なった理由として、"
            "著者らは何を挙げていますか？"
        ),
        relevant_pages=(25, 26),
    ),
    RetrievalEvaluationCase(
        question=(
            "著者らがsynthetic dataを使ったAML評価について注意すべきだと"
            "結論づけている理由は何ですか？"
        ),
        relevant_pages=(26, 29),
    ),
)


@dataclass(frozen=True)
class RetrievalEvaluationReport:
    """Per-case retrieval results and their aggregate metrics."""

    results: tuple[RetrievalEvaluationResult, ...]
    summary: RetrievalEvaluationSummary


def run_retrieval_evaluation(
    pdf_path: Path,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    embedding_model: str,
    client: OllamaClient | None = None,
) -> RetrievalEvaluationReport:
    """Evaluate multiple questions while reusing one PDF embedding pass."""
    if not cases:
        raise ValueError("evaluation cases must not be empty")

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

    evaluation_results: list[RetrievalEvaluationResult] = []
    for case in cases:
        question_embeddings = ollama_client.embed_texts(
            [case.question],
            model=clean_model,
        )
        if len(question_embeddings) != 1:
            raise ValueError(
                "question embedding response must contain exactly one vector"
            )

        search_results = retrieve_similar_chunks(
            question_embeddings[0],
            embedded_chunks,
        )
        evaluation_results.append(evaluate_retrieval(case, search_results))

    summary = aggregate_retrieval_results(evaluation_results)
    return RetrievalEvaluationReport(tuple(evaluation_results), summary)


def format_retrieval_evaluation_report(
    report: RetrievalEvaluationReport,
) -> str:
    """Format per-case and aggregate retrieval metrics for manual review."""
    lines: list[str] = []

    for index, result in enumerate(report.results, start=1):
        lines.extend(
            [
                f"Case {index}",
                f"question: {result.question}",
                f"relevant_pages: {result.relevant_pages}",
                f"retrieved_pages: {result.retrieved_pages}",
                f"first_relevant_rank: {result.first_relevant_rank}",
                f"Hit@1: {result.hit_at_1}",
                f"Hit@3: {result.hit_at_3}",
                "",
            ]
        )

    lines.extend(
        [
            "Summary",
            f"Hit@1 rate: {report.summary.hit_at_1_rate:.4f}",
            f"Hit@3 rate: {report.summary.hit_at_3_rate:.4f}",
            f"MRR: {report.summary.mrr:.4f}",
        ]
    )
    return "\n".join(lines)
