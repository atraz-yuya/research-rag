from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    """Text extracted from one PDF page."""

    document_name: str
    page_number: int
    text: str
