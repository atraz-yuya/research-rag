import math
from collections.abc import Sequence

from .models import EmbeddedChunk, SearchResult


def cosine_similarity(
    vector_a: Sequence[float],
    vector_b: Sequence[float],
) -> float:
    """Calculate cosine similarity between two finite, non-zero vectors."""
    if not vector_a or not vector_b:
        raise ValueError("vectors must not be empty")
    if len(vector_a) != len(vector_b):
        raise ValueError("vector dimensions must match")

    values_a = _validated_vector(vector_a, name="vector_a")
    values_b = _validated_vector(vector_b, name="vector_b")
    norm_a_squared = math.fsum(value * value for value in values_a)
    norm_b_squared = math.fsum(value * value for value in values_b)

    if norm_a_squared == 0.0 or norm_b_squared == 0.0:
        raise ValueError("cosine similarity is undefined for a zero vector")

    dot_product = math.fsum(
        value_a * value_b
        for value_a, value_b in zip(values_a, values_b, strict=True)
    )
    return dot_product / math.sqrt(norm_a_squared * norm_b_squared)


def retrieve_similar_chunks(
    query_embedding: Sequence[float],
    embedded_chunks: Sequence[EmbeddedChunk],
    top_k: int = 3,
) -> list[SearchResult]:
    """Return the most similar chunks in descending cosine-similarity order."""
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if not embedded_chunks:
        return []

    scored_chunks = [
        (
            embedded_chunk,
            cosine_similarity(query_embedding, embedded_chunk.embedding),
        )
        for embedded_chunk in embedded_chunks
    ]
    scored_chunks.sort(key=lambda item: -item[1])

    return [
        SearchResult(
            chunk=embedded_chunk.chunk,
            score=score,
            rank=rank,
        )
        for rank, (embedded_chunk, score) in enumerate(
            scored_chunks[:top_k],
            start=1,
        )
    ]


def _validated_vector(
    vector: Sequence[float],
    name: str,
) -> tuple[float, ...]:
    values: list[float] = []

    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} contains a non-numeric value")

        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise ValueError(f"{name} contains a non-finite value")
        values.append(numeric_value)

    return tuple(values)
