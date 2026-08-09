from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from research_rag import gui_service
from research_rag.document_manager import DocumentInspection, DocumentStatus
from research_rag.gui_service import RagGuiService, format_corpus_label
from research_rag.gui_settings import GuiRuntimeSettings
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
    *,
    display_name: str | None = None,
) -> StoredRagIndexMetadata:
    return StoredRagIndexMetadata(
        index_id=index_id,
        embedding_model="stored-embedding-model",
        created_at="2026-08-09T00:00:00Z",
        documents=documents if documents is not None else (make_document(),),
        chunk_count=1,
        display_name=display_name,
    )


class StubStore:
    def __init__(self) -> None:
        self.initialized = 0
        self.list_result = (make_metadata(),)
        self.list_calls = 0
        self.load_calls: list[str] = []
        self.rename_calls: list[tuple[str, str]] = []
        self.delete_calls: list[str] = []
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

    def rename_index(
        self,
        index_id: str,
        display_name: str,
    ) -> StoredRagIndexMetadata:
        self.rename_calls.append((index_id, display_name))
        return make_metadata(index_id, display_name=display_name)

    def delete_index(self, index_id: str) -> bool:
        self.delete_calls.append(index_id)
        return True


class StubManager:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.client: object | None = None
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
        display_name: str | None = None,
    ) -> StoredRagIndexMetadata:
        self.calls.append(
            ("create", tuple(pdf_paths), embedding_model, display_name)
        )
        return make_metadata("created-id", display_name=display_name)

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
    runtime_settings: GuiRuntimeSettings | None = None,
    client_factory: Callable[[str], object] | None = None,
) -> RagGuiService:
    return RagGuiService(
        store,  # type: ignore[arg-type]
        manager=manager,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        runtime_settings=runtime_settings,
        client_factory=client_factory,  # type: ignore[arg-type]
    )


class FakeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


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
    created = service.create_corpus(paths, display_name="研究資料 A")

    assert inspections == manager.inspections
    assert created.index_id == "created-id"
    assert manager.calls == [
        ("inspect", "index-id"),
        ("create", paths, "qwen3-embedding:0.6b", "研究資料 A"),
    ]
    assert created.display_name == "研究資料 A"


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


def test_service_delegates_corpus_rename_and_delete_to_store() -> None:
    store = StubStore()
    service = make_service(store, StubManager())

    renamed = service.rename_corpus("index-id", "研究資料 B")
    deleted = service.delete_corpus("index-id")

    assert renamed.display_name == "研究資料 B"
    assert deleted is True
    assert store.rename_calls == [("index-id", "研究資料 B")]
    assert store.delete_calls == ["index-id"]


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


def test_service_exposes_and_applies_immutable_runtime_settings() -> None:
    store = StubStore()
    manager = StubManager()
    client = FakeClient("http://old.example.test:11434")
    initial = GuiRuntimeSettings(
        embedding_model="embedding-old",
        generation_model="generation-old",
        top_k=3,
        ollama_base_url=client.base_url,
    )
    service = make_service(
        store,
        manager,
        client=client,
        runtime_settings=initial,
    )
    changed = GuiRuntimeSettings(
        embedding_model=" embedding-new ",
        generation_model=" generation-new ",
        top_k=9,
        ollama_base_url="http://old.example.test:11434/",
    )

    applied = service.apply_runtime_settings(changed)

    assert applied == GuiRuntimeSettings(
        embedding_model="embedding-new",
        generation_model="generation-new",
        top_k=9,
        ollama_base_url="http://old.example.test:11434",
    )
    assert service.runtime_settings == applied
    assert service.client is client
    assert manager.client is client


def test_embedding_setting_only_changes_future_corpus_creation() -> None:
    store = StubStore()
    manager = StubManager()
    service = make_service(store, manager)

    service.apply_runtime_settings(
        GuiRuntimeSettings(
            embedding_model="new-corpus-embedding",
            generation_model="generation",
            top_k=3,
            ollama_base_url="http://localhost:11434",
        )
    )
    service.create_corpus((Path("new.pdf"),))
    service.add_document("index-id", Path("added.pdf"))
    service.reindex_document("index-id", "document-id")

    assert manager.calls == [
        (
            "create",
            (Path("new.pdf"),),
            "new-corpus-embedding",
            None,
        ),
        ("add", "index-id", Path("added.pdf")),
        ("reindex", "index-id", "document-id"),
    ]
    assert store.list_result[0].embedding_model == "stored-embedding-model"


def test_generation_model_and_top_k_apply_to_subsequent_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = StubStore()
    manager = StubManager()
    client = FakeClient("http://localhost:11434")
    service = make_service(store, manager, client=client)
    calls: list[tuple[str, int, str, object]] = []

    def fake_answer(
        index: RagIndex,
        question: str,
        *,
        generation_model: str,
        top_k: int,
        client: object,
    ) -> RagAnswer:
        calls.append(
            (generation_model, top_k, index.embedding_model, client)
        )
        return RagAnswer("answer", ())

    monkeypatch.setattr(gui_service, "answer_question_from_index", fake_answer)
    service.apply_runtime_settings(
        GuiRuntimeSettings(
            embedding_model="future-only-model",
            generation_model="new-generation",
            top_k=8,
            ollama_base_url=client.base_url,
        )
    )

    service.answer("index-id", "question")

    assert calls == [
        ("new-generation", 8, "stored-embedding-model", client)
    ]


def test_ollama_url_rebuilds_one_shared_client_without_network_call() -> None:
    store = StubStore()
    manager = StubManager()
    old_client = FakeClient("http://localhost:11434")
    factory_calls: list[str] = []

    def client_factory(base_url: str) -> object:
        factory_calls.append(base_url)
        return FakeClient(base_url)

    service = make_service(
        store,
        manager,
        client=old_client,
        client_factory=client_factory,
    )

    service.apply_runtime_settings(
        GuiRuntimeSettings(
            embedding_model="embedding",
            generation_model="generation",
            top_k=3,
            ollama_base_url="https://remote.example.test:11434/",
        )
    )

    assert factory_calls == ["https://remote.example.test:11434"]
    assert service.client is manager.client
    assert service.client is not old_client
    assert service.client.base_url == "https://remote.example.test:11434"


def test_restore_runtime_settings_restores_exact_prior_shared_client() -> None:
    store = StubStore()
    manager = StubManager()
    old_client = FakeClient("http://localhost:11434")
    initial = GuiRuntimeSettings(
        "embedding-old",
        "generation-old",
        3,
        old_client.base_url,
    )
    service = make_service(
        store,
        manager,
        client=old_client,
        runtime_settings=initial,
        client_factory=FakeClient,
    )
    service.apply_runtime_settings(
        GuiRuntimeSettings(
            "embedding-new",
            "generation-new",
            6,
            "http://new.example.test:11434",
        )
    )

    service.restore_runtime_settings(initial, old_client)  # type: ignore[arg-type]

    assert service.runtime_settings == initial
    assert service.client is old_client
    assert manager.client is old_client


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


def test_corpus_label_prefers_display_name_and_unnamed_uses_fallback() -> None:
    named = make_metadata(
        "secret-uuid",
        (make_document("first.pdf"),),
        display_name="卒業研究 関連論文",
    )
    unnamed = make_metadata(
        "legacy-uuid",
        (
            make_document("first.pdf", document_id="one", position=0),
            make_document("second.pdf", document_id="two", position=1),
        ),
    )

    assert format_corpus_label(named) == "卒業研究 関連論文"
    assert format_corpus_label(unnamed) == "first.pdf + 1件"
