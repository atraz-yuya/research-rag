import math

from .models import Chunk, EmbeddedChunk
from .ollama_client import OllamaClient


def embed_chunks(
    chunks: list[Chunk],
    model: str,
    client: OllamaClient,
) -> list[EmbeddedChunk]:
    """Pair chunks with embeddings returned by an embedding client."""
    if not model.strip():
        raise ValueError("model must not be empty")
    if not chunks:
        return []

    for index, chunk in enumerate(chunks):
        if not chunk.text.strip():
            raise ValueError(f"Chunk at index {index} has empty text")

    embeddings = client.embed_texts(
        [chunk.text for chunk in chunks],
        model=model,
    )

    if len(embeddings) != len(chunks):
        raise ValueError("embedding count does not match chunk count")

    immutable_embeddings: list[tuple[float, ...]] = []
    expected_dimension: int | None = None

    for index, embedding in enumerate(embeddings):
        if not isinstance(embedding, list):
            raise ValueError(f"Embedding at index {index} must be a list")
        if not embedding:
            raise ValueError(f"Embedding at index {index} is empty")

        immutable_embedding: list[float] = []
        for value in embedding:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Embedding at index {index} contains a non-numeric value"
                )

            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise ValueError(
                    f"Embedding at index {index} contains a non-finite value"
                )
            immutable_embedding.append(numeric_value)

        if expected_dimension is None:
            expected_dimension = len(immutable_embedding)
        elif len(immutable_embedding) != expected_dimension:
            raise ValueError("embedding dimensions are inconsistent")

        immutable_embeddings.append(tuple(immutable_embedding))

    return [
        EmbeddedChunk(chunk=chunk, embedding=embedding)
        for chunk, embedding in zip(chunks, immutable_embeddings, strict=True)
    ]
