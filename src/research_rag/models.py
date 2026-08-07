from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    """Text extracted from one PDF page."""

    document_name: str
    page_number: int
    text: str


@dataclass(frozen=True)
class Chunk:
    """A searchable text segment from one PDF page."""

    document_name: str
    page_number: int
    chunk_index: int
    text: str


@dataclass(frozen=True)
class EmbeddedChunk:
    """A chunk paired with its immutable embedding vector."""

    chunk: Chunk
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class SearchResult:
    """A ranked chunk returned by vector similarity search."""

    chunk: Chunk
    score: float
    rank: int
