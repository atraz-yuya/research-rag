from pathlib import Path

import pymupdf
import pytest

from research_rag.pdf_reader import NoExtractableTextError, extract_page_texts


def create_pdf(pdf_path: Path, page_texts: list[str | None]) -> None:
    """Create a temporary PDF with one page per supplied text value."""
    document = pymupdf.open()
    try:
        for text in page_texts:
            page = document.new_page()
            if text is not None:
                page.insert_text((72, 72), text)
        document.save(pdf_path)
    finally:
        document.close()


def test_extract_page_texts_preserves_order_numbers_and_document_name(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "research-paper.pdf"
    create_pdf(pdf_path, ["First page", "Second page", "Third page"])

    pages = extract_page_texts(pdf_path)

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert [page.document_name for page in pages] == [pdf_path.name] * 3
    assert [page.text for page in pages] == [
        "First page",
        "Second page",
        "Third page",
    ]


def test_extract_page_texts_strips_surrounding_whitespace(tmp_path: Path) -> None:
    pdf_path = tmp_path / "whitespace.pdf"
    create_pdf(pdf_path, ["   text with surrounding whitespace   "])

    pages = extract_page_texts(pdf_path)

    assert len(pages) == 1
    assert pages[0].text == "text with surrounding whitespace"


def test_extract_page_texts_keeps_empty_page_when_other_page_has_text(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "partly-empty.pdf"
    create_pdf(pdf_path, ["Before empty page", None, "After empty page"])

    pages = extract_page_texts(pdf_path)

    assert [page.page_number for page in pages] == [1, 2, 3]
    assert [page.text for page in pages] == [
        "Before empty page",
        "",
        "After empty page",
    ]


def test_extract_page_texts_raises_for_missing_file(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        extract_page_texts(missing_path)


def test_extract_page_texts_raises_for_non_file_path(tmp_path: Path) -> None:
    with pytest.raises(IsADirectoryError, match="not a regular file"):
        extract_page_texts(tmp_path)


def test_extract_page_texts_raises_for_non_pdf_file(tmp_path: Path) -> None:
    text_path = tmp_path / "not-a-pdf.txt"
    text_path.write_text("This is not a PDF.", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to open PDF"):
        extract_page_texts(text_path)


def test_extract_page_texts_raises_when_all_pages_are_empty(tmp_path: Path) -> None:
    pdf_path = tmp_path / "all-empty.pdf"
    create_pdf(pdf_path, [None, None])

    with pytest.raises(
        NoExtractableTextError,
        match="No text could be extracted",
    ):
        extract_page_texts(pdf_path)
