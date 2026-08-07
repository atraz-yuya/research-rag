from .models import Chunk, PageText


def split_pages_into_chunks(
    pages: list[PageText],
    chunk_size: int = 1000,
    overlap: int = 150,
) -> list[Chunk]:
    """Split each page into overlapping character-based chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    if overlap < 0:
        raise ValueError("overlap must be non-negative")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size")

    chunks: list[Chunk] = []
    step = chunk_size - overlap

    for page in pages:
        if not page.text.strip():
            continue

        chunk_index = 0
        start = 0

        while start < len(page.text):
            end = min(start + chunk_size, len(page.text))
            chunk_text = page.text[start:end].strip()

            if chunk_text:
                chunks.append(
                    Chunk(
                        document_name=page.document_name,
                        page_number=page.page_number,
                        chunk_index=chunk_index,
                        text=chunk_text,
                    )
                )
                chunk_index += 1

            if end == len(page.text):
                break

            start += step

    return chunks
