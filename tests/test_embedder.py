import pytest

from research_rag.embedder import embed_chunks
from research_rag.models import Chunk, EmbeddedChunk


class StubEmbeddingClient:
    def __init__(self, embeddings: list[list[float]]) -> None:
        self.embeddings = embeddings
        self.calls: list[tuple[list[str], str]] = []

    def embed_texts(self, texts: list[str], model: str) -> list[list[float]]:
        self.calls.append((texts, model))
        return self.embeddings


def make_chunk(text: str, page_number: int = 1, chunk_index: int = 0) -> Chunk:
    return Chunk(
        document_name="paper.pdf",
        page_number=page_number,
        chunk_index=chunk_index,
        text=text,
    )


def test_embed_chunks_converts_one_chunk_and_preserves_original() -> None:
    chunk = make_chunk("first text")
    client = StubEmbeddingClient([[0.1, 0.2, 0.3]])

    embedded = embed_chunks([chunk], model="test-model", client=client)

    assert embedded == [
        EmbeddedChunk(chunk=chunk, embedding=(0.1, 0.2, 0.3))
    ]
    assert embedded[0].chunk is chunk
    assert client.calls == [(["first text"], "test-model")]


def test_embed_chunks_preserves_order_and_pairs_each_embedding() -> None:
    chunks = [
        make_chunk("first", page_number=1, chunk_index=0),
        make_chunk("second", page_number=1, chunk_index=1),
        make_chunk("third", page_number=2, chunk_index=0),
    ]
    client = StubEmbeddingClient([[1, 0], [0, 1], [0.5, 0.5]])

    embedded = embed_chunks(chunks, model="another-model", client=client)

    assert [item.chunk for item in embedded] == chunks
    assert [item.embedding for item in embedded] == [
        (1.0, 0.0),
        (0.0, 1.0),
        (0.5, 0.5),
    ]
    assert client.calls == [(["first", "second", "third"], "another-model")]


def test_embed_chunks_returns_empty_list_without_calling_client() -> None:
    client = StubEmbeddingClient([])

    assert embed_chunks([], model="test-model", client=client) == []
    assert client.calls == []


def test_embed_chunks_rejects_embedding_count_mismatch() -> None:
    chunks = [make_chunk("first"), make_chunk("second", chunk_index=1)]
    client = StubEmbeddingClient([[0.1, 0.2]])

    with pytest.raises(ValueError, match="embedding count does not match chunk count"):
        embed_chunks(chunks, model="test-model", client=client)


def test_embed_chunks_rejects_empty_embedding() -> None:
    client = StubEmbeddingClient([[]])

    with pytest.raises(ValueError, match="Embedding at index 0 is empty"):
        embed_chunks([make_chunk("text")], model="test-model", client=client)


def test_embed_chunks_rejects_inconsistent_embedding_dimensions() -> None:
    chunks = [make_chunk("first"), make_chunk("second", chunk_index=1)]
    client = StubEmbeddingClient([[0.1, 0.2], [0.3]])

    with pytest.raises(ValueError, match="embedding dimensions are inconsistent"):
        embed_chunks(chunks, model="test-model", client=client)


def test_embed_chunks_rejects_non_numeric_embedding_value() -> None:
    chunk = make_chunk("text")
    client = StubEmbeddingClient([[0.1, "invalid"]])  # type: ignore[list-item]

    with pytest.raises(ValueError, match="contains a non-numeric value"):
        embed_chunks([chunk], model="test-model", client=client)


@pytest.mark.parametrize("text", ["", "   \n\t"])
def test_embed_chunks_rejects_empty_or_whitespace_only_chunk(text: str) -> None:
    client = StubEmbeddingClient([[0.1]])

    with pytest.raises(ValueError, match="Chunk at index 0 has empty text"):
        embed_chunks([make_chunk(text)], model="test-model", client=client)

    assert client.calls == []
