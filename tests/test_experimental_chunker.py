import pytest

from research_rag.experimental_chunker import (
    split_pages_into_heading_aware_chunks,
)
from research_rag.models import PageText


def make_page(
    text: str,
    *,
    page_number: int = 1,
    document_name: str = "paper.pdf",
) -> PageText:
    return PageText(document_name, page_number, text)


def test_numbered_heading_creates_a_hard_boundary() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page("Figure text...\n4.2 Data\nActual section text...")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [
        "Figure text...",
        "4.2 Data\nActual section text...",
    ]


def test_split_number_and_title_heading_starts_the_new_section() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page("Figure text...\n4.2\nData\nActual section text...")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [
        "Figure text...",
        "4.2\nData\nActual section text...",
    ]


@pytest.mark.parametrize(
    "heading",
    [
        "4 Data",
        "4.2 Data",
        "4.2.1 Elliptic.",
        "6 Conclusion",
        "6.1 Literature Review",
    ],
)
def test_common_numbered_heading_forms_are_detected(heading: str) -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page(f"Earlier text\n{heading}\nSection text")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [
        "Earlier text",
        f"{heading}\nSection text",
    ]


def test_chunks_never_cross_page_boundaries() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [
            make_page("Page one\n4 Data\nFirst section", page_number=1),
            make_page("Page two\n5 Results\nSecond section", page_number=2),
        ],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.page_number for chunk in chunks] == [1, 1, 2, 2]
    assert all("Page two" not in chunk.text for chunk in chunks[:2])
    assert all("Page one" not in chunk.text for chunk in chunks[2:])


def test_chunk_index_is_sequential_and_resets_for_each_page() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [
            make_page("Preamble\n4 Data\nSection", page_number=1),
            make_page("Preamble\n5 Results\nSection", page_number=2),
        ],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 0, 1]


def test_long_section_without_heading_is_split_by_character_count() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page("abcdefghijklmno")],
        chunk_size=10,
        overlap=3,
    )

    assert [chunk.text for chunk in chunks] == ["abcdefghij", "hijklmno"]


def test_long_section_preserves_overlap() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page("abcdefghijklmno")],
        chunk_size=10,
        overlap=3,
    )

    assert chunks[0].text[-3:] == chunks[1].text[:3] == "hij"


def test_blank_pages_do_not_create_chunks() -> None:
    chunks = split_pages_into_heading_aware_chunks(
        [make_page("   \n\t"), make_page("Content", page_number=2)],
        chunk_size=10,
        overlap=3,
    )

    assert len(chunks) == 1
    assert chunks[0].page_number == 2
    assert chunks[0].text == "Content"


@pytest.mark.parametrize(
    ("chunk_size", "overlap", "message"),
    [
        (0, 0, "chunk_size must be greater than 0"),
        (10, -1, "overlap must be non-negative"),
        (10, 10, "overlap must be smaller than chunk_size"),
    ],
)
def test_invalid_chunk_settings_raise_value_error(
    chunk_size: int,
    overlap: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        split_pages_into_heading_aware_chunks(
            [],
            chunk_size=chunk_size,
            overlap=overlap,
        )
