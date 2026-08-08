from .experimental_chunker_v2 import (
    _NUMBER_ONLY_PATTERN,
    _find_heading_starts,
    _split_at_strict_numbered_headings,
    _split_section,
)
from .models import Chunk, PageText


def split_pages_into_heading_context_chunks(
    pages: list[PageText],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    """Prepend a strict section heading to its continuation chunks.

    Body windows remain identical to Candidate v2, so continuation text may
    exceed ``chunk_size`` by the heading prefix length.
    """
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
        for section in _split_at_strict_numbered_headings(page.text):
            heading = _extract_section_heading(section)
            section_chunks = _split_section(
                section,
                chunk_size=chunk_size,
                overlap=overlap,
            )
            for section_chunk_index, body_window in enumerate(section_chunks):
                chunk_text = body_window
                if section_chunk_index > 0 and heading is not None:
                    chunk_text = _prepend_heading_unless_present(
                        body_window,
                        heading,
                    )
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


def _extract_section_heading(section: str) -> str | None:
    heading_starts = _find_heading_starts(section)
    if not heading_starts or heading_starts[0] != 0:
        return None

    lines = section.splitlines()
    first_line = lines[0].strip()
    if _NUMBER_ONLY_PATTERN.fullmatch(first_line) is None:
        return first_line

    for line in lines[1:]:
        title = line.strip()
        if title:
            return f"{first_line}\n{title}"

    return first_line


def _prepend_heading_unless_present(
    body_window: str,
    heading: str,
) -> str:
    if body_window == heading or body_window.startswith(f"{heading}\n"):
        return body_window
    return f"{heading}\n{body_window}"
