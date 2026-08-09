from __future__ import annotations

import math
import sqlite3
import struct
import uuid
from collections.abc import Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import Chunk, EmbeddedChunk, RagIndex


SCHEMA_VERSION = 3
MAX_DISPLAY_NAME_LENGTH = 100


class RagIndexStoreError(RuntimeError):
    """Raised when a persistent RAG index store operation cannot finish safely."""


@dataclass(frozen=True)
class StoredDocumentMetadata:
    """Persistent identity and source information for one indexed document."""

    document_id: str
    document_name: str
    source_path: Path
    position: int
    content_sha256: str | None = None
    file_size: int | None = None
    mtime_ns: int | None = None
    indexed_at: str | None = None


@dataclass(frozen=True)
class SourceFingerprint:
    """A verified source-file fingerprint stored with document metadata."""

    content_sha256: str
    file_size: int
    mtime_ns: int


@dataclass(frozen=True)
class StoredRagIndexMetadata:
    """Lightweight metadata for one stored RAG index."""

    index_id: str
    embedding_model: str
    created_at: str
    documents: tuple[StoredDocumentMetadata, ...]
    chunk_count: int
    display_name: str | None = None


@dataclass(frozen=True)
class _PreparedChunk:
    document_name: str
    page_number: int
    chunk_index: int
    text: str
    embedding_dimension: int
    embedding_blob: bytes


class SQLiteRagIndexStore:
    """Persist complete immutable RagIndex values in a local SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def initialize(self) -> None:
        """Create schema v3 or transactionally migrate schema v1/v2."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with closing(self._open_connection()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS store_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    )
                    """
                )
                row = connection.execute(
                    "SELECT value FROM store_metadata WHERE key = ?",
                    ("schema_version",),
                ).fetchone()
                if row is None:
                    self._create_schema_v3(connection)
                    connection.execute(
                        "INSERT INTO store_metadata (key, value) VALUES (?, ?)",
                        ("schema_version", str(SCHEMA_VERSION)),
                    )
                elif row["value"] == "1":
                    self._migrate_v1_to_v2(connection)
                    self._migrate_v2_to_v3(connection)
                    connection.execute(
                        """
                        UPDATE store_metadata
                        SET value = ?
                        WHERE key = ?
                        """,
                        (str(SCHEMA_VERSION), "schema_version"),
                    )
                elif row["value"] == "2":
                    self._migrate_v2_to_v3(connection)
                    connection.execute(
                        """
                        UPDATE store_metadata
                        SET value = ?
                        WHERE key = ?
                        """,
                        (str(SCHEMA_VERSION), "schema_version"),
                    )
                elif row["value"] == str(SCHEMA_VERSION):
                    self._create_schema_v3(connection)
                else:
                    self._raise_unsupported_schema(row["value"])
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def save_index(
        self,
        index: RagIndex,
        source_paths: Sequence[Path],
        *,
        display_name: str | None = None,
    ) -> StoredRagIndexMetadata:
        """Save a prebuilt index without claiming trusted file fingerprints."""
        return self._save_index(
            index,
            source_paths,
            fingerprints=None,
            display_name=display_name,
        )

    def save_verified_index(
        self,
        index: RagIndex,
        source_paths: Sequence[Path],
        fingerprints: Sequence[SourceFingerprint],
        *,
        display_name: str | None = None,
    ) -> StoredRagIndexMetadata:
        """Save an index with fingerprints verified around document building."""
        return self._save_index(
            index,
            source_paths,
            fingerprints=fingerprints,
            display_name=display_name,
        )

    def _save_index(
        self,
        index: RagIndex,
        source_paths: Sequence[Path],
        *,
        fingerprints: Sequence[SourceFingerprint] | None,
        display_name: str | None,
    ) -> StoredRagIndexMetadata:
        normalized_display_name = _normalize_display_name(display_name)
        normalized_paths = self._validate_source_paths(index, source_paths)
        verified_fingerprints = self._validate_fingerprints(
            fingerprints,
            document_count=len(index.document_names),
        )
        prepared_chunks = tuple(
            self._prepare_chunk(embedded_chunk)
            for embedded_chunk in index.embedded_chunks
        )

        index_id = str(uuid.uuid4())
        created_at = _utc_now_iso8601()
        documents = tuple(
            StoredDocumentMetadata(
                document_id=str(uuid.uuid4()),
                document_name=document_name,
                source_path=source_path,
                position=position,
                content_sha256=(
                    verified_fingerprints[position].content_sha256
                    if verified_fingerprints is not None
                    else None
                ),
                file_size=(
                    verified_fingerprints[position].file_size
                    if verified_fingerprints is not None
                    else None
                ),
                mtime_ns=(
                    verified_fingerprints[position].mtime_ns
                    if verified_fingerprints is not None
                    else None
                ),
                indexed_at=(
                    created_at if verified_fingerprints is not None else None
                ),
            )
            for position, (document_name, source_path) in enumerate(
                zip(index.document_names, normalized_paths, strict=True)
            )
        )
        document_ids = {
            document.document_name: document.document_id
            for document in documents
        }

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO rag_indexes (
                            index_id,
                            display_name,
                            embedding_model,
                            created_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            index_id,
                            normalized_display_name,
                            index.embedding_model,
                            created_at,
                        ),
                    )
                    connection.executemany(
                        """
                        INSERT INTO rag_documents (
                            document_id,
                            index_id,
                            position,
                            document_name,
                            source_path,
                            content_sha256,
                            file_size,
                            mtime_ns,
                            indexed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                document.document_id,
                                index_id,
                                document.position,
                                document.document_name,
                                str(document.source_path),
                                document.content_sha256,
                                document.file_size,
                                document.mtime_ns,
                                document.indexed_at,
                            )
                            for document in documents
                        ],
                    )
                    self._insert_chunks(
                        connection,
                        index_id,
                        document_ids,
                        prepared_chunks,
                    )
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to save RAG index: {index_id}"
                ) from exc

        return StoredRagIndexMetadata(
            index_id=index_id,
            embedding_model=index.embedding_model,
            created_at=created_at,
            documents=documents,
            chunk_count=len(prepared_chunks),
            display_name=normalized_display_name,
        )

    def load_index(self, index_id: str) -> RagIndex:
        """Load a prepared index without reading source PDFs or using Ollama."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            index_row = connection.execute(
                """
                SELECT embedding_model
                FROM rag_indexes
                WHERE index_id = ?
                """,
                (clean_index_id,),
            ).fetchone()
            if index_row is None:
                raise KeyError(f"Stored RAG index does not exist: {clean_index_id}")

            document_rows = connection.execute(
                """
                SELECT position, document_name
                FROM rag_documents
                WHERE index_id = ?
                ORDER BY position ASC
                """,
                (clean_index_id,),
            ).fetchall()
            chunk_rows = connection.execute(
                """
                SELECT
                    c.position,
                    d.document_name,
                    c.page_number,
                    c.chunk_index,
                    c.text,
                    c.embedding_dimension,
                    c.embedding
                FROM rag_chunks AS c
                JOIN rag_documents AS d
                    ON d.index_id = c.index_id
                    AND d.document_id = c.document_id
                WHERE c.index_id = ?
                ORDER BY c.position ASC
                """,
                (clean_index_id,),
            ).fetchall()

        embedding_model = index_row["embedding_model"]
        if not embedding_model.strip():
            raise RagIndexStoreError(
                f"Stored RAG index has an empty embedding model: {clean_index_id}"
            )
        self._validate_ordered_positions(
            document_rows,
            item_name="document",
            index_id=clean_index_id,
        )
        self._validate_ordered_positions(
            chunk_rows,
            item_name="chunk",
            index_id=clean_index_id,
        )
        if not document_rows:
            raise RagIndexStoreError(
                f"Stored RAG index has no documents: {clean_index_id}"
            )
        if not chunk_rows:
            raise RagIndexStoreError(
                f"Stored RAG index has no chunks: {clean_index_id}"
            )

        embedded_chunks = tuple(
            EmbeddedChunk(
                chunk=Chunk(
                    document_name=row["document_name"],
                    page_number=row["page_number"],
                    chunk_index=row["chunk_index"],
                    text=row["text"],
                ),
                embedding=self._deserialize_embedding(
                    row["embedding"],
                    row["embedding_dimension"],
                ),
            )
            for row in chunk_rows
        )
        return RagIndex(
            document_names=tuple(
                row["document_name"] for row in document_rows
            ),
            embedding_model=embedding_model,
            embedded_chunks=embedded_chunks,
        )

    def list_indexes(self) -> tuple[StoredRagIndexMetadata, ...]:
        """List lightweight index metadata without loading embedding BLOBs."""
        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            index_rows = connection.execute(
                """
                SELECT
                    i.index_id,
                    i.display_name,
                    i.embedding_model,
                    i.created_at,
                    COUNT(c.chunk_id) AS chunk_count
                FROM rag_indexes AS i
                LEFT JOIN rag_chunks AS c ON c.index_id = i.index_id
                GROUP BY
                    i.index_id,
                    i.display_name,
                    i.embedding_model,
                    i.created_at
                ORDER BY i.created_at DESC, i.index_id ASC
                """
            ).fetchall()
            document_rows = connection.execute(
                """
                SELECT
                    index_id,
                    document_id,
                    document_name,
                    source_path,
                    position,
                    content_sha256,
                    file_size,
                    mtime_ns,
                    indexed_at
                FROM rag_documents
                ORDER BY index_id ASC, position ASC
                """
            ).fetchall()

        documents_by_index: dict[str, list[StoredDocumentMetadata]] = {
            row["index_id"]: [] for row in index_rows
        }
        for row in document_rows:
            documents_by_index[row["index_id"]].append(
                self._document_metadata_from_row(row)
            )

        return tuple(
            StoredRagIndexMetadata(
                index_id=row["index_id"],
                embedding_model=row["embedding_model"],
                created_at=row["created_at"],
                documents=tuple(documents_by_index[row["index_id"]]),
                chunk_count=row["chunk_count"],
                display_name=row["display_name"],
            )
            for row in index_rows
        )

    def get_index_metadata(self, index_id: str) -> StoredRagIndexMetadata:
        """Return one index's lightweight metadata without loading embeddings."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")
        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            index_row = connection.execute(
                """
                SELECT
                    i.index_id,
                    i.display_name,
                    i.embedding_model,
                    i.created_at,
                    COUNT(c.chunk_id) AS chunk_count
                FROM rag_indexes AS i
                LEFT JOIN rag_chunks AS c ON c.index_id = i.index_id
                WHERE i.index_id = ?
                GROUP BY
                    i.index_id,
                    i.display_name,
                    i.embedding_model,
                    i.created_at
                """,
                (clean_index_id,),
            ).fetchone()
            if index_row is None:
                raise KeyError(
                    f"Stored RAG index does not exist: {clean_index_id}"
                )
            document_rows = connection.execute(
                """
                SELECT
                    index_id,
                    document_id,
                    document_name,
                    source_path,
                    position,
                    content_sha256,
                    file_size,
                    mtime_ns,
                    indexed_at
                FROM rag_documents
                WHERE index_id = ?
                ORDER BY position ASC
                """,
                (clean_index_id,),
            ).fetchall()

        return StoredRagIndexMetadata(
            index_id=index_row["index_id"],
            embedding_model=index_row["embedding_model"],
            created_at=index_row["created_at"],
            documents=tuple(
                self._document_metadata_from_row(row)
                for row in document_rows
            ),
            chunk_count=index_row["chunk_count"],
            display_name=index_row["display_name"],
        )

    def rename_index(
        self,
        index_id: str,
        display_name: str,
    ) -> StoredRagIndexMetadata:
        """Atomically update presentation metadata without touching RAG data."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")
        clean_display_name = _normalize_display_name(display_name)
        if clean_display_name is None:
            raise ValueError("display_name must not be None when renaming")

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    cursor = connection.execute(
                        """
                        UPDATE rag_indexes
                        SET display_name = ?
                        WHERE index_id = ?
                        """,
                        (clean_display_name, clean_index_id),
                    )
                    if cursor.rowcount == 0:
                        raise KeyError(
                            "Stored RAG index does not exist: "
                            f"{clean_index_id}"
                        )
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to rename RAG index: {clean_index_id}"
                ) from exc

        return self.get_index_metadata(clean_index_id)

    def append_document(
        self,
        index_id: str,
        document_index: RagIndex,
        source_path: Path,
        fingerprint: SourceFingerprint,
    ) -> StoredDocumentMetadata:
        """Atomically append one newly prepared document to an index."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")
        self._require_single_document_index(document_index)
        normalized_path = self._validate_source_paths(
            document_index,
            (source_path,),
        )[0]
        self._validate_fingerprint(fingerprint)
        prepared_chunks = tuple(
            self._prepare_chunk(embedded_chunk)
            for embedded_chunk in document_index.embedded_chunks
        )
        indexed_at = _utc_now_iso8601()
        document = StoredDocumentMetadata(
            document_id=str(uuid.uuid4()),
            document_name=document_index.document_names[0],
            source_path=normalized_path,
            position=0,
            content_sha256=fingerprint.content_sha256,
            file_size=fingerprint.file_size,
            mtime_ns=fingerprint.mtime_ns,
            indexed_at=indexed_at,
        )

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    index_row = self._get_index_row(connection, clean_index_id)
                    if index_row["embedding_model"] != document_index.embedding_model:
                        raise ValueError(
                            "document embedding model must match stored index model"
                        )
                    duplicate = connection.execute(
                        """
                        SELECT 1
                        FROM rag_documents
                        WHERE index_id = ? AND document_name = ?
                        """,
                        (clean_index_id, document.document_name),
                    ).fetchone()
                    if duplicate is not None:
                        raise ValueError(
                            "document name already exists in stored index: "
                            f"{document.document_name}"
                        )
                    position = connection.execute(
                        """
                        SELECT COALESCE(MAX(position), -1) + 1
                        FROM rag_documents
                        WHERE index_id = ?
                        """,
                        (clean_index_id,),
                    ).fetchone()[0]
                    document = StoredDocumentMetadata(
                        document_id=document.document_id,
                        document_name=document.document_name,
                        source_path=document.source_path,
                        position=position,
                        content_sha256=document.content_sha256,
                        file_size=document.file_size,
                        mtime_ns=document.mtime_ns,
                        indexed_at=document.indexed_at,
                    )
                    self._insert_document(connection, clean_index_id, document)
                    start_position = connection.execute(
                        """
                        SELECT COALESCE(MAX(position), -1) + 1
                        FROM rag_chunks
                        WHERE index_id = ?
                        """,
                        (clean_index_id,),
                    ).fetchone()[0]
                    self._insert_document_chunks(
                        connection,
                        clean_index_id,
                        document.document_id,
                        prepared_chunks,
                        start_position=start_position,
                    )
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to append document to RAG index: {clean_index_id}"
                ) from exc
        return document

    def remove_document(
        self,
        index_id: str,
        document_id: str,
    ) -> StoredDocumentMetadata:
        """Atomically remove one document while keeping the index searchable."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")
        clean_document_id = _require_uuid(
            document_id,
            field_name="document_id",
        )

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    self._get_index_row(connection, clean_index_id)
                    row = self._get_document_row(
                        connection,
                        clean_index_id,
                        clean_document_id,
                    )
                    total_chunks = connection.execute(
                        "SELECT COUNT(*) FROM rag_chunks WHERE index_id = ?",
                        (clean_index_id,),
                    ).fetchone()[0]
                    document_chunks = connection.execute(
                        """
                        SELECT COUNT(*)
                        FROM rag_chunks
                        WHERE index_id = ? AND document_id = ?
                        """,
                        (clean_index_id, clean_document_id),
                    ).fetchone()[0]
                    if total_chunks - document_chunks <= 0:
                        raise ValueError(
                            "cannot remove the last searchable document; "
                            "use delete_index() to remove the whole corpus"
                        )
                    removed = self._document_metadata_from_row(row)
                    connection.execute(
                        """
                        DELETE FROM rag_documents
                        WHERE index_id = ? AND document_id = ?
                        """,
                        (clean_index_id, clean_document_id),
                    )
                    self._compact_document_positions(connection, clean_index_id)
                    self._renumber_chunk_positions(connection, clean_index_id)
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to remove document from RAG index: {clean_index_id}"
                ) from exc
        return removed

    def replace_document_chunks(
        self,
        index_id: str,
        document_id: str,
        document_index: RagIndex,
        fingerprint: SourceFingerprint,
    ) -> StoredDocumentMetadata:
        """Atomically replace one document's chunks and fingerprint metadata."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")
        clean_document_id = _require_uuid(
            document_id,
            field_name="document_id",
        )
        self._require_single_document_index(document_index)
        self._validate_fingerprint(fingerprint)
        prepared_chunks = tuple(
            self._prepare_chunk(embedded_chunk)
            for embedded_chunk in document_index.embedded_chunks
        )
        indexed_at = _utc_now_iso8601()

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    index_row = self._get_index_row(connection, clean_index_id)
                    if index_row["embedding_model"] != document_index.embedding_model:
                        raise ValueError(
                            "document embedding model must match stored index model"
                        )
                    row = self._get_document_row(
                        connection,
                        clean_index_id,
                        clean_document_id,
                    )
                    if row["document_name"] != document_index.document_names[0]:
                        raise ValueError(
                            "reindexed document name must match stored document name"
                        )
                    connection.execute(
                        """
                        DELETE FROM rag_chunks
                        WHERE index_id = ? AND document_id = ?
                        """,
                        (clean_index_id, clean_document_id),
                    )
                    start_position = connection.execute(
                        """
                        SELECT COALESCE(MAX(position), -1) + 1
                        FROM rag_chunks
                        WHERE index_id = ?
                        """,
                        (clean_index_id,),
                    ).fetchone()[0]
                    self._insert_document_chunks(
                        connection,
                        clean_index_id,
                        clean_document_id,
                        prepared_chunks,
                        start_position=start_position,
                    )
                    connection.execute(
                        """
                        UPDATE rag_documents
                        SET
                            content_sha256 = ?,
                            file_size = ?,
                            mtime_ns = ?,
                            indexed_at = ?
                        WHERE index_id = ? AND document_id = ?
                        """,
                        (
                            fingerprint.content_sha256,
                            fingerprint.file_size,
                            fingerprint.mtime_ns,
                            indexed_at,
                            clean_index_id,
                            clean_document_id,
                        ),
                    )
                    self._renumber_chunk_positions(connection, clean_index_id)
                    updated_row = self._get_document_row(
                        connection,
                        clean_index_id,
                        clean_document_id,
                    )
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to reindex document in RAG index: {clean_index_id}"
                ) from exc
        return self._document_metadata_from_row(updated_row)

    def delete_index(self, index_id: str) -> bool:
        """Delete one stored index and cascade to its documents and chunks."""
        clean_index_id = _require_uuid(index_id, field_name="index_id")

        with closing(self._open_connection()) as connection:
            self._require_supported_schema(connection)
            try:
                with connection:
                    cursor = connection.execute(
                        "DELETE FROM rag_indexes WHERE index_id = ?",
                        (clean_index_id,),
                    )
            except sqlite3.Error as exc:
                raise RagIndexStoreError(
                    f"Failed to delete RAG index: {clean_index_id}"
                ) from exc
        return cursor.rowcount > 0

    def _open_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _create_schema_v3(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_indexes (
                index_id TEXT PRIMARY KEY,
                display_name TEXT NULL,
                embedding_model TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_documents (
                document_id TEXT PRIMARY KEY,
                index_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                document_name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                content_sha256 TEXT NULL,
                file_size INTEGER NULL,
                mtime_ns INTEGER NULL,
                indexed_at TEXT NULL,
                FOREIGN KEY (index_id)
                    REFERENCES rag_indexes(index_id)
                    ON DELETE CASCADE,
                UNIQUE (index_id, position),
                UNIQUE (index_id, document_name),
                UNIQUE (index_id, document_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_chunks (
                chunk_id INTEGER PRIMARY KEY,
                index_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding_dimension INTEGER NOT NULL,
                embedding BLOB NOT NULL,
                FOREIGN KEY (index_id)
                    REFERENCES rag_indexes(index_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (index_id, document_id)
                    REFERENCES rag_documents(index_id, document_id)
                    ON DELETE CASCADE,
                UNIQUE (index_id, position)
            )
            """
        )

    def _migrate_v1_to_v2(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE rag_documents ADD COLUMN content_sha256 TEXT NULL"
        )
        connection.execute(
            "ALTER TABLE rag_documents ADD COLUMN file_size INTEGER NULL"
        )
        connection.execute(
            "ALTER TABLE rag_documents ADD COLUMN mtime_ns INTEGER NULL"
        )
        connection.execute(
            "ALTER TABLE rag_documents ADD COLUMN indexed_at TEXT NULL"
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX rag_documents_index_document_unique
            ON rag_documents(index_id, document_id)
            """
        )
        connection.execute("ALTER TABLE rag_chunks RENAME TO rag_chunks_v1")
        connection.execute(
            """
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
                FOREIGN KEY (index_id)
                    REFERENCES rag_indexes(index_id)
                    ON DELETE CASCADE,
                FOREIGN KEY (index_id, document_id)
                    REFERENCES rag_documents(index_id, document_id)
                    ON DELETE CASCADE,
                UNIQUE (index_id, position)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO rag_chunks (
                chunk_id,
                index_id,
                document_id,
                position,
                page_number,
                chunk_index,
                text,
                embedding_dimension,
                embedding
            )
            SELECT
                chunk_id,
                index_id,
                document_id,
                position,
                page_number,
                chunk_index,
                text,
                embedding_dimension,
                embedding
            FROM rag_chunks_v1
            ORDER BY chunk_id
            """
        )
        connection.execute("DROP TABLE rag_chunks_v1")

    @staticmethod
    def _migrate_v2_to_v3(connection: sqlite3.Connection) -> None:
        connection.execute(
            "ALTER TABLE rag_indexes ADD COLUMN display_name TEXT NULL"
        )

    def _require_supported_schema(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        try:
            row = connection.execute(
                "SELECT value FROM store_metadata WHERE key = ?",
                ("schema_version",),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            raise RagIndexStoreError(
                "RAG index store is not initialized"
            ) from exc
        if row is None:
            raise RagIndexStoreError("RAG index store has no schema_version")
        if row["value"] != str(SCHEMA_VERSION):
            self._raise_unsupported_schema(row["value"])

    @staticmethod
    def _raise_unsupported_schema(value: str) -> None:
        raise RagIndexStoreError(
            "Unsupported RAG index store schema version: "
            f"{value}; expected {SCHEMA_VERSION}"
        )

    @staticmethod
    def _validate_source_paths(
        index: RagIndex,
        source_paths: Sequence[Path],
    ) -> tuple[Path, ...]:
        if not index.embedding_model.strip():
            raise ValueError("index embedding_model must not be empty")
        if not index.embedded_chunks:
            raise ValueError("index must contain at least one embedded chunk")
        if not index.document_names:
            raise ValueError("index must contain at least one document name")
        if len(set(index.document_names)) != len(index.document_names):
            raise ValueError("index document names must be unique")

        ordered_paths = tuple(source_paths)
        if not ordered_paths:
            raise ValueError("source_paths must not be empty")
        if len(ordered_paths) != len(index.document_names):
            raise ValueError(
                "source_paths count must match index document_names count"
            )

        normalized_paths = tuple(
            path.expanduser().resolve(strict=False) for path in ordered_paths
        )
        for position, (document_name, source_path) in enumerate(
            zip(index.document_names, normalized_paths, strict=True)
        ):
            if source_path.name != document_name:
                raise ValueError(
                    "source path basename must match index document name at "
                    f"position {position}: {source_path.name} != {document_name}"
                )

        known_names = set(index.document_names)
        for embedded_chunk in index.embedded_chunks:
            if embedded_chunk.chunk.document_name not in known_names:
                raise ValueError(
                    "embedded chunk references an unknown document name: "
                    f"{embedded_chunk.chunk.document_name}"
                )
        return normalized_paths

    @classmethod
    def _validate_fingerprints(
        cls,
        fingerprints: Sequence[SourceFingerprint] | None,
        *,
        document_count: int,
    ) -> tuple[SourceFingerprint, ...] | None:
        if fingerprints is None:
            return None
        verified = tuple(fingerprints)
        if len(verified) != document_count:
            raise ValueError(
                "fingerprints count must match index document_names count"
            )
        for fingerprint in verified:
            cls._validate_fingerprint(fingerprint)
        return verified

    @staticmethod
    def _validate_fingerprint(fingerprint: SourceFingerprint) -> None:
        digest = fingerprint.content_sha256
        if len(digest) != 64:
            raise ValueError("content_sha256 must contain 64 hexadecimal characters")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError(
                "content_sha256 must contain only hexadecimal characters"
            ) from exc
        if digest != digest.lower():
            raise ValueError("content_sha256 must use lowercase hexadecimal")
        if fingerprint.file_size < 0:
            raise ValueError("file_size must be 0 or greater")
        if fingerprint.mtime_ns < 0:
            raise ValueError("mtime_ns must be 0 or greater")

    @staticmethod
    def _require_single_document_index(index: RagIndex) -> None:
        if len(index.document_names) != 1:
            raise ValueError("document index must contain exactly one document")
        if not index.embedding_model.strip():
            raise ValueError("document index embedding_model must not be empty")
        if not index.embedded_chunks:
            raise ValueError("document index must contain at least one embedded chunk")
        document_name = index.document_names[0]
        if any(
            embedded_chunk.chunk.document_name != document_name
            for embedded_chunk in index.embedded_chunks
        ):
            raise ValueError(
                "document index chunks must reference its single document name"
            )

    @staticmethod
    def _document_metadata_from_row(
        row: sqlite3.Row,
    ) -> StoredDocumentMetadata:
        return StoredDocumentMetadata(
            document_id=row["document_id"],
            document_name=row["document_name"],
            source_path=Path(row["source_path"]),
            position=row["position"],
            content_sha256=row["content_sha256"],
            file_size=row["file_size"],
            mtime_ns=row["mtime_ns"],
            indexed_at=row["indexed_at"],
        )

    @staticmethod
    def _get_index_row(
        connection: sqlite3.Connection,
        index_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT index_id, embedding_model, created_at
            FROM rag_indexes
            WHERE index_id = ?
            """,
            (index_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Stored RAG index does not exist: {index_id}")
        return row

    @staticmethod
    def _get_document_row(
        connection: sqlite3.Connection,
        index_id: str,
        document_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT
                index_id,
                document_id,
                document_name,
                source_path,
                position,
                content_sha256,
                file_size,
                mtime_ns,
                indexed_at
            FROM rag_documents
            WHERE index_id = ? AND document_id = ?
            """,
            (index_id, document_id),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"Document {document_id} does not belong to RAG index {index_id}"
            )
        return row

    @staticmethod
    def _insert_document(
        connection: sqlite3.Connection,
        index_id: str,
        document: StoredDocumentMetadata,
    ) -> None:
        connection.execute(
            """
            INSERT INTO rag_documents (
                document_id,
                index_id,
                position,
                document_name,
                source_path,
                content_sha256,
                file_size,
                mtime_ns,
                indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                index_id,
                document.position,
                document.document_name,
                str(document.source_path),
                document.content_sha256,
                document.file_size,
                document.mtime_ns,
                document.indexed_at,
            ),
        )

    @staticmethod
    def _insert_document_chunks(
        connection: sqlite3.Connection,
        index_id: str,
        document_id: str,
        chunks: Sequence[_PreparedChunk],
        *,
        start_position: int,
    ) -> None:
        connection.executemany(
            """
            INSERT INTO rag_chunks (
                index_id,
                document_id,
                position,
                page_number,
                chunk_index,
                text,
                embedding_dimension,
                embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index_id,
                    document_id,
                    start_position + offset,
                    chunk.page_number,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.embedding_dimension,
                    sqlite3.Binary(chunk.embedding_blob),
                )
                for offset, chunk in enumerate(chunks)
            ],
        )

    @staticmethod
    def _compact_document_positions(
        connection: sqlite3.Connection,
        index_id: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT document_id
            FROM rag_documents
            WHERE index_id = ?
            ORDER BY position ASC
            """,
            (index_id,),
        ).fetchall()
        for position, row in enumerate(rows):
            connection.execute(
                """
                UPDATE rag_documents
                SET position = ?
                WHERE index_id = ? AND document_id = ?
                """,
                (-(position + 1), index_id, row["document_id"]),
            )
        for position, row in enumerate(rows):
            connection.execute(
                """
                UPDATE rag_documents
                SET position = ?
                WHERE index_id = ? AND document_id = ?
                """,
                (position, index_id, row["document_id"]),
            )

    @staticmethod
    def _renumber_chunk_positions(
        connection: sqlite3.Connection,
        index_id: str,
    ) -> None:
        rows = connection.execute(
            """
            SELECT c.chunk_id
            FROM rag_chunks AS c
            JOIN rag_documents AS d
                ON d.index_id = c.index_id
                AND d.document_id = c.document_id
            WHERE c.index_id = ?
            ORDER BY d.position ASC, c.position ASC
            """,
            (index_id,),
        ).fetchall()
        for position, row in enumerate(rows):
            connection.execute(
                """
                UPDATE rag_chunks
                SET position = ?
                WHERE index_id = ? AND chunk_id = ?
                """,
                (-(position + 1), index_id, row["chunk_id"]),
            )
        for position, row in enumerate(rows):
            connection.execute(
                """
                UPDATE rag_chunks
                SET position = ?
                WHERE index_id = ? AND chunk_id = ?
                """,
                (position, index_id, row["chunk_id"]),
            )

    @staticmethod
    def _prepare_chunk(embedded_chunk: EmbeddedChunk) -> _PreparedChunk:
        chunk = embedded_chunk.chunk
        if chunk.page_number < 1:
            raise ValueError("chunk page_number must be 1 or greater")
        if chunk.chunk_index < 0:
            raise ValueError("chunk_index must be 0 or greater")
        dimension, blob = _serialize_embedding(embedded_chunk.embedding)
        return _PreparedChunk(
            document_name=chunk.document_name,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            text=chunk.text,
            embedding_dimension=dimension,
            embedding_blob=blob,
        )

    @staticmethod
    def _insert_chunks(
        connection: sqlite3.Connection,
        index_id: str,
        document_ids: dict[str, str],
        chunks: Sequence[_PreparedChunk],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO rag_chunks (
                index_id,
                document_id,
                position,
                page_number,
                chunk_index,
                text,
                embedding_dimension,
                embedding
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    index_id,
                    document_ids[chunk.document_name],
                    position,
                    chunk.page_number,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.embedding_dimension,
                    sqlite3.Binary(chunk.embedding_blob),
                )
                for position, chunk in enumerate(chunks)
            ],
        )

    @staticmethod
    def _deserialize_embedding(
        raw_blob: bytes,
        dimension: int,
    ) -> tuple[float, ...]:
        if not isinstance(dimension, int) or dimension <= 0:
            raise RagIndexStoreError(
                f"Stored embedding has invalid dimension: {dimension}"
            )
        if not isinstance(raw_blob, (bytes, bytearray, memoryview)):
            raise RagIndexStoreError("Stored embedding is not a binary BLOB")
        blob = bytes(raw_blob)
        expected_length = dimension * 8
        if len(blob) != expected_length:
            raise RagIndexStoreError(
                "Stored embedding BLOB length does not match its dimension: "
                f"expected {expected_length} bytes, found {len(blob)}"
            )
        values = struct.unpack(f"<{dimension}d", blob)
        if not all(math.isfinite(value) for value in values):
            raise RagIndexStoreError(
                "Stored embedding contains a non-finite value"
            )
        return values

    @staticmethod
    def _validate_ordered_positions(
        rows: Sequence[sqlite3.Row],
        *,
        item_name: str,
        index_id: str,
    ) -> None:
        positions = tuple(row["position"] for row in rows)
        expected = tuple(range(len(rows)))
        if positions != expected:
            raise RagIndexStoreError(
                f"Stored {item_name} positions are corrupt for index "
                f"{index_id}: {positions}"
            )


def _serialize_embedding(embedding: Sequence[float]) -> tuple[int, bytes]:
    """Encode an embedding as little-endian IEEE-754 float64."""
    values = tuple(float(value) for value in embedding)
    if not values:
        raise ValueError("embedding must not be empty")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding must contain only finite values")
    return len(values), struct.pack(f"<{len(values)}d", *values)


def _require_uuid(value: str, *, field_name: str) -> str:
    clean_value = value.strip()
    if not clean_value:
        raise ValueError(f"{field_name} must not be empty")
    try:
        parsed_id = uuid.UUID(clean_value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc
    return str(parsed_id)


def _normalize_display_name(display_name: str | None) -> str | None:
    """Normalize an optional corpus label shared by save and rename writes."""
    if display_name is None:
        return None
    if not isinstance(display_name, str):
        raise TypeError("display_name must be a string or None")
    clean_name = display_name.strip()
    if not clean_name:
        raise ValueError("display_name must not be empty")
    if len(clean_name) > MAX_DISPLAY_NAME_LENGTH:
        raise ValueError(
            "display_name must be "
            f"{MAX_DISPLAY_NAME_LENGTH} characters or fewer"
        )
    return clean_name


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
