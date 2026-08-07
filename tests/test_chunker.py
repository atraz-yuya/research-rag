import pytest

from research_rag.chunker import split_pages_into_chunks
from research_rag.models import Chunk, PageText


def test_short_page_becomes_one_chunk() -> None:
    pages = [PageText(document_name="paper.pdf", page_number=1, text="short text")]

    chunks = split_pages_into_chunks(pages, chunk_size=20, overlap=5)

    assert chunks == [
        Chunk(
            document_name="paper.pdf",
            page_number=1,
            chunk_index=0,
            text="short text",
        )
    ]


def test_long_page_is_split_with_overlap_and_complete_final_chunk() -> None:
    pages = [
        PageText(
            document_name="paper.pdf",
            page_number=1,
            text="abcdefghijklmno",
        )
    ]

    chunks = split_pages_into_chunks(pages, chunk_size=10, overlap=3)

    assert [chunk.text for chunk in chunks] == ["abcdefghij", "hijklmno"]
    assert chunks[0].text[-3:] == chunks[1].text[:3] == "hij"


def test_metadata_indices_and_page_boundaries_are_preserved() -> None:
    pages = [
        PageText(document_name="paper.pdf", page_number=1, text="A" * 12),
        PageText(document_name="paper.pdf", page_number=2, text="B" * 12),
    ]

    chunks = split_pages_into_chunks(pages, chunk_size=10, overlap=3)

    assert [chunk.document_name for chunk in chunks] == ["paper.pdf"] * 4
    assert [chunk.page_number for chunk in chunks] == [1, 1, 2, 2]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 0, 1]
    assert [chunk.text for chunk in chunks] == [
        "A" * 10,
        "A" * 5,
        "B" * 10,
        "B" * 5,
    ]
    assert all(set(chunk.text) <= {"A"} for chunk in chunks[:2])
    assert all(set(chunk.text) <= {"B"} for chunk in chunks[2:])


def test_empty_and_whitespace_only_pages_create_no_chunks() -> None:
    pages = [
        PageText(document_name="paper.pdf", page_number=1, text=""),
        PageText(document_name="paper.pdf", page_number=2, text="   \n\t"),
        PageText(document_name="paper.pdf", page_number=3, text="content"),
    ]

    chunks = split_pages_into_chunks(pages, chunk_size=10, overlap=2)

    assert chunks == [
        Chunk(
            document_name="paper.pdf",
            page_number=3,
            chunk_index=0,
            text="content",
        )
    ]


def test_whitespace_only_slices_are_skipped_and_indices_remain_sequential() -> None:
    pages = [
        PageText(
            document_name="paper.pdf",
            page_number=1,
            text="abc      def",
        )
    ]

    chunks = split_pages_into_chunks(pages, chunk_size=3, overlap=0)

    assert [chunk.text for chunk in chunks] == ["abc", "def"]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


def test_default_chunk_size_and_overlap_are_applied() -> None:
    text = "0123456789" * 100 + "x"
    pages = [PageText(document_name="paper.pdf", page_number=1, text=text)]

    chunks = split_pages_into_chunks(pages)

    assert [chunk.text for chunk in chunks] == [text[:1000], text[850:]]


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_non_positive_chunk_size_raises_value_error(chunk_size: int) -> None:
    with pytest.raises(ValueError, match="chunk_size must be greater than 0"):
        split_pages_into_chunks([], chunk_size=chunk_size, overlap=0)


def test_negative_overlap_raises_value_error() -> None:
    with pytest.raises(ValueError, match="overlap must be non-negative"):
        split_pages_into_chunks([], chunk_size=10, overlap=-1)


@pytest.mark.parametrize("overlap", [10, 11])
def test_overlap_not_smaller_than_chunk_size_raises_value_error(
    overlap: int,
) -> None:
    with pytest.raises(ValueError, match="overlap must be smaller than chunk_size"):
        split_pages_into_chunks([], chunk_size=10, overlap=overlap)


def test_empty_page_list_returns_empty_list() -> None:
    assert split_pages_into_chunks([], chunk_size=10, overlap=3) == []
