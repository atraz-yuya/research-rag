from pathlib import Path
from typing import Any

import pytest

from research_rag import cli
from research_rag.models import Chunk, RagAnswer, SearchResult
from research_rag.ollama_client import OllamaError


def make_answer() -> RagAnswer:
    first = SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=3,
            chunk_index=0,
            text="First source passage.",
        ),
        score=0.91234,
        rank=1,
    )
    second = SearchResult(
        chunk=Chunk(
            document_name="paper.pdf",
            page_number=8,
            chunk_index=0,
            text="Second source passage.",
        ),
        score=0.85123,
        rank=2,
    )
    return RagAnswer("Generated grounded answer.", (first, second))


def test_parser_accepts_pdf_question_models_and_top_k() -> None:
    args = cli.build_parser().parse_args(
        [
            "paper.pdf",
            "What is proposed?",
            "--embedding-model",
            "custom-embedding",
            "--generation-model",
            "custom-generation",
            "--top-k",
            "5",
            "--ollama-base-url",
            "http://ollama.test:11434",
        ]
    )

    assert args.pdf_path == Path("paper.pdf")
    assert args.question == "What is proposed?"
    assert args.embedding_model == "custom-embedding"
    assert args.generation_model == "custom-generation"
    assert args.top_k == 5
    assert args.ollama_base_url == "http://ollama.test:11434"


def test_parser_uses_documented_defaults() -> None:
    args = cli.build_parser().parse_args(["paper.pdf", "Question"])

    assert args.embedding_model == "qwen3-embedding:0.6b"
    assert args.generation_model == "qwen3:4b-instruct"
    assert args.top_k == 3


def test_help_shows_default_generation_model(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["--help"])

    output = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "既定: qwen3:4b-instruct" in output.out


def test_main_runs_pipeline_and_prints_answer_and_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected_answer = make_answer()
    captured: dict[str, Any] = {}

    def fake_answer_question_from_pdf(
        pdf_path: Path,
        question: str,
        *,
        embedding_model: str,
        generation_model: str,
        top_k: int,
        client: Any,
    ) -> RagAnswer:
        captured.update(
            pdf_path=pdf_path,
            question=question,
            embedding_model=embedding_model,
            generation_model=generation_model,
            top_k=top_k,
            base_url=client.base_url,
        )
        return expected_answer

    monkeypatch.setattr(
        cli,
        "answer_question_from_pdf",
        fake_answer_question_from_pdf,
    )

    exit_code = cli.main(
        [
            "paper.pdf",
            "What is proposed?",
            "--embedding-model",
            "embedding-model",
            "--generation-model",
            "generation-model",
            "--top-k",
            "2",
            "--ollama-base-url",
            "http://ollama.test:11434/",
        ]
    )

    output = capsys.readouterr()
    assert exit_code == 0
    assert output.err == ""
    assert "回答:" in output.out
    assert "Generated grounded answer." in output.out
    assert "参照:" in output.out
    assert "[1] paper.pdf p.3" in output.out
    assert "score: 0.9123" in output.out
    assert "First source passage." in output.out
    assert "[2] paper.pdf p.8" in output.out
    assert "score: 0.8512" in output.out
    assert "Second source passage." in output.out
    assert captured == {
        "pdf_path": Path("paper.pdf"),
        "question": "What is proposed?",
        "embedding_model": "embedding-model",
        "generation_model": "generation-model",
        "top_k": 2,
        "base_url": "http://ollama.test:11434",
    }


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("PDF file does not exist: missing.pdf"),
        ValueError("No text could be extracted from PDF"),
        OllamaError("Could not connect to Ollama"),
    ],
)
def test_main_reports_pipeline_error_and_returns_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    def fake_answer_question_from_pdf(*args: Any, **kwargs: Any) -> RagAnswer:
        raise error

    monkeypatch.setattr(
        cli,
        "answer_question_from_pdf",
        fake_answer_question_from_pdf,
    )

    exit_code = cli.main(["paper.pdf", "Question"])

    output = capsys.readouterr()
    assert exit_code != 0
    assert output.out == ""
    assert f"エラー: {error}" in output.err


@pytest.mark.parametrize("top_k", ["0", "-1"])
def test_parser_rejects_non_positive_top_k(top_k: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(
            ["paper.pdf", "Question", "--top-k", top_k]
        )

    assert exc_info.value.code != 0
