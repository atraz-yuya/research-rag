import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .models import RagAnswer
from .ollama_client import DEFAULT_OLLAMA_BASE_URL, OllamaClient, OllamaError
from .rag_service import answer_question_from_pdf


DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
DEFAULT_GENERATION_MODEL = "qwen3:4b-instruct"
DEFAULT_TOP_K = 3


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="単一PDFの内容を検索し、Ollamaで質問へ回答します。"
    )
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="質問対象となるPDFファイルのパス",
    )
    parser.add_argument("question", help="PDFの内容についての質問")
    parser.add_argument(
        "--embedding-model",
        default=DEFAULT_EMBEDDING_MODEL,
        help=f"Ollamaの埋め込みモデル（既定: {DEFAULT_EMBEDDING_MODEL}）",
    )
    parser.add_argument(
        "--generation-model",
        default=DEFAULT_GENERATION_MODEL,
        help=f"Ollamaの生成モデル（既定: {DEFAULT_GENERATION_MODEL}）",
    )
    parser.add_argument(
        "--top-k",
        type=_positive_integer,
        default=DEFAULT_TOP_K,
        help=f"回答生成に使用する検索結果数（既定: {DEFAULT_TOP_K}）",
    )
    parser.add_argument(
        "--ollama-base-url",
        default=DEFAULT_OLLAMA_BASE_URL,
        help=f"Ollama APIの接続先（既定: {DEFAULT_OLLAMA_BASE_URL}）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return its process exit code."""
    args = build_parser().parse_args(argv)

    try:
        client = OllamaClient(base_url=args.ollama_base_url)
        answer = answer_question_from_pdf(
            args.pdf_path,
            args.question,
            embedding_model=args.embedding_model,
            generation_model=args.generation_model,
            top_k=args.top_k,
            client=client,
        )
    except (OSError, ValueError, OllamaError) as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1

    print(_format_answer(answer))
    return 0


def _positive_integer(value: str) -> int:
    parsed_value = int(value)
    if parsed_value <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed_value


def _format_answer(answer: RagAnswer) -> str:
    lines = ["回答:", answer.text, "", "参照:"]

    for source in answer.sources:
        lines.extend(
            [
                f"[{source.rank}] {source.chunk.document_name} "
                f"p.{source.chunk.page_number}",
                f"score: {source.score:.4f}",
                source.chunk.text,
                "",
            ]
        )

    return "\n".join(lines).rstrip()


if __name__ == "__main__":
    raise SystemExit(main())
