import pytest

from research_rag.models import Chunk, RagAnswer, SearchResult
from research_rag.rag_service import generate_answer


class StubChatClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> str:
        self.calls.append((messages, model))
        return self.response


def make_search_result(
    *,
    rank: int,
    document_name: str,
    page_number: int,
    text: str,
    score: float = 0.9,
) -> SearchResult:
    return SearchResult(
        chunk=Chunk(
            document_name=document_name,
            page_number=page_number,
            chunk_index=rank - 1,
            text=text,
        ),
        score=score,
        rank=rank,
    )


def test_generate_answer_uses_one_source_and_preserves_it() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=3,
        text="The experiment improved accuracy.",
    )
    client = StubChatClient("Accuracy improved in the experiment.")

    answer = generate_answer(
        "What improved?",
        [source],
        model="generation-model",
        client=client,
    )

    assert answer == RagAnswer(
        text="Accuracy improved in the experiment.",
        sources=(source,),
    )
    assert answer.sources[0] is source
    assert client.calls[0][1] == "generation-model"


def test_generate_answer_includes_question_and_source_details_in_prompt() -> None:
    source = make_search_result(
        rank=1,
        document_name="research-paper.pdf",
        page_number=8,
        text="Grounded source text.",
    )
    client = StubChatClient("Grounded answer")

    generate_answer(
        "What does the source say?",
        [source],
        model="generation-model",
        client=client,
    )

    messages, _ = client.calls[0]
    user_prompt = messages[1]["content"]
    assert "What does the source say?" in user_prompt
    assert "[Source 1]" in user_prompt
    assert "Rank: 1" in user_prompt
    assert "Document: research-paper.pdf" in user_prompt
    assert "Page: 8" in user_prompt
    assert "Grounded source text." in user_prompt


def test_generate_answer_instructs_model_to_use_only_sources() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    generate_answer(
        "Question",
        [source],
        model="generation-model",
        client=client,
    )

    system_prompt = client.calls[0][0][0]["content"]
    assert "only the provided source material" in system_prompt
    assert "cannot be determined" in system_prompt
    assert "Do not guess" in system_prompt
    assert "concise" in system_prompt


def test_generate_answer_orders_prompt_and_sources_by_rank() -> None:
    second = make_search_result(
        rank=2,
        document_name="paper.pdf",
        page_number=9,
        text="Second-ranked text.",
    )
    first = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=2,
        text="First-ranked text.",
    )
    client = StubChatClient("Answer")

    answer = generate_answer(
        "Question",
        [second, first],
        model="generation-model",
        client=client,
    )

    user_prompt = client.calls[0][0][1]["content"]
    assert user_prompt.index("[Source 1]") < user_prompt.index("[Source 2]")
    assert user_prompt.index("First-ranked text.") < user_prompt.index(
        "Second-ranked text."
    )
    assert answer.sources == (first, second)
    assert answer.sources[0] is first
    assert answer.sources[1] is second


@pytest.mark.parametrize("question", ["", "   \n\t"])
def test_generate_answer_rejects_empty_or_whitespace_question(
    question: str,
) -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="question must not be empty"):
        generate_answer(
            question,
            [source],
            model="generation-model",
            client=client,
        )

    assert client.calls == []


def test_generate_answer_rejects_empty_search_results() -> None:
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="no search results are available"):
        generate_answer(
            "Question",
            [],
            model="generation-model",
            client=client,
        )

    assert client.calls == []


def test_generate_answer_rejects_empty_model() -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient("Answer")

    with pytest.raises(ValueError, match="model must not be empty"):
        generate_answer("Question", [source], model="  ", client=client)

    assert client.calls == []


@pytest.mark.parametrize("response", ["", "   \n\t"])
def test_generate_answer_rejects_empty_llm_answer(response: str) -> None:
    source = make_search_result(
        rank=1,
        document_name="paper.pdf",
        page_number=1,
        text="Source text.",
    )
    client = StubChatClient(response)

    with pytest.raises(ValueError, match="LLM returned an empty answer"):
        generate_answer(
            "Question",
            [source],
            model="generation-model",
            client=client,
        )
