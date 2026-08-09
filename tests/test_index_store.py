import sqlite3
import struct
from pathlib import Path
from uuid import UUID

import pytest

from research_rag import index_store, rag_service
from research_rag.document_manager import (
    DocumentStatus,
    PersistentRagDocumentManager,
)
from research_rag.index_store import (
    SCHEMA_VERSION,
    RagIndexStoreError,
    SQLiteRagIndexStore,
    SourceFingerprint,
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


def test_initialize_creates_schema_version_three_and_is_idempotent(
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
        index_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(rag_indexes)")
        }
    assert version == (str(SCHEMA_VERSION),)
    assert {
        "store_metadata",
        "rag_indexes",
        "rag_documents",
        "rag_chunks",
    } <= tables
    assert "display_name" in index_columns


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
        match=r"Unsupported.*99.*expected 3",
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
    assert metadata.display_name is None
    assert store.get_index_metadata(metadata.index_id).display_name is None
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
        assert document.content_sha256 is None
        assert document.file_size is None
        assert document.mtime_ns is None
        assert document.indexed_at is None

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


def test_save_with_display_name_normalizes_and_persists_it_atomically(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    fingerprints = (
        SourceFingerprint("a" * 64, 10, 100),
        SourceFingerprint("b" * 64, 20, 200),
        SourceFingerprint("c" * 64, 30, 300),
    )

    metadata = store.save_verified_index(
        make_index(),
        make_source_paths(tmp_path),
        fingerprints,
        display_name="  卒業研究 関連論文  ",
    )

    assert metadata.display_name == "卒業研究 関連論文"
    assert store.get_index_metadata(metadata.index_id).display_name == (
        "卒業研究 関連論文"
    )
    assert store.list_indexes()[0].display_name == "卒業研究 関連論文"


@pytest.mark.parametrize("display_name", ["", "  \n ", "x" * 101])
def test_save_rejects_invalid_display_name_before_database_write(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    display_name: str,
) -> None:
    with pytest.raises(ValueError, match="display_name"):
        store.save_index(
            make_index(),
            make_source_paths(tmp_path),
            display_name=display_name,
        )

    assert table_count(store.db_path, "rag_indexes") == 0


def test_invalid_display_name_is_rejected_before_opening_database(
    tmp_path: Path,
) -> None:
    uninitialized = SQLiteRagIndexStore(tmp_path / "missing" / "store.sqlite3")

    with pytest.raises(ValueError, match="display_name"):
        uninitialized.save_index(
            make_index(),
            make_source_paths(tmp_path),
            display_name="   ",
        )

    assert not uninitialized.db_path.exists()


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
    original_open_connection = store._open_connection

    def open_without_embedding_access() -> sqlite3.Connection:
        connection = original_open_connection()

        def deny_embedding_reads(
            operation: int,
            table_name: str | None,
            column_name: str | None,
            database_name: str | None,
            trigger_name: str | None,
        ) -> int:
            if (
                operation == sqlite3.SQLITE_READ
                and table_name == "rag_chunks"
                and column_name == "embedding"
            ):
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(deny_embedding_reads)
        return connection

    monkeypatch.setattr(store, "_open_connection", open_without_embedding_access)

    items = store.list_indexes()

    assert first.index_id != second.index_id
    assert [item.index_id for item in items] == [second.index_id, first.index_id]
    assert all(item.chunk_count == 2 for item in items)
    assert [document.document_name for document in items[0].documents] == [
        "first.pdf",
        "empty.pdf",
        "second.pdf",
    ]


def test_rename_normalizes_name_without_changing_ids_or_embeddings(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_index = make_index()
    saved = store.save_index(original_index, make_source_paths(tmp_path))
    original_document_ids = tuple(
        document.document_id for document in saved.documents
    )
    with sqlite3.connect(store.db_path) as connection:
        original_embeddings = connection.execute(
            """
            SELECT chunk_id, embedding
            FROM rag_chunks
            WHERE index_id = ?
            ORDER BY position
            """,
            (saved.index_id,),
        ).fetchall()

    def unexpected_deserialize(*args: object, **kwargs: object) -> None:
        raise AssertionError("rename must not deserialize embeddings")

    monkeypatch.setattr(store, "_deserialize_embedding", unexpected_deserialize)
    renamed = store.rename_index(saved.index_id, "  研究資料 A  ")

    assert renamed.index_id == saved.index_id
    assert renamed.display_name == "研究資料 A"
    assert tuple(
        document.document_id for document in renamed.documents
    ) == original_document_ids
    with sqlite3.connect(store.db_path) as connection:
        renamed_embeddings = connection.execute(
            """
            SELECT chunk_id, embedding
            FROM rag_chunks
            WHERE index_id = ?
            ORDER BY position
            """,
            (saved.index_id,),
        ).fetchall()
    assert renamed_embeddings == original_embeddings


def test_rename_allows_duplicate_display_names(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    first = store.save_index(make_index(), make_source_paths(tmp_path))
    second = store.save_index(make_index(), make_source_paths(tmp_path))

    store.rename_index(first.index_id, "共通名")
    store.rename_index(second.index_id, "共通名")

    assert [item.display_name for item in store.list_indexes()] == [
        "共通名",
        "共通名",
    ]


@pytest.mark.parametrize("display_name", ["", " \n ", "名" * 101])
def test_rename_rejects_invalid_display_names(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
    display_name: str,
) -> None:
    saved = store.save_index(make_index(), make_source_paths(tmp_path))

    with pytest.raises(ValueError, match="display_name"):
        store.rename_index(saved.index_id, display_name)

    assert store.get_index_metadata(saved.index_id).display_name is None


def test_rename_missing_index_fails_clearly(
    store: SQLiteRagIndexStore,
) -> None:
    missing_id = "00000000-0000-0000-0000-000000000099"

    with pytest.raises(KeyError, match="does not exist"):
        store.rename_index(missing_id, "Missing")


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
        store.save_index(
            make_index(),
            make_source_paths(tmp_path),
            display_name="Atomic name",
        )

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
    with pytest.raises(ValueError, match=message):
        uninitialized.rename_index(index_id, "Name")

    assert not uninitialized.db_path.exists()


def test_load_missing_index_fails_clearly(store: SQLiteRagIndexStore) -> None:
    missing_id = str(UUID("00000000-0000-0000-0000-000000000001"))

    with pytest.raises(KeyError, match="does not exist"):
        store.load_index(missing_id)


def _create_schema_v1_store(
    db_path: Path,
    *,
    with_data: bool = True,
    source_path: Path = Path("/old/legacy.pdf"),
) -> RagIndex:
    index_id = "00000000-0000-0000-0000-000000000101"
    document_id = "00000000-0000-0000-0000-000000000102"
    original = RagIndex(
        document_names=("legacy.pdf",),
        embedding_model="legacy-embedding-model",
        embedded_chunks=(
            EmbeddedChunk(
                Chunk("legacy.pdf", 2, 0, "Legacy source text"),
                (0.25, -0.75),
            ),
        ),
    )
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE store_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT INTO store_metadata (key, value)
            VALUES ('schema_version', '1');
            CREATE TABLE rag_indexes (
                index_id TEXT PRIMARY KEY,
                embedding_model TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE rag_documents (
                document_id TEXT PRIMARY KEY,
                index_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                document_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                FOREIGN KEY (index_id) REFERENCES rag_indexes(index_id)
                    ON DELETE CASCADE,
                UNIQUE (index_id, position),
                UNIQUE (index_id, document_name)
            );
            CREATE TABLE rag_chunks (
                chunk_id INTEGER PRIMARY KEY,
                index_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding_dimension INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (index_id) REFERENCES rag_indexes(index_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (document_id) REFERENCES rag_documents(document_id)
                    ON DELETE CASCADE,
                UNIQUE (index_id, position)
            );
            """
        )
        if with_data:
            connection.execute(
                "INSERT INTO rag_indexes VALUES (?, ?, ?)",
                (index_id, original.embedding_model, "2026-08-01T00:00:00Z"),
            )
            connection.execute(
                "INSERT INTO rag_documents VALUES (?, ?, ?, ?, ?)",
                (document_id, index_id, 0, "legacy.pdf", str(source_path)),
            )
            connection.execute(
                """
                INSERT INTO rag_chunks (
                    chunk_id, index_id, document_id, position, page_number,
                    chunk_index, text, embedding_dimension, embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    7,
                    index_id,
                    document_id,
                    0,
                    2,
                    0,
                    "Legacy source text",
                    2,
                    struct.pack("<2d", 0.25, -0.75),
                ),
            )
    return original


def _create_schema_v2_store(db_path: Path) -> RagIndex:
    original = _create_schema_v1_store(db_path)
    store = SQLiteRagIndexStore(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        store._migrate_v1_to_v2(connection)
        connection.execute(
            "UPDATE store_metadata SET value = '2' WHERE key = 'schema_version'"
        )
        connection.execute(
            """
            UPDATE rag_documents
            SET
                content_sha256 = ?,
                file_size = ?,
                mtime_ns = ?,
                indexed_at = ?
            """,
            ("a" * 64, 123, 456, "2026-08-02T00:00:00Z"),
        )
        connection.commit()
    return original


def test_initialize_migrates_v1_transactionally_without_changing_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    original = _create_schema_v1_store(db_path)

    migrated = SQLiteRagIndexStore(db_path)
    migrated.initialize()

    assert migrated.load_index(
        "00000000-0000-0000-0000-000000000101"
    ) == original
    metadata = migrated.get_index_metadata(
        "00000000-0000-0000-0000-000000000101"
    )
    assert metadata.documents[0].document_id == (
        "00000000-0000-0000-0000-000000000102"
    )
    assert metadata.documents[0].content_sha256 is None
    assert metadata.documents[0].file_size is None
    assert metadata.documents[0].mtime_ns is None
    assert metadata.documents[0].indexed_at is None
    assert metadata.display_name is None
    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        chunk_row = connection.execute(
            "SELECT chunk_id, embedding FROM rag_chunks"
        ).fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert version == ("3",)
    assert chunk_row == (7, struct.pack("<2d", 0.25, -0.75))
    assert foreign_key_errors == []


def test_initialize_migrates_v2_to_v3_without_changing_persistent_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "version-two.sqlite3"
    original = _create_schema_v2_store(db_path)
    with sqlite3.connect(db_path) as connection:
        before_ids_and_embedding = connection.execute(
            """
            SELECT i.index_id, d.document_id, c.chunk_id, c.embedding
            FROM rag_indexes AS i
            JOIN rag_documents AS d ON d.index_id = i.index_id
            JOIN rag_chunks AS c
                ON c.index_id = d.index_id AND c.document_id = d.document_id
            """
        ).fetchone()

    migrated = SQLiteRagIndexStore(db_path)
    migrated.initialize()

    metadata = migrated.get_index_metadata(
        "00000000-0000-0000-0000-000000000101"
    )
    assert migrated.load_index(metadata.index_id) == original
    assert metadata.display_name is None
    assert metadata.documents[0].content_sha256 == "a" * 64
    assert metadata.documents[0].file_size == 123
    assert metadata.documents[0].mtime_ns == 456
    assert metadata.documents[0].indexed_at == "2026-08-02T00:00:00Z"
    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        after_ids_and_embedding = connection.execute(
            """
            SELECT i.index_id, d.document_id, c.chunk_id, c.embedding
            FROM rag_indexes AS i
            JOIN rag_documents AS d ON d.index_id = i.index_id
            JOIN rag_chunks AS c
                ON c.index_id = d.index_id AND c.document_id = d.document_id
            """
        ).fetchone()
    assert version == ("3",)
    assert after_ids_and_embedding == before_ids_and_embedding


def test_failed_v2_to_v3_migration_rolls_back_without_claiming_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "version-two.sqlite3"
    _create_schema_v2_store(db_path)
    migrating = SQLiteRagIndexStore(db_path)

    def fail_after_schema_change(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE rag_indexes ADD COLUMN display_name TEXT NULL"
        )
        raise sqlite3.OperationalError("simulated v3 migration failure")

    monkeypatch.setattr(migrating, "_migrate_v2_to_v3", fail_after_schema_change)

    with pytest.raises(sqlite3.OperationalError, match="simulated v3"):
        migrating.initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(rag_indexes)")
        }
    assert version == ("2",)
    assert "display_name" not in columns


def test_v1_to_v3_rolls_back_both_steps_when_v3_migration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "version-one.sqlite3"
    _create_schema_v1_store(db_path)
    migrating = SQLiteRagIndexStore(db_path)

    def fail_v3(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE rag_indexes ADD COLUMN display_name TEXT NULL"
        )
        raise sqlite3.OperationalError("simulated sequential migration failure")

    monkeypatch.setattr(migrating, "_migrate_v2_to_v3", fail_v3)

    with pytest.raises(sqlite3.OperationalError, match="simulated sequential"):
        migrating.initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        document_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(rag_documents)")
        }
        index_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(rag_indexes)")
        }
        chunk = connection.execute(
            "SELECT chunk_id, embedding FROM rag_chunks"
        ).fetchone()
    assert version == ("1",)
    assert "content_sha256" not in document_columns
    assert "display_name" not in index_columns
    assert chunk == (7, struct.pack("<2d", 0.25, -0.75))


def test_failed_v1_migration_rolls_back_schema_and_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    _create_schema_v1_store(db_path, with_data=False)
    migrating = SQLiteRagIndexStore(db_path)

    def fail_after_schema_change(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE rag_documents ADD COLUMN content_sha256 TEXT NULL"
        )
        raise sqlite3.OperationalError("simulated migration failure")

    monkeypatch.setattr(migrating, "_migrate_v1_to_v2", fail_after_schema_change)

    with pytest.raises(sqlite3.OperationalError, match="simulated"):
        migrating.initialize()

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT value FROM store_metadata WHERE key = 'schema_version'"
        ).fetchone()
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(rag_documents)")
        }
    assert version == ("1",)
    assert "content_sha256" not in columns


def test_migrated_v1_document_reports_unknown_with_current_file_metadata(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.sqlite3"
    source_path = tmp_path / "legacy.pdf"
    source_path.write_bytes(b"legacy source bytes")
    _create_schema_v1_store(db_path, source_path=source_path)
    migrated = SQLiteRagIndexStore(db_path)
    migrated.initialize()

    status = PersistentRagDocumentManager(
        migrated,
        client=object(),  # type: ignore[arg-type]
    ).inspect_documents("00000000-0000-0000-0000-000000000101")[0]

    assert status.status is DocumentStatus.UNKNOWN
    assert status.stored_content_sha256 is None
    assert status.current_content_sha256 is not None
    assert status.current_file_size == len(b"legacy source bytes")


def test_schema_v2_rejects_cross_index_document_chunk_association(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    first = store.save_index(make_index(), make_source_paths(tmp_path))
    second = store.save_index(make_index(), make_source_paths(tmp_path))

    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute(
                """
                UPDATE rag_chunks
                SET index_id = ?, position = 100
                WHERE index_id = ? AND position = 0
                """,
                (second.index_id, first.index_id),
            )


def test_save_verified_index_persists_fingerprint_metadata(
    store: SQLiteRagIndexStore,
    tmp_path: Path,
) -> None:
    fingerprints = (
        SourceFingerprint("a" * 64, 10, 100),
        SourceFingerprint("b" * 64, 20, 200),
        SourceFingerprint("c" * 64, 30, 300),
    )

    saved = store.save_verified_index(
        make_index(),
        make_source_paths(tmp_path),
        fingerprints,
    )
    listed = store.get_index_metadata(saved.index_id)

    assert [document.content_sha256 for document in listed.documents] == [
        "a" * 64,
        "b" * 64,
        "c" * 64,
    ]
    assert [document.file_size for document in listed.documents] == [10, 20, 30]
    assert [document.mtime_ns for document in listed.documents] == [100, 200, 300]
    assert all(document.indexed_at is not None for document in listed.documents)
