import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import pytest

from research_rag.ollama_client import (
    DEFAULT_TIMEOUT_SECONDS,
    OllamaClient,
    OllamaError,
)


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def install_fake_urlopen(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[urllib.request.Request, float], FakeResponse],
) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", handler)


def test_embed_texts_posts_batch_request_and_parses_embeddings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["content_type"] = request.get_header("Content-type")
        captured["payload"] = json.loads(request.data or b"")
        captured["timeout"] = timeout
        return FakeResponse(b'{"embeddings": [[0.1, 0.2], [0.3, 0.4]]}')

    install_fake_urlopen(monkeypatch, fake_urlopen)
    client = OllamaClient(base_url="http://ollama.test/", timeout=12.5)

    embeddings = client.embed_texts(["first", "second"], model="embed-model")

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert captured == {
        "url": "http://ollama.test/api/embed",
        "method": "POST",
        "content_type": "application/json",
        "payload": {"model": "embed-model", "input": ["first", "second"]},
        "timeout": 12.5,
    }


def test_embed_texts_returns_empty_list_without_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise AssertionError("HTTP request must not be made")

    install_fake_urlopen(monkeypatch, fail_urlopen)

    assert OllamaClient().embed_texts([], model="embed-model") == []


def test_client_uses_extended_default_timeout() -> None:
    client = OllamaClient()

    assert DEFAULT_TIMEOUT_SECONDS == 300.0
    assert client.timeout == 300.0


def test_embed_texts_reports_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.URLError("connection refused")

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="Could not connect to Ollama") as error:
        OllamaClient().embed_texts(["text"], model="embed-model")

    assert isinstance(error.value.__cause__, urllib.error.URLError)


def test_embed_texts_reports_wait_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise TimeoutError("timed out")

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(
        OllamaError,
        match="Timed out while waiting for Ollama at http://localhost:11434",
    ) as error:
        OllamaClient().embed_texts(["text"], model="embed-model")

    assert isinstance(error.value.__cause__, TimeoutError)


def test_embed_texts_reports_unavailable_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error": "model not found"}'),
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="model 'missing-model' is not available"):
        OllamaClient().embed_texts(["text"], model="missing-model")


def test_embed_texts_reports_other_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"error": "server failed"}'),
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="HTTP 500: server failed"):
        OllamaClient().embed_texts(["text"], model="embed-model")


def test_embed_texts_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(b"not-json")

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="invalid JSON"):
        OllamaClient().embed_texts(["text"], model="embed-model")


@pytest.mark.parametrize(
    ("payload", "texts", "message"),
    [
        ({}, ["text"], "does not contain an embeddings field"),
        ({"embeddings": [[0.1]]}, ["first", "second"], "count does not match"),
        ({"embeddings": [[]]}, ["text"], "Embedding at index 0 is empty"),
        (
            {"embeddings": [[0.1, 0.2], [0.3]]},
            ["first", "second"],
            "dimensions are inconsistent",
        ),
        (
            {"embeddings": [[0.1, "invalid"]]},
            ["text"],
            "contains a non-numeric value",
        ),
    ],
)
def test_embed_texts_rejects_invalid_response_structure(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    texts: list[str],
    message: str,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match=message):
        OllamaClient().embed_texts(texts, model="embed-model")


def test_generate_chat_posts_messages_and_returns_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data or b"")
        captured["timeout"] = timeout
        return FakeResponse(
            b'{"message": {"role": "assistant", "content": " Generated answer. "}}'
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)
    client = OllamaClient(base_url="http://ollama.test/", timeout=9.0)
    messages = [{"role": "user", "content": "Question"}]

    answer = client.generate_chat(messages, model="generation-model")

    assert answer == "Generated answer."
    assert captured == {
        "url": "http://ollama.test/api/chat",
        "payload": {
            "model": "generation-model",
            "messages": messages,
            "stream": False,
            "think": False,
        },
        "timeout": 9.0,
    }


def test_generate_chat_includes_optional_generation_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        captured["payload"] = json.loads(request.data or b"")
        return FakeResponse(
            b'{"message": {"role": "assistant", "content": "answer"}}'
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)
    messages = [{"role": "user", "content": "Question"}]

    answer = OllamaClient().generate_chat(
        messages,
        model="generation-model",
        options={"num_ctx": 32768, "temperature": 0},
    )

    assert answer == "answer"
    assert captured["payload"] == {
        "model": "generation-model",
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {"num_ctx": 32768, "temperature": 0},
    }


def test_generate_chat_reports_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            {},
            io.BytesIO(b'{"error": "generation failed"}'),
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="HTTP 500: generation failed"):
        OllamaClient().generate_chat(
            [{"role": "user", "content": "Question"}],
            model="generation-model",
        )


def test_generate_chat_reports_unavailable_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error": "model not found"}'),
        )

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="model 'missing-model' is not available"):
        OllamaClient().generate_chat(
            [{"role": "user", "content": "Question"}],
            model="missing-model",
        )


def test_generate_chat_rejects_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(b"not-json")

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="invalid JSON"):
        OllamaClient().generate_chat(
            [{"role": "user", "content": "Question"}],
            model="generation-model",
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "does not contain a message field"),
        ({"message": "invalid"}, "message field must be an object"),
        ({"message": {}}, "does not contain a content field"),
        ({"message": {"content": 123}}, "content field must be a string"),
    ],
)
def test_generate_chat_rejects_invalid_response_structure(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    message: str,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match=message):
        OllamaClient().generate_chat(
            [{"role": "user", "content": "Question"}],
            model="generation-model",
        )


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_generate_chat_rejects_empty_answer(
    monkeypatch: pytest.MonkeyPatch,
    content: str,
) -> None:
    def fake_urlopen(
        request: urllib.request.Request,
        timeout: float,
    ) -> FakeResponse:
        payload = {"message": {"role": "assistant", "content": content}}
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    install_fake_urlopen(monkeypatch, fake_urlopen)

    with pytest.raises(OllamaError, match="empty answer"):
        OllamaClient().generate_chat(
            [{"role": "user", "content": "Question"}],
            model="generation-model",
        )
