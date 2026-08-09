import sqlite3
import struct
from pathlib import Path
from uuid import UUID

import pytest

from research_rag import index_store, rag_service
from research_rag.index_store import (
    SCHEMA_VERSION,
    RagIndexStoreError,
    SQLiteRagIndexStore,
)
from research_rag.models import Chunk, EmbeddedChunk, RagIndex
from research_rag.rag_service import answer_question_from_index


@pytest.fixture
def store(tmp_path: Path) -> SQLiteRagIndexStore:
    index_store = SQLiteRagIndexStore(tmp_path / "data" / "indexes.sqlite3")
    index_store.initialize()
    return index_store


def make_index() -> RagIndex:
    return RagIndex(
        document_names=("first.pdf", "empty.pdf", "second.pdf"),
        embedding_model="embedding-model",
        embedded_chunks=(
            EmbeddedChunk(
                Chunk("second.pdf", 4, 0, "Second document source"),
                (0.25, -3.5),
            ),
            EmbeddedChunk(
                Chunk("first.pdf", 1, 2, "First document source"),
                (1.23456789012345, 0.0),
            ),
        ),
    )


def make_source_paths(tmp_path: Path) -> tuple[Path, ...]:
    return (
        tmp_path / "sources" / "first.pdf",
        tmp_path / "sources" / "empty.pdf",
        tmp_path / "other" / "second.pdf",
    )


def table_count(db_path: Path, table_name: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
    assert row is not None
    return row[0]


def test_initialize_creates_schema_version_one_and_is_idempotent(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "nested" / "indexes.sqlite3"
    index_store = SQLiteRagIndexStore(db_path)

    index_store.initialize()
    index_store.initialize()

    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert version == (str(SCHEMA_VERSION),)
    assert {
        "store_metadata",
        "rag_indexes",
        "rag_documents",
        "rag_chunks",
    } <= tables


def test_initialize_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    db_path = tmp_path / "indexes.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE store_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO store_metadata (key, value) VALUES (?, ?)",
            ("schema_version", "99"),
        )

    with pytest.raises(
        RagIndexStoreError,
        match=r"Unsupported.*99.*expected 1",
    ):
        SQLiteRagIndexStore(db_path).initialize()


def test_store_connections_enable_foreign_keys(
    store: SQLiteRagIndexStore,
) -> None:
    connection = store._open_connection()
    try:
        row = connection.execute("PRAGMA foreign_keys").fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == 1


def test_save_returns_uuid_metadata_and_persists_all_documents(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    source_paths = make_source_paths(tmp_path)

    metadata = store.save_index(make_index(), source_paths)

    assert str(UUID(metadata.index_id)) == metadata.index_id
    assert metadata.embedding_model == "embedding-model"
    assert metadata.created_at.endswith("Z")
    assert metadata.chunk_count == 2
    assert [document.position for document in metadata.documents] == [0, 1, 2]
    assert [document.document_name for document in metadata.documents] == [
        "first.pdf",
        "empty.pdf",
        "second.pdf",
    ]
    assert [document.source_path for document in metadata.documents] == [
        path.expanduser().resolve(strict=False) for path in source_paths
    ]
    assert len({document.document_id for document in metadata.documents}) == 3
    for document in metadata.documents:
        assert str(UUID(document.document_id)) == document.document_id

    with sqlite3.connect(store.db_path) as connection:
        rows = connection.execute(
            """
            SELECT position, document_name, source_path
            FROM rag_documents
            WHERE index_id = ?
            ORDER BY position
            """,
            (metadata.index_id,),
        ).fetchall()
    assert rows == [
        (0, "first.pdf", str(source_paths[0].resolve(strict=False))),
        (1, "empty.pdf", str(source_paths[1].resolve(strict=False))),
        (2, "second.pdf", str(source_paths[2].resolve(strict=False))),
    ]


@pytest.mark.parametrize(
    ("source_paths", "message"),
    [
        ((), "source_paths must not be empty"),
        ((Path("first.pdf"),), "count must match"),
        (
            (
                Path("wrong.pdf"),
                Path("empty.pdf"),
                Path("second.pdf"),
            ),
            "basename must match",
        ),
    ],
)
def test_save_rejects_invalid_source_paths_before_writing(
    store: SQLiteRagIndexStore,
    source_paths: tuple[Path, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        store.save_index(make_index(), source_paths)

    assert table_count(store.db_path, "rag_indexes") == 0


def test_save_rejects_duplicate_document_names_before_writing(
    store: SQLiteRagIndexStore,
) -> None:
    embedded_chunk = EmbeddedChunk(
        Chunk("paper.pdf", 1, 0, "Text"),
        (1.0,),
    )
    invalid_index = RagIndex(
        ("paper.pdf", "paper.pdf"),
        "embedding-model",
        (embedded_chunk,),
    )

    with pytest.raises(ValueError, match="document names must be unique"):
        store.save_index(
            invalid_index,
            [Path("one/paper.pdf"), Path("two/paper.pdf")],
        )

    assert table_count(store.db_path, "rag_indexes") == 0


def test_save_rejects_nonfinite_embedding_before_writing(
    store: SQLiteRagIndexStore,
) -> None:
    invalid_index = RagIndex(
        ("paper.pdf",),
        "embedding-model",
        (
            EmbeddedChunk(
                Chunk("paper.pdf", 1, 0, "Text"),
                (float("inf"),),
            ),
        ),
    )

    with pytest.raises(ValueError, match="only finite values"):
        store.save_index(invalid_index, [Path("paper.pdf")])

    assert table_count(store.db_path, "rag_indexes") == 0


def test_save_load_round_trip_preserves_index_and_float64_encoding(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    original = make_index()
    metadata = store.save_index(original, make_source_paths(tmp_path))

    loaded = store.load_index(metadata.index_id)

    assert loaded == original
    assert [chunk.chunk.document_name for chunk in loaded.embedded_chunks] == [
        "second.pdf",
        "first.pdf",
    ]
    assert loaded.embedded_chunks[0].chunk.page_number == 4
    assert loaded.embedded_chunks[1].chunk.chunk_index == 2
    assert loaded.embedding_model == original.embedding_model
    assert loaded.embedded_chunks[1].embedding[0] == 1.23456789012345

    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            """
            SELECT embedding_dimension, embedding
            FROM rag_chunks
            WHERE index_id = ? AND position = 0
            """,
            (metadata.index_id,),
        ).fetchone()
    assert row == (2, struct.pack("<2d", 0.25, -3.5))


@pytest.mark.parametrize(
    ("update_sql", "parameters", "message"),
    [
        (
            "UPDATE rag_chunks SET embedding_dimension = 0 WHERE index_id = ?",
            (),
            "invalid dimension",
        ),
        (
            "UPDATE rag_chunks SET embedding = ? WHERE index_id = ?",
            (b"\x00",),
            "BLOB length",
        ),
        (
            """
            UPDATE rag_chunks
            SET embedding_dimension = 1, embedding = ?
            WHERE index_id = ?
            """,
            (struct.pack("<d", float("nan")),),
            "non-finite",
        ),
    ],
)
def test_load_rejects_corrupt_embeddings(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    update_sql: str,
    parameters: tuple[object, ...],
    message: str,
) -> None:
    metadata = store.save_index(make_index(), make_source_paths(tmp_path))
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            update_sql,
            (*parameters, metadata.index_id),
        )

    with pytest.raises(RagIndexStoreError, match=message):
        store.load_index(metadata.index_id)


def test_load_works_without_source_files_and_without_document_processing(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_paths = make_source_paths(tmp_path)
    for source_path in source_paths:
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"temporary source")
    metadata = store.save_index(make_index(), source_paths)
    for source_path in source_paths:
        source_path.unlink()

    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("document processing must not run during load")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_call)
    monkeypatch.setattr(rag_service, "embed_chunks", unexpected_call)

    loaded = SQLiteRagIndexStore(store.db_path).load_index(metadata.index_id)

    assert loaded == make_index()
    assert all(not source_path.exists() for source_path in source_paths)


def test_loaded_index_can_answer_without_rebuilding_documents(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = store.save_index(make_index(), make_source_paths(tmp_path))
    loaded = SQLiteRagIndexStore(store.db_path).load_index(metadata.index_id)

    class StubClient:
        def __init__(self) -> None:
            self.embedding_calls: list[tuple[list[str], str]] = []
            self.generation_calls = 0

        def embed_texts(
            self,
            texts: list[str],
            model: str,
        ) -> list[list[float]]:
            self.embedding_calls.append((texts, model))
            return [[1.0, 0.0]]

        def generate_chat(
            self,
            messages: list[dict[str, str]],
            model: str,
        ) -> str:
            self.generation_calls += 1
            return "Grounded answer"

    def unexpected_call(*args: object, **kwargs: object) -> None:
        raise AssertionError("document processing must not run while answering")

    monkeypatch.setattr(rag_service, "extract_page_texts", unexpected_call)
    monkeypatch.setattr(rag_service, "split_pages_into_chunks", unexpected_call)
    monkeypatch.setattr(rag_service, "embed_chunks", unexpected_call)
    client = StubClient()

    answer = answer_question_from_index(
        loaded,
        "Question",
        generation_model="generation-model",
        top_k=1,
        client=client,  # type: ignore[arg-type]
    )

    assert answer.text == "Grounded answer"
    assert answer.sources[0].chunk.document_name == "first.pdf"
    assert answer.sources[0].chunk.page_number == 1
    assert client.embedding_calls == [(["Question"], "embedding-model")]
    assert client.generation_calls == 1


def test_list_indexes_returns_lightweight_newest_first_metadata(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamps = iter(
        ["2026-01-01T00:00:00.000000Z", "2026-01-02T00:00:00.000000Z"]
    )
    monkeypatch.setattr(index_store, "_utc_now_iso8601", lambda: next(timestamps))
    first = store.save_index(make_index(), make_source_paths(tmp_path))
    second = store.save_index(make_index(), make_source_paths(tmp_path))

    def unexpected_deserialize(*args: object, **kwargs: object) -> None:
        raise AssertionError("list_indexes must not hydrate embeddings")

    monkeypatch.setattr(store, "_deserialize_embedding", unexpected_deserialize)

    items = store.list_indexes()

    assert first.index_id != second.index_id
    assert [item.index_id for item in items] == [second.index_id, first.index_id]
    assert all(item.chunk_count == 2 for item in items)
    assert [document.document_name for document in items[0].documents] == [
        "first.pdf",
        "empty.pdf",
        "second.pdf",
    ]


def test_delete_returns_status_cascades_rows_and_preserves_sources(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    source_paths = make_source_paths(tmp_path)
    for source_path in source_paths:
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"source remains")
    metadata = store.save_index(make_index(), source_paths)

    assert store.delete_index(metadata.index_id) is True
    assert store.delete_index(metadata.index_id) is False
    assert table_count(store.db_path, "rag_indexes") == 0
    assert table_count(store.db_path, "rag_documents") == 0
    assert table_count(store.db_path, "rag_chunks") == 0
    assert all(source_path.exists() for source_path in source_paths)


def test_failed_save_rolls_back_index_document_and_chunk_rows(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_insert_chunks(*args: object, **kwargs: object) -> None:
        raise sqlite3.IntegrityError("simulated insert failure")

    monkeypatch.setattr(store, "_insert_chunks", failing_insert_chunks)

    with pytest.raises(RagIndexStoreError, match="Failed to save"):
        store.save_index(make_index(), make_source_paths(tmp_path))

    assert table_count(store.db_path, "rag_indexes") == 0
    assert table_count(store.db_path, "rag_documents") == 0
    assert table_count(store.db_path, "rag_chunks") == 0


@pytest.mark.parametrize(
    ("index_id", "message"),
    [
        ("", "index_id must not be empty"),
        ("   \n", "index_id must not be empty"),
        ("not-a-uuid", "index_id must be a valid UUID"),
    ],
)
def test_load_and_delete_reject_invalid_index_ids_before_database_work(
    tmp_path: Path,
    index_id: str,
    message: str,
) -> None:
    uninitialized = SQLiteRagIndexStore(tmp_path / "missing" / "store.sqlite3")

    with pytest.raises(ValueError, match=message):
        uninitialized.load_index(index_id)
    with pytest.raises(ValueError, match=message):
        uninitialized.delete_index(index_id)

    assert not uninitialized.db_path.exists()


def test_load_missing_index_fails_clearly(store: SQLiteRagIndexStore) -> None:
    missing_id = str(UUID("00000000-0000-0000-0000-000000000001"))

    with pytest.raises(KeyError, match="does not exist"):
        store.load_index(missing_id)
