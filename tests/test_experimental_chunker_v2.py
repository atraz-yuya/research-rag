import pytest

from research_rag.experimental_chunker_v2 import (
    split_pages_into_strict_heading_aware_chunks,
)
from research_rag.models import PageText


def make_page(
    text: str,
    *,
    page_number: int = 1,
) -> PageText:
    return PageText("paper.pdf", page_number, text)


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
def test_same_line_numbered_headings_create_boundaries(heading: str) -> None:
    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(f"Earlier text\n{heading}\nSection text")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [
        "Earlier text",
        f"{heading}\nSection text",
    ]


@pytest.mark.parametrize(
    ("number", "title"),
    [("4.2", "Data"), ("6", "Conclusion")],
)
def test_split_heading_with_title_and_body_creates_boundary(
    number: str,
    title: str,
) -> None:
    body = "The methods are compared on two data sets."
    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(f"Earlier text\n{number}\n{title}\n{body}")],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [
        "Earlier text",
        f"{number}\n{title}\n{body}",
    ]


def test_decimal_axis_values_do_not_create_tiny_chunks() -> None:
    text = "Figure text\n0.7\n0.6\n0.5\n0.4\nAnomaly Score"

    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(text)],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [text]
    assert all(len(chunk.text) > 3 for chunk in chunks)


def test_nonzero_decimal_axis_values_do_not_create_boundaries() -> None:
    text = (
        "Figure text\n2.5\n5.0\n7.5\nAccuracy\n"
        "Values are shown for each model."
    )

    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(text)],
        chunk_size=200,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [text]


@pytest.mark.parametrize("number", ["2022", "2019", "49"])
def test_standalone_integers_do_not_create_boundaries(number: str) -> None:
    text = f"Earlier text\n{number}\nTrailing text"

    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(text)],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == [text]


def test_chunks_never_cross_page_boundaries() -> None:
    chunks = split_pages_into_strict_heading_aware_chunks(
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
    chunks = split_pages_into_strict_heading_aware_chunks(
        [
            make_page("Preamble\n4 Data\nSection", page_number=1),
            make_page("Preamble\n5 Results\nSection", page_number=2),
        ],
        chunk_size=100,
        overlap=10,
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 0, 1]


def test_long_section_is_split_by_character_count_with_overlap() -> None:
    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page("abcdefghijklmno")],
        chunk_size=10,
        overlap=3,
    )

    assert [chunk.text for chunk in chunks] == ["abcdefghij", "hijklmno"]
    assert chunks[0].text[-3:] == chunks[1].text[:3] == "hij"


def test_blank_page_is_skipped() -> None:
    chunks = split_pages_into_strict_heading_aware_chunks(
        [make_page(" \n\t"), make_page("Content", page_number=2)],
        chunk_size=10,
        overlap=3,
    )

    assert len(chunks) == 1
    assert chunks[0].page_number == 2
    assert chunks[0].chunk_index == 0
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
        split_pages_into_strict_heading_aware_chunks(
            [],
            chunk_size=chunk_size,
            overlap=overlap,
        )
