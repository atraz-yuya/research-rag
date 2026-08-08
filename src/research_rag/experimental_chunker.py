import re

from .models import Chunk, PageText


_NUMBERED_HEADING_PATTERN = re.compile(
    r"^[ \t]*(?:"
    r"\d+(?:\.\d+)*\.?[ \t]+[A-Z][^\n]*"
    r"|\d+(?:\.\d+)+\.?[ \t]*$"
    r")",
    re.MULTILINE,
)


def split_pages_into_heading_aware_chunks(
    pages: list[PageText],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    """Split pages at numbered headings, then by overlapping characters."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be non-negative")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[Chunk] = []

    for page in pages:
        if not page.text.strip():
            continue

        chunk_index = 0
        for section in _split_at_numbered_headings(page.text):
            for chunk_text in _split_section(
                section,
                chunk_size=chunk_size,
                overlap=overlap,
            ):
                chunks.append(
                    Chunk(
                        document_name=page.document_name,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=chunk_text,
                    )
                )
                chunk_index += 1

    return chunks


def _split_at_numbered_headings(text: str) -> tuple[str, ...]:
    heading_starts = [
        match.start() for match in _NUMBERED_HEADING_PATTERN.finditer(text)
    ]
    if not heading_starts:
        return (text,)

    sections: list[str] = []
    section_start = 0

    for heading_start in heading_starts:
        if heading_start > section_start:
            section = text[section_start:heading_start]
            if section.strip():
                sections.append(section)
        section_start = heading_start

    final_section = text[section_start:]
    if final_section.strip():
        sections.append(final_section)

    return tuple(sections)


def _split_section(
    section: str,
    *,
    chunk_size: int,
    overlap: int,
) -> tuple[str, ...]:
    if not section.strip():
        return ()

    chunks: list[str] = []
    step = chunk_size - overlap
    start = 0

    while start < len(section):
        end = min(start + chunk_size, len(section))
        chunk_text = section[start:end].strip()
        if chunk_text:
            chunks.append(chunk_text)

        if end == len(section):
            break
        start += step

    return tuple(chunks)
