from pathlib import Path

import pymupdf

from .models import PageText


def extract_page_texts(pdf_path: Path) -> list[PageText]:
    """Extract text from each page of a PDF in its original page order."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file does not exist: {pdf_path}")

    if pdf_path.is_dir():
        raise IsADirectoryError(f"PDF path is not a regular file: {pdf_path}")

    if not pdf_path.is_file():
        raise ValueError(f"PDF path is not a regular file: {pdf_path}")

    try:
        document = pymupdf.open(pdf_path, filetype="pdf")
    except (pymupdf.EmptyFileError, pymupdf.FileDataError) as exc:
        raise ValueError(f"Failed to open PDF file: {pdf_path}") from exc

    with document:
        pages = [
            PageText(
                document_name=pdf_path.name,
                page_number=page_index + 1,
                text=page.get_text().strip(),
            )
            for page_index, page in enumerate(document)
        ]

    if not any(page.text for page in pages):
        raise ValueError(f"No text could be extracted from PDF: {pdf_path}")

    return pages
