import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from research_rag import document_manager, rag_service
from research_rag.document_manager import (
    DocumentStatus,
    PersistentRagDocumentManager,
    SourceFileChangedError,
)
from research_rag.index_store import RagIndexStoreError, SQLiteRagIndexStore
from research_rag.models import Chunk, EmbeddedChunk, RagIndex
from research_rag.rag_service import answer_question_from_index


class StubClient:
    def __init__(self) -> None:
        self.embedding_calls: list[tuple[list[str], str]] = []

    def embed_texts(self, texts: list[str], model: str) -> list[list[float]]:
        self.embedding_calls.append((texts, model))
        return [[1.0, 0.0] for _ in texts]

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        model: str,
    ) -> str:
        return "Managed answer"


class RecordingBuilder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Path, ...], str, object]] = []

    def __call__(
        self,
        pdf_paths: tuple[Path, ...],
        *,
        embedding_model: str,
        client: object,
    ) -> RagIndex:
        paths = tuple(pdf_paths)
        self.calls.append((paths, embedding_model, client))
        embedded_chunks = tuple(
            EmbeddedChunk(
                chunk=Chunk(
                    document_name=path.name,
                    page_number=1,
                    chunk_index=0,
                    text=f"{path.name}: {path.read_text()}",
                ),
                embedding=(float(position + 1), 0.0),
            )
            for position, path in enumerate(paths)
        )
        return RagIndex(
            document_names=tuple(path.name for path in paths),
            embedding_model=embedding_model,
            embedded_chunks=embedded_chunks,
        )


@pytest.fixture
def store(tmp_path: Path) -> SQLiteRagIndexStore:
    result = SQLiteRagIndexStore(tmp_path / "indexes.sqlite3")
    result.initialize()
    return result


@pytest.fixture
def source_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    paths = tuple(tmp_path / name for name in ("first.pdf", "second.pdf", "third.pdf"))
    for position, path in enumerate(paths, start=1):
        path.write_text(f"source version {position}")
    return paths  # type: ignore[return-value]


@pytest.fixture
def builder(monkeypatch: pytest.MonkeyPatch) -> RecordingBuilder:
    result = RecordingBuilder()
    monkeypatch.setattr(document_manager, "build_rag_index", result)
    return result


def _manager(
    store: SQLiteRagIndexStore,
    client: StubClient | None = None,
) -> PersistentRagDocumentManager:
    return PersistentRagDocumentManager(
        store,
        client=client if client is not None else StubClient(),  # type: ignore[arg-type]
    )


def test_create_index_stores_verified_fingerprints_and_current_status(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    client = StubClient()
    manager = _manager(store, client)

    metadata = manager.create_index(
        source_paths[:2],
        embedding_model="stored-model",
    )
    inspections = manager.inspect_documents(metadata.index_id)

    assert [item.status for item in inspections] == [
        DocumentStatus.CURRENT,
        DocumentStatus.CURRENT,
    ]
    assert [item.position for item in inspections] == [0, 1]
    assert all(item.stored_content_sha256 == item.current_content_sha256 for item in inspections)
    assert all(item.stored_file_size == item.current_file_size for item in inspections)
    assert all(item.stored_mtime_ns == item.current_mtime_ns for item in inspections)
    assert all(item.indexed_at is not None for item in inspections)
    assert builder.calls == [(source_paths[:2], "stored-model", client)]


def test_create_index_persists_display_name_in_verified_save(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    manager = _manager(store)

    metadata = manager.create_index(
        source_paths[:2],
        embedding_model="stored-model",
        display_name="  研究資料 A  ",
    )

    assert metadata.display_name == "研究資料 A"
    assert store.get_index_metadata(metadata.index_id).display_name == (
        "研究資料 A"
    )


def test_create_aborts_without_saving_when_source_changes_during_build(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_builder = RecordingBuilder()

    def changing_builder(*args: Any, **kwargs: Any) -> RagIndex:
        result = original_builder(*args, **kwargs)
        source_paths[0].write_text("changed during indexing")
        return result

    monkeypatch.setattr(document_manager, "build_rag_index", changing_builder)

    with pytest.raises(SourceFileChangedError, match="changed while it was being indexed"):
        _manager(store).create_index(
            (source_paths[0],),
            embedding_model="stored-model",
        )

    assert store.list_indexes() == ()


def test_inspect_distinguishes_current_modified_missing_and_unknown(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    manager = _manager(store)
    managed = manager.create_index(source_paths, embedding_model="stored-model")

    unchanged_stat = source_paths[0].stat()
    os.utime(
        source_paths[0],
        ns=(unchanged_stat.st_atime_ns, unchanged_stat.st_mtime_ns + 1_000_000),
    )
    source_paths[1].write_text("different content")
    source_paths[2].unlink()

    statuses = manager.inspect_documents(managed.index_id)

    assert [item.status for item in statuses] == [
        DocumentStatus.CURRENT,
        DocumentStatus.MODIFIED,
        DocumentStatus.MISSING,
    ]
    assert statuses[0].stored_mtime_ns != statuses[0].current_mtime_ns
    assert statuses[0].stored_content_sha256 == statuses[0].current_content_sha256
    assert statuses[1].stored_content_sha256 != statuses[1].current_content_sha256
    assert statuses[2].current_content_sha256 is None

    legacy_index = RecordingBuilder()(
        (source_paths[0],),
        embedding_model="stored-model",
        client=object(),
    )
    legacy = store.save_index(legacy_index, (source_paths[0],))
    unknown = manager.inspect_documents(legacy.index_id)
    assert unknown[0].status is DocumentStatus.UNKNOWN
    assert unknown[0].stored_content_sha256 is None
    assert unknown[0].current_content_sha256 is not None


def test_inspect_hashes_each_source_once_and_runs_no_document_or_ollama_work(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    metadata = manager.create_index(source_paths[:2], embedding_model="stored-model")
    original_fingerprint = document_manager.fingerprint_source_file
    calls: list[Path] = []

    def recording_fingerprint(path: Path):  # type: ignore[no-untyped-def]
        calls.append(path)
        return original_fingerprint(path)

    def unexpected(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("document processing must not run during inspection")

    monkeypatch.setattr(document_manager, "fingerprint_source_file", recording_fingerprint)
    monkeypatch.setattr(document_manager, "build_rag_index", unexpected)
    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected)
    monkeypatch.setattr(rag_service, "embed_chunks", unexpected)

    statuses = manager.inspect_documents(metadata.index_id)

    assert len(statuses) == 2
    assert calls == list(source_paths[:2])


def test_add_processes_only_new_document_and_preserves_existing_ids(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    client = StubClient()
    manager = _manager(store, client)
    created = manager.create_index(source_paths[:2], embedding_model="stored-model")
    prior_ids = tuple(document.document_id for document in created.documents)
    builder.calls.clear()

    added = manager.add_document(created.index_id, source_paths[2])
    after = store.get_index_metadata(created.index_id)
    loaded = store.load_index(created.index_id)

    assert added.document_id not in prior_ids
    assert tuple(document.document_id for document in after.documents[:2]) == prior_ids
    assert [document.position for document in after.documents] == [0, 1, 2]
    assert loaded.document_names == ("first.pdf", "second.pdf", "third.pdf")
    assert [item.chunk.document_name for item in loaded.embedded_chunks] == [
        "first.pdf",
        "second.pdf",
        "third.pdf",
    ]
    assert builder.calls == [((source_paths[2],), "stored-model", client)]


def test_duplicate_basename_add_fails_before_build_and_keeps_index(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    tmp_path: Path,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    duplicate = tmp_path / "other" / source_paths[0].name
    duplicate.parent.mkdir()
    duplicate.write_text("other source")
    original = store.load_index(created.index_id)
    builder.calls.clear()

    with pytest.raises(ValueError, match="already exists"):
        manager.add_document(created.index_id, duplicate)

    assert builder.calls == []
    assert store.load_index(created.index_id) == original


def test_failed_add_keeps_previous_index_usable(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    original = store.load_index(created.index_id)

    def fail_build(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Ollama failed")

    monkeypatch.setattr(document_manager, "build_rag_index", fail_build)

    with pytest.raises(RuntimeError, match="Ollama failed"):
        manager.add_document(created.index_id, source_paths[1])

    assert store.load_index(created.index_id) == original


def test_failed_add_transaction_rolls_back_document_and_chunks(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    original = store.load_index(created.index_id)
    original_metadata = store.get_index_metadata(created.index_id)

    def fail_insert(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.IntegrityError("simulated append failure")

    monkeypatch.setattr(store, "_insert_document_chunks", fail_insert)

    with pytest.raises(RagIndexStoreError, match="Failed to append"):
        manager.add_document(created.index_id, source_paths[1])

    assert store.load_index(created.index_id) == original
    assert store.get_index_metadata(created.index_id) == original_metadata


def test_remove_only_selected_document_compacts_order_and_preserves_source(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    manager = _manager(store)
    created = manager.create_index(source_paths, embedding_model="stored-model")
    removed_id = created.documents[1].document_id
    retained_ids = (created.documents[0].document_id, created.documents[2].document_id)

    removed = manager.remove_document(created.index_id, removed_id)
    after = store.get_index_metadata(created.index_id)
    loaded = store.load_index(created.index_id)

    assert removed.document_id == removed_id
    assert tuple(document.document_id for document in after.documents) == retained_ids
    assert [document.position for document in after.documents] == [0, 1]
    assert loaded.document_names == ("first.pdf", "third.pdf")
    assert [item.chunk.document_name for item in loaded.embedded_chunks] == [
        "first.pdf",
        "third.pdf",
    ]
    assert source_paths[1].exists()
    assert created.index_id == after.index_id


def test_remove_rejects_last_searchable_document(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")

    with pytest.raises(ValueError, match="last searchable document"):
        manager.remove_document(created.index_id, created.documents[0].document_id)

    assert store.load_index(created.index_id).document_names == ("first.pdf",)


def test_failed_remove_transaction_keeps_previous_index(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index(source_paths[:2], embedding_model="stored-model")
    original = store.load_index(created.index_id)

    def fail_renumber(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.IntegrityError("simulated remove failure")

    monkeypatch.setattr(store, "_renumber_chunk_positions", fail_renumber)

    with pytest.raises(RagIndexStoreError, match="Failed to remove"):
        manager.remove_document(created.index_id, created.documents[0].document_id)

    assert store.load_index(created.index_id) == original


def test_reindex_replaces_only_selected_document_and_preserves_identity(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    client = StubClient()
    manager = _manager(store, client)
    created = manager.create_index(source_paths[:2], embedding_model="stored-model")
    before = store.load_index(created.index_id)
    target = created.documents[0]
    unchanged = created.documents[1]
    source_paths[0].write_text("replacement content")
    builder.calls.clear()

    updated = manager.reindex_document(created.index_id, target.document_id)
    after_metadata = store.get_index_metadata(created.index_id)
    after = store.load_index(created.index_id)

    assert updated.document_id == target.document_id
    assert updated.position == target.position
    assert after_metadata.index_id == created.index_id
    assert after_metadata.documents[1].document_id == unchanged.document_id
    assert after.embedded_chunks[1] == before.embedded_chunks[1]
    assert "replacement content" in after.embedded_chunks[0].chunk.text
    assert builder.calls == [((source_paths[0],), "stored-model", client)]
    assert manager.inspect_documents(created.index_id)[0].status is DocumentStatus.CURRENT


def test_missing_source_reindex_fails_before_build(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    source_paths[0].unlink()
    builder.calls.clear()

    with pytest.raises(FileNotFoundError, match="does not exist"):
        manager.reindex_document(created.index_id, created.documents[0].document_id)

    assert builder.calls == []


def test_changed_during_reindex_keeps_old_chunks_and_fingerprint(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    old_index = store.load_index(created.index_id)
    old_document = store.get_index_metadata(created.index_id).documents[0]
    original_builder = RecordingBuilder()

    def changing_builder(*args: Any, **kwargs: Any) -> RagIndex:
        result = original_builder(*args, **kwargs)
        source_paths[0].write_text("changed after document embedding")
        return result

    monkeypatch.setattr(document_manager, "build_rag_index", changing_builder)

    with pytest.raises(SourceFileChangedError, match="changed while it was being indexed"):
        manager.reindex_document(created.index_id, old_document.document_id)

    assert store.load_index(created.index_id) == old_index
    assert store.get_index_metadata(created.index_id).documents[0] == old_document


def test_failed_reindex_transaction_keeps_old_index(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index((source_paths[0],), embedding_model="stored-model")
    original = store.load_index(created.index_id)
    source_paths[0].write_text("replacement")

    def fail_renumber(*args: Any, **kwargs: Any) -> None:
        raise sqlite3.IntegrityError("simulated reindex failure")

    monkeypatch.setattr(store, "_renumber_chunk_positions", fail_renumber)

    with pytest.raises(RagIndexStoreError, match="Failed to reindex"):
        manager.reindex_document(created.index_id, created.documents[0].document_id)

    assert store.load_index(created.index_id) == original


def test_loaded_index_after_mutations_can_answer_without_document_processing(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, Path, Path],
    builder: RecordingBuilder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(store)
    created = manager.create_index(source_paths[:2], embedding_model="stored-model")
    manager.add_document(created.index_id, source_paths[2])
    manager.remove_document(created.index_id, created.documents[1].document_id)
    source_paths[0].write_text("reindexed answer source")
    manager.reindex_document(created.index_id, created.documents[0].document_id)
    reopened = SQLiteRagIndexStore(store.db_path)
    reopened.initialize()
    loaded = reopened.load_index(created.index_id)

    def unexpected(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("document processing must not run while answering")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected)
    monkeypatch.setattr(rag_service, "split_pages_into_chunks", unexpected)
    monkeypatch.setattr(rag_service, "embed_chunks", unexpected)
    answer_client = StubClient()

    answer = answer_question_from_index(
        loaded,
        "Question",
        generation_model="generation-model",
        top_k=1,
        client=answer_client,  # type: ignore[arg-type]
    )

    assert answer.text == "Managed answer"
    assert loaded.document_names == ("first.pdf", "third.pdf")
    assert answer_client.embedding_calls == [(["Question"], "stored-model")]
