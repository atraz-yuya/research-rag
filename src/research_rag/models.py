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
