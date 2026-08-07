import json
import math
import urllib.error
import urllib.request
from typing import Any


DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_TIMEOUT_SECONDS = 30.0


class OllamaError(RuntimeError):
    """An error raised while requesting or validating an Ollama response."""


class OllamaClient:
    """Minimal HTTP client for Ollama's embedding and chat APIs."""

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be greater than 0")

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def embed_texts(self, texts: list[str], model: str) -> list[list[float]]:
        """Generate one embedding per input text using Ollama."""
        if not model.strip():
            raise ValueError("model must not be empty")
        if not texts:
            return []

        for index, text in enumerate(texts):
            if not text.strip():
                raise ValueError(f"Text at index {index} is empty")

        response_data = self._post_json(
            "/api/embed",
            {"model": model, "input": texts},
            model=model,
        )
        return _parse_embeddings(response_data, expected_count=len(texts))

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> str:
        """Generate a non-streaming chat answer using Ollama."""
        if not model.strip():
            raise ValueError("model must not be empty")
        if not messages:
            raise ValueError("messages must not be empty")

        for index, message in enumerate(messages):
            role = message.get("role")
            content = message.get("content")
            if not isinstance(role, str) or not role.strip():
                raise ValueError(f"Message at index {index} has an invalid role")
            if not isinstance(content, str) or not content.strip():
                raise ValueError(f"Message at index {index} has empty content")

        response_data = self._post_json(
            "/api/chat",
            {"model": model, "messages": messages, "stream": False},
            model=model,
        )
        return _parse_chat_answer(response_data)

    def _post_json(
        self,
        endpoint: str,
        payload: dict[str, object],
        model: str,
    ) -> object:
        request_body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read()
        except urllib.error.HTTPError as exc:
            detail = _read_http_error_detail(exc)
            if exc.code == 404:
                raise OllamaError(
                    f"Ollama model '{model}' is not available "
                    f"(HTTP 404): {detail}"
                ) from exc
            raise OllamaError(
                f"Ollama API returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"Could not connect to Ollama at {self.base_url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise OllamaError(
                f"Timed out while connecting to Ollama at {self.base_url}"
            ) from exc

        try:
            response_data: Any = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OllamaError("Ollama returned invalid JSON") from exc

        return response_data


def _read_http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        response_body = error.read()
    except OSError:
        return str(error.reason)

    try:
        response_data = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return str(error.reason)

    if isinstance(response_data, dict) and isinstance(
        response_data.get("error"), str
    ):
        return response_data["error"]

    return str(error.reason)


def _parse_embeddings(
    response_data: object,
    expected_count: int,
) -> list[list[float]]:
    if not isinstance(response_data, dict):
        raise OllamaError("Ollama response must be a JSON object")
    if "embeddings" not in response_data:
        raise OllamaError("Ollama response does not contain an embeddings field")

    embeddings = response_data["embeddings"]
    if not isinstance(embeddings, list):
        raise OllamaError("Ollama embeddings field must be an array")
    if len(embeddings) != expected_count:
        raise OllamaError("Ollama embedding count does not match input count")

    parsed_embeddings: list[list[float]] = []
    expected_dimension: int | None = None

    for index, embedding in enumerate(embeddings):
        if not isinstance(embedding, list):
            raise OllamaError(f"Embedding at index {index} must be an array")
        if not embedding:
            raise OllamaError(f"Embedding at index {index} is empty")

        parsed_embedding: list[float] = []
        for value in embedding:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise OllamaError(
                    f"Embedding at index {index} contains a non-numeric value"
                )

            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise OllamaError(
                    f"Embedding at index {index} contains a non-finite value"
                )
            parsed_embedding.append(numeric_value)

        if expected_dimension is None:
            expected_dimension = len(parsed_embedding)
        elif len(parsed_embedding) != expected_dimension:
            raise OllamaError("Ollama embedding dimensions are inconsistent")

        parsed_embeddings.append(parsed_embedding)

    return parsed_embeddings


def _parse_chat_answer(response_data: object) -> str:
    if not isinstance(response_data, dict):
        raise OllamaError("Ollama response must be a JSON object")
    if "message" not in response_data:
        raise OllamaError("Ollama response does not contain a message field")

    message = response_data["message"]
    if not isinstance(message, dict):
        raise OllamaError("Ollama message field must be an object")
    if "content" not in message:
        raise OllamaError("Ollama message does not contain a content field")

    content = message["content"]
    if not isinstance(content, str):
        raise OllamaError("Ollama message content field must be a string")

    answer = content.strip()
    if not answer:
        raise OllamaError("Ollama returned an empty answer")

    return answer
