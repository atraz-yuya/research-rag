import pytest

from research_rag.experimental_chunker_v2 import (
    split_pages_into_strict_heading_aware_chunks,
)
from research_rag.experimental_chunker_v3 import (
    split_pages_into_heading_context_chunks,
)
from research_rag.models import PageText


def make_page(
    text: str,
    *,
    page_number: int = 1,
) -> PageText:
    return PageText("paper.pdf", page_number, text)


def test_first_section_chunk_is_identical_to_candidate_v2() -> None:
    pages = [make_page("4 Data\nabcdefghijklmnopqrstuvwxyz")]

    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=15,
        overlap=3,
    )
    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=15,
        overlap=3,
    )

    assert candidate_v3[0] == candidate_v2[0]


def test_same_line_heading_is_prepended_to_continuation_chunks() -> None:
    pages = [make_page("4 Data\nabcdefghijklmnopqrstuvwxyz")]
    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=15,
        overlap=3,
    )

    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=15,
        overlap=3,
    )

    assert len(candidate_v3) == len(candidate_v2)
    assert [chunk.text for chunk in candidate_v3[1:]] == [
        f"4 Data\n{chunk.text}" for chunk in candidate_v2[1:]
    ]


def test_split_heading_is_prepended_to_continuation_chunks() -> None:
    pages = [
        make_page(
            "4.2\nData\nThe evaluation compares two data sets. "
            "Additional experimental details follow."
        )
    ]
    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=35,
        overlap=5,
    )

    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=35,
        overlap=5,
    )

    assert candidate_v3[0] == candidate_v2[0]
    assert candidate_v3[1].text == f"4.2\nData\n{candidate_v2[1].text}"


def test_heading_prefix_does_not_shrink_or_shift_body_windows() -> None:
    pages = [make_page("5 Results\nabcdefghijklmnopqrstuvwxyz")]
    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=15,
        overlap=4,
    )

    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=15,
        overlap=4,
    )

    prefix = "5 Results\n"
    assert candidate_v3[1].text.removeprefix(prefix) == candidate_v2[1].text
    assert len(candidate_v3[1].text) == len(candidate_v2[1].text) + len(prefix)
    assert len(candidate_v3[1].text) > 15


def test_heading_is_not_duplicated_when_body_window_already_has_it() -> None:
    pages = [make_page("3 Methods\nabcde3 Methods\nuvwxyzabcdefgh")]
    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=18,
        overlap=3,
    )

    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=18,
        overlap=3,
    )

    assert candidate_v2[1].text.startswith("3 Methods\n")
    assert candidate_v3[1].text == candidate_v2[1].text
    assert not candidate_v3[1].text.startswith("3 Methods\n3 Methods\n")


def test_text_without_detected_heading_matches_candidate_v2() -> None:
    pages = [make_page("abcdefghijklmnopqrstuvwxyz")]

    candidate_v2 = split_pages_into_strict_heading_aware_chunks(
        pages,
        chunk_size=10,
        overlap=3,
    )
    candidate_v3 = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=10,
        overlap=3,
    )

    assert candidate_v3 == candidate_v2


def test_each_section_uses_its_own_heading() -> None:
    pages = [
        make_page(
            "3 Methods\nabcdefghijklmnopqrstuv\n"
            "4 Results\nwxyzabcdefghijklmnopqr"
        )
    ]

    chunks = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=16,
        overlap=3,
    )

    methods_chunks = [chunk for chunk in chunks if "3 Methods" in chunk.text]
    results_chunks = [chunk for chunk in chunks if "4 Results" in chunk.text]
    assert len(methods_chunks) >= 2
    assert len(results_chunks) >= 2
    assert all("4 Results" not in chunk.text for chunk in methods_chunks)
    assert all("3 Methods" not in chunk.text for chunk in results_chunks)


def test_heading_context_does_not_propagate_across_pages() -> None:
    pages = [
        make_page(
            "4 Data\nabcdefghijklmnopqrstuvwxyz",
            page_number=1,
        ),
        make_page("secondpageabcdefghijklmnop", page_number=2),
    ]

    chunks = split_pages_into_heading_context_chunks(
        pages,
        chunk_size=14,
        overlap=3,
    )

    page_two_chunks = [chunk for chunk in chunks if chunk.page_number == 2]
    assert page_two_chunks
    assert all("4 Data" not in chunk.text for chunk in page_two_chunks)
    assert [chunk.chunk_index for chunk in page_two_chunks] == list(
        range(len(page_two_chunks))
    )


def test_blank_page_is_skipped() -> None:
    chunks = split_pages_into_heading_context_chunks(
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
        split_pages_into_heading_context_chunks(
            [],
            chunk_size=chunk_size,
            overlap=overlap,
        )
