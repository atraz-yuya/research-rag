import io
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import pytest

from research_rag.ollama_client import OllamaClient, OllamaError


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
