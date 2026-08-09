from pathlib import Path
from typing import Any

import pytest

from research_rag import gui_service
from research_rag.document_manager import DocumentInspection, DocumentStatus
from research_rag.gui_service import RagGuiService, format_corpus_label
from research_rag.index_store import (
    StoredDocumentMetadata,
    StoredRagIndexMetadata,
)
from research_rag.models import Chunk, RagAnswer, RagIndex, SearchResult


def make_document(
    name: str = "paper.pdf",
    *,
    document_id: str = "document-id",
    position: int = 0,
) -> StoredDocumentMetadata:
    return StoredDocumentMetadata(
        document_id=document_id,
        document_name=name,
        source_path=Path("/sources") / name,
        position=position,
    )


def make_metadata(
    index_id: str = "index-id",
    documents: tuple[StoredDocumentMetadata, ...] | None = None,
) -> StoredRagIndexMetadata:
    return StoredRagIndexMetadata(
        index_id=index_id,
        embedding_model="stored-embedding-model",
        created_at="2026-08-09T00:00:00Z",
        documents=documents if documents is not None else (make_document(),),
        chunk_count=1,
    )


class StubStore:
    def __init__(self) -> None:
        self.initialized = 0
        self.list_result = (make_metadata(),)
        self.list_calls = 0
        self.load_calls: list[str] = []
        self.loaded_index = RagIndex(
            document_names=("paper.pdf",),
            embedding_model="stored-embedding-model",
            embedded_chunks=(),
        )

    def initialize(self) -> None:
        self.initialized += 1

    def list_indexes(self) -> tuple[StoredRagIndexMetadata, ...]:
        self.list_calls += 1
        return self.list_result

    def load_index(self, index_id: str) -> RagIndex:
        self.load_calls.append(index_id)
        return self.loaded_index


class StubManager:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.inspections = (
            DocumentInspection(
                index_id="index-id",
                document_id="document-id",
                document_name="paper.pdf",
                source_path=Path("/sources/paper.pdf"),
                position=0,
                status=DocumentStatus.CURRENT,
                stored_content_sha256="a" * 64,
                current_content_sha256="a" * 64,
                stored_file_size=10,
                current_file_size=10,
                stored_mtime_ns=20,
                current_mtime_ns=20,
                indexed_at="2026-08-09T00:00:00Z",
            ),
        )

    def inspect_documents(self, index_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("inspect", index_id))
        return self.inspections

    def create_index(
        self,
        pdf_paths: tuple[Path, ...],
        *,
        embedding_model: str,
    ) -> StoredRagIndexMetadata:
        self.calls.append(("create", tuple(pdf_paths), embedding_model))
        return make_metadata("created-id")

    def add_document(self, index_id: str, pdf_path: Path):  # type: ignore[no-untyped-def]
        self.calls.append(("add", index_id, pdf_path))
        return make_document(pdf_path.name, document_id="added-id")

    def remove_document(self, index_id: str, document_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("remove", index_id, document_id))
        return make_document(document_id=document_id)

    def reindex_document(self, index_id: str, document_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("reindex", index_id, document_id))
        return make_document(document_id=document_id)


def make_service(
    store: StubStore,
    manager: StubManager,
    *,
    client: object | None = None,
) -> RagGuiService:
    return RagGuiService(
        store,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
    )


def test_service_initializes_and_lists_lightweight_corpus_metadata() -> None:
    store = StubStore()
    service = make_service(store, StubManager())

    service.initialize()
    corpora = service.list_corpora()

    assert store.initialized == 1
    assert store.list_calls == 1
    assert corpora == store.list_result
    assert store.load_calls == []


def test_service_inspects_and_creates_through_persistent_manager() -> None:
    store = StubStore()
    manager = StubManager()
    service = make_service(store, manager)
    paths = (Path("first.pdf"), Path("second.pdf"))

    inspections = service.inspect_documents("index-id")
    created = service.create_corpus(paths)

    assert inspections == manager.inspections
    assert created.index_id == "created-id"
    assert manager.calls == [
        ("inspect", "index-id"),
        ("create", paths, "qwen3-embedding:0.6b"),
    ]


def test_service_delegates_add_remove_and_reindex_with_durable_ids() -> None:
    store = StubStore()
    manager = StubManager()
    service = make_service(store, manager)

    service.add_document("index-id", Path("new.pdf"))
    service.remove_document("index-id", "document-id")
    service.reindex_document("index-id", "document-id")

    assert manager.calls == [
        ("add", "index-id", Path("new.pdf")),
        ("remove", "index-id", "document-id"),
        ("reindex", "index-id", "document-id"),
    ]


def test_service_loads_selected_index_and_uses_shared_answer_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StubStore()
    manager = StubManager()
    client = object()
    service = make_service(store, manager, client=client)
    source = SearchResult(Chunk("paper.pdf", 3, 0, "Source"), 0.9, 1)
    expected = RagAnswer("Answer", (source,))
    calls: list[tuple[Any, ...]] = []

    def fake_answer(
        index: RagIndex,
        question: str,
        *,
        generation_model: str,
        top_k: int,
        client: object,
    ) -> RagAnswer:
        calls.append((index, question, generation_model, top_k, client))
        return expected

    monkeypatch.setattr(gui_service, "answer_question_from_index", fake_answer)

    result = service.answer("index-id", "  Question?  ")

    assert result == expected
    assert store.load_calls == ["index-id"]
    assert calls == [
        (
            store.loaded_index,
            "Question?",
            "qwen3:4b-instruct",
            3,
            client,
        )
    ]


def test_service_rejects_empty_question_before_loading_index() -> None:
    store = StubStore()
    service = make_service(store, StubManager())

    with pytest.raises(ValueError, match="question must not be empty"):
        service.answer("index-id", "  \n ")

    assert store.load_calls == []


def test_corpus_label_hides_uuid_and_summarizes_document_count() -> None:
    one = make_metadata("secret-uuid", (make_document("first.pdf"),))
    many = make_metadata(
        "another-secret-uuid",
        (
            make_document("first.pdf", document_id="one", position=0),
            make_document("second.pdf", document_id="two", position=1),
            make_document("third.pdf", document_id="three", position=2),
        ),
    )

    assert format_corpus_label(one) == "first.pdf"
    assert format_corpus_label(many) == "first.pdf + 2件"
    assert "secret-uuid" not in format_corpus_label(one)
