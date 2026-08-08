import re
from collections.abc import Sequence

from .models import Chunk, PageText


_SAME_LINE_HEADING_PATTERN = re.compile(
    r"^[ \t]*[1-9]\d{0,2}(?:\.\d+)*\.?[ \t]+[A-Z][^\n]*$"
)
_NUMBER_ONLY_PATTERN = re.compile(
    r"^[ \t]*[1-9]\d{0,2}(?:\.\d+)*\.?[ \t]*$"
)
_NUMERIC_VALUE_PATTERN = re.compile(
    r"^[ \t]*[+-]?(?:\d+(?:\.\d+)?|\.\d+)[ \t]*$"
)


def split_pages_into_strict_heading_aware_chunks(
    pages: list[PageText],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    """Split pages using conservative numbered-heading boundaries."""
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


def _split_at_strict_numbered_headings(text: str) -> tuple[str, ...]:
    heading_starts = _find_heading_starts(text)
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


def _find_heading_starts(text: str) -> tuple[int, ...]:
    lines = text.splitlines(keepends=True)
    line_texts = [line.rstrip("\r\n") for line in lines]
    line_starts: list[int] = []
    offset = 0

    for line in lines:
        line_starts.append(offset)
        offset += len(line)

    heading_starts: list[int] = []
    for index, line in enumerate(line_texts):
        if _SAME_LINE_HEADING_PATTERN.fullmatch(line):
            heading_starts.append(line_starts[index])
        elif _NUMBER_ONLY_PATTERN.fullmatch(line) and _is_split_heading(
            line_texts,
            index,
        ):
            heading_starts.append(line_starts[index])

    return tuple(heading_starts)


def _is_split_heading(lines: Sequence[str], number_index: int) -> bool:
    previous_index = _previous_nonempty_line_index(lines, number_index)
    if previous_index is not None and _is_numeric_value(lines[previous_index]):
        return False

    title_index = _next_nonempty_line_index(lines, number_index)
    if title_index is None or not _is_title_like(lines[title_index]):
        return False

    body_index = _next_nonempty_line_index(lines, title_index)
    return body_index is not None and _is_body_like(lines[body_index])


def _previous_nonempty_line_index(
    lines: Sequence[str],
    before_index: int,
) -> int | None:
    for index in range(before_index - 1, -1, -1):
        if lines[index].strip():
            return index
    return None


def _next_nonempty_line_index(
    lines: Sequence[str],
    after_index: int,
) -> int | None:
    for index in range(after_index + 1, len(lines)):
        if lines[index].strip():
            return index
    return None


def _is_title_like(line: str) -> bool:
    title = line.strip()
    if not title or len(title) > 120 or len(title.split()) > 12:
        return False
    if _is_numeric_value(title):
        return False
    return title[0].isupper() and any(character.isalpha() for character in title)


def _is_body_like(line: str) -> bool:
    body = line.strip()
    return (
        len(body.split()) >= 4
        and any(character.islower() for character in body)
        and not _is_numeric_value(body)
    )


def _is_numeric_value(line: str) -> bool:
    return _NUMERIC_VALUE_PATTERN.fullmatch(line) is not None


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
