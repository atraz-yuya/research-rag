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


SCHEMA_VERSION = 1


class RagIndexStoreError(RuntimeError):
    """Raised when a persistent RAG index store operation cannot finish safely."""


@dataclass(frozen=True)
class StoredDocumentMetadata:
    """Persistent identity and source information for one indexed document."""

    document_id: str
    document_name: str
    source_path: Path
    position: int


@dataclass(frozen=True)
class StoredRagIndexMetadata:
    """Lightweight metadata for one stored RAG index."""

    index_id: str
    embedding_model: str
    created_at: str
    documents: tuple[StoredDocumentMetadata, ...]
    chunk_count: int


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
        """Create or validate the version-1 store schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with closing(self._open_connection()) as connection:
            with connection:
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
                    connection.execute(
                        "INSERT INTO store_metadata (key, value) VALUES (?, ?)",
                        ("schema_version", str(SCHEMA_VERSION)),
                    )
                else:
                    self._validate_schema_version(row["value"])

                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rag_indexes (
                        index_id TEXT PRIMARY KEY,
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
                        FOREIGN KEY (index_id)
                            REFERENCES rag_indexes(index_id)
                            ON DELETE CASCADE,
                        UNIQUE (index_id, position),
                        UNIQUE (index_id, document_name)
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
                        FOREIGN KEY (document_id)
                            REFERENCES rag_documents(document_id)
                            ON DELETE CASCADE,
                        UNIQUE (index_id, position)
                    )
                    """
                )

    def save_index(
        self,
        index: RagIndex,
        source_paths: Sequence[Path],
    ) -> StoredRagIndexMetadata:
        """Atomically save one complete index and return durable metadata."""
        normalized_paths = self._validate_source_paths(index, source_paths)
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
                            embedding_model,
                            created_at
                        ) VALUES (?, ?, ?)
                        """,
                        (index_id, index.embedding_model, created_at),
                    )
                    connection.executemany(
                        """
                        INSERT INTO rag_documents (
                            document_id,
                            index_id,
                            position,
                            document_name,
                            source_path
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                document.document_id,
                                index_id,
                                document.position,
                                document.document_name,
                                str(document.source_path),
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
        )

    def load_index(self, index_id: str) -> RagIndex:
        """Load a prepared index without reading source PDFs or using Ollama."""
        clean_index_id = _require_nonempty_index_id(index_id)

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
                    ON d.document_id = c.document_id
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
                    i.embedding_model,
                    i.created_at,
                    COUNT(c.chunk_id) AS chunk_count
                FROM rag_indexes AS i
                LEFT JOIN rag_chunks AS c ON c.index_id = i.index_id
                GROUP BY i.index_id, i.embedding_model, i.created_at
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
                    position
                FROM rag_documents
                ORDER BY index_id ASC, position ASC
                """
            ).fetchall()

        documents_by_index: dict[str, list[StoredDocumentMetadata]] = {
            row["index_id"]: [] for row in index_rows
        }
        for row in document_rows:
            documents_by_index[row["index_id"]].append(
                StoredDocumentMetadata(
                    document_id=row["document_id"],
                    document_name=row["document_name"],
                    source_path=Path(row["source_path"]),
                    position=row["position"],
                )
            )

        return tuple(
            StoredRagIndexMetadata(
                index_id=row["index_id"],
                embedding_model=row["embedding_model"],
                created_at=row["created_at"],
                documents=tuple(documents_by_index[row["index_id"]]),
                chunk_count=row["chunk_count"],
            )
            for row in index_rows
        )

    def delete_index(self, index_id: str) -> bool:
        """Delete one stored index and cascade to its documents and chunks."""
        clean_index_id = _require_nonempty_index_id(index_id)

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
        self._validate_schema_version(row["value"])

    @staticmethod
    def _validate_schema_version(value: str) -> None:
        if value != str(SCHEMA_VERSION):
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
    """Encode an embedding as schema-v1 little-endian IEEE-754 float64."""
    values = tuple(float(value) for value in embedding)
    if not values:
        raise ValueError("embedding must not be empty")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("embedding must contain only finite values")
    return len(values), struct.pack(f"<{len(values)}d", *values)


def _require_nonempty_index_id(index_id: str) -> str:
    clean_index_id = index_id.strip()
    if not clean_index_id:
        raise ValueError("index_id must not be empty")
    try:
        parsed_id = uuid.UUID(clean_index_id)
    except ValueError as exc:
        raise ValueError("index_id must be a valid UUID") from exc
    return str(parsed_id)


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
