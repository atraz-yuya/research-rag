import math

import pytest

from research_rag.models import Chunk, EmbeddedChunk
from research_rag.retriever import cosine_similarity, retrieve_similar_chunks


def test_cosine_similarity_of_identical_vectors_is_one() -> None:
    assert cosine_similarity([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)


def test_cosine_similarity_of_orthogonal_vectors_is_zero() -> None:
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_of_different_directions_matches_expected_value() -> None:
    expected = 1.0 / math.sqrt(2.0)

    assert cosine_similarity([1.0, 0.0], [1.0, 1.0]) == pytest.approx(expected)


def test_cosine_similarity_rejects_different_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions must match"):
        cosine_similarity([1.0, 0.0], [1.0])


@pytest.mark.parametrize(
    ("vector_a", "vector_b"),
    [([], [1.0]), ([1.0], [])],
)
def test_cosine_similarity_rejects_empty_vector(
    vector_a: list[float],
    vector_b: list[float],
) -> None:
    with pytest.raises(ValueError, match="vectors must not be empty"):
        cosine_similarity(vector_a, vector_b)


@pytest.mark.parametrize(
    ("vector_a", "vector_b"),
    [([0.0, 0.0], [1.0, 0.0]), ([1.0, 0.0], [0.0, 0.0])],
)
def test_cosine_similarity_rejects_zero_vector(
    vector_a: list[float],
    vector_b: list[float],
) -> None:
    with pytest.raises(ValueError, match="zero vector"):
        cosine_similarity(vector_a, vector_b)


@pytest.mark.parametrize("non_finite_value", [math.nan, math.inf, -math.inf])
def test_cosine_similarity_rejects_non_finite_value(
    non_finite_value: float,
) -> None:
    with pytest.raises(ValueError, match="non-finite value"):
        cosine_similarity([1.0, non_finite_value], [1.0, 0.0])


def make_embedded_chunk(
    text: str,
    embedding: tuple[float, ...],
    *,
    document_name: str = "paper.pdf",
    page_number: int = 1,
    chunk_index: int = 0,
) -> EmbeddedChunk:
    return EmbeddedChunk(
        chunk=Chunk(
            document_name=document_name,
            page_number=page_number,
            chunk_index=chunk_index,
            text=text,
        ),
        embedding=embedding,
    )


def test_retrieve_similar_chunks_returns_one_ranked_original_chunk() -> None:
    embedded_chunk = make_embedded_chunk(
        "relevant text",
        (1.0, 0.0),
        document_name="research.pdf",
        page_number=7,
    )

    results = retrieve_similar_chunks([1.0, 0.0], [embedded_chunk])

    assert len(results) == 1
    assert results[0].chunk is embedded_chunk.chunk
    assert results[0].score == pytest.approx(1.0)
    assert results[0].rank == 1
    assert results[0].chunk.document_name == "research.pdf"
    assert results[0].chunk.page_number == 7


def test_retrieve_similar_chunks_sorts_by_score_and_assigns_ranks() -> None:
    orthogonal = make_embedded_chunk("orthogonal", (0.0, 1.0), chunk_index=0)
    diagonal = make_embedded_chunk("diagonal", (1.0, 1.0), chunk_index=1)
    identical = make_embedded_chunk("identical", (1.0, 0.0), chunk_index=2)

    results = retrieve_similar_chunks(
        [1.0, 0.0],
        [orthogonal, diagonal, identical],
    )

    assert [result.chunk for result in results] == [
        identical.chunk,
        diagonal.chunk,
        orthogonal.chunk,
    ]
    assert [result.score for result in results] == pytest.approx(
        [1.0, 1.0 / math.sqrt(2.0), 0.0]
    )
    assert [result.rank for result in results] == [1, 2, 3]


def test_retrieve_similar_chunks_limits_results_with_top_k() -> None:
    embedded_chunks = [
        make_embedded_chunk("first", (1.0, 0.0), chunk_index=0),
        make_embedded_chunk("second", (1.0, 1.0), chunk_index=1),
        make_embedded_chunk("third", (0.0, 1.0), chunk_index=2),
    ]

    results = retrieve_similar_chunks(
        [1.0, 0.0],
        embedded_chunks,
        top_k=2,
    )

    assert len(results) == 2
    assert [result.chunk.text for result in results] == ["first", "second"]


def test_retrieve_similar_chunks_returns_all_when_top_k_exceeds_count() -> None:
    embedded_chunks = [
        make_embedded_chunk("first", (1.0, 0.0), chunk_index=0),
        make_embedded_chunk("second", (0.0, 1.0), chunk_index=1),
    ]

    results = retrieve_similar_chunks(
        [1.0, 0.0],
        embedded_chunks,
        top_k=3,
    )

    assert len(results) == 2


@pytest.mark.parametrize("top_k", [0, -1])
def test_retrieve_similar_chunks_rejects_non_positive_top_k(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k must be greater than 0"):
        retrieve_similar_chunks([1.0, 0.0], [], top_k=top_k)


def test_retrieve_similar_chunks_returns_empty_for_no_targets() -> None:
    assert retrieve_similar_chunks([1.0, 0.0], [], top_k=3) == []


def test_retrieve_similar_chunks_rejects_embedding_dimension_mismatch() -> None:
    embedded_chunk = make_embedded_chunk("text", (1.0, 0.0, 0.0))

    with pytest.raises(ValueError, match="dimensions must match"):
        retrieve_similar_chunks([1.0, 0.0], [embedded_chunk])


def test_retrieve_similar_chunks_preserves_input_order_for_equal_scores() -> None:
    first = make_embedded_chunk("first", (1.0, 1.0), chunk_index=0)
    second = make_embedded_chunk("second", (1.0, 1.0), chunk_index=1)
    third = make_embedded_chunk("third", (1.0, 1.0), chunk_index=2)

    results = retrieve_similar_chunks(
        [1.0, 0.0],
        [first, second, third],
    )

    assert [result.chunk for result in results] == [
        first.chunk,
        second.chunk,
        third.chunk,
    ]
