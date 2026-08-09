from __future__ import annotations

import hashlib
import stat
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .index_store import (
    SQLiteRagIndexStore,
    SourceFingerprint,
    StoredDocumentMetadata,
    StoredRagIndexMetadata,
)
from .ollama_client import OllamaClient
from .rag_service import build_rag_index


_HASH_READ_SIZE = 1024 * 1024


class DocumentStatus(str, Enum):
    """Relationship between an indexed document and its stored source path."""

    CURRENT = "CURRENT"
    MODIFIED = "MODIFIED"
    MISSING = "MISSING"
    UNKNOWN = "UNKNOWN"


class SourceFileChangedError(RuntimeError):
    """Raised when a source PDF changes while an index operation is running."""


@dataclass(frozen=True)
class DocumentInspection:
    """Stored and current source metadata for one managed document."""

    index_id: str
    document_id: str
    document_name: str
    source_path: Path
    position: int
    status: DocumentStatus
    stored_content_sha256: str | None
    current_content_sha256: str | None
    stored_file_size: int | None
    current_file_size: int | None
    stored_mtime_ns: int | None
    current_mtime_ns: int | None
    indexed_at: str | None


def fingerprint_source_file(source_path: Path) -> SourceFingerprint:
    """Hash one regular file by streaming it and return supporting metadata."""
    path = source_path.expanduser().resolve(strict=False)
    try:
        before = path.stat()
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"PDF source does not exist: {path}") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f"PDF source is not a regular file: {path}")

    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(_HASH_READ_SIZE):
            digest.update(block)

    after = path.stat()
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity:
        raise SourceFileChangedError(
            f"PDF source changed while its fingerprint was being computed: {path}"
        )

    return SourceFingerprint(
        content_sha256=digest.hexdigest(),
        file_size=after.st_size,
        mtime_ns=after.st_mtime_ns,
    )


class PersistentRagDocumentManager:
    """Coordinate filesystem and Ollama work around atomic store mutations."""

    def __init__(
        self,
        store: SQLiteRagIndexStore,
        *,
        client: OllamaClient | None = None,
    ) -> None:
        self.store = store
        self.client = client if client is not None else OllamaClient()

    def create_index(
        self,
        pdf_paths: Sequence[Path],
        *,
        embedding_model: str,
        display_name: str | None = None,
    ) -> StoredRagIndexMetadata:
        """Build and atomically save a new corpus with verified fingerprints."""
        clean_embedding_model = embedding_model.strip()
        if not clean_embedding_model:
            raise ValueError("embedding_model must not be empty")
        paths = _validate_new_pdf_paths(pdf_paths)
        before = tuple(fingerprint_source_file(path) for path in paths)
        index = build_rag_index(
            paths,
            embedding_model=clean_embedding_model,
            client=self.client,
        )
        after = tuple(fingerprint_source_file(path) for path in paths)
        _require_unchanged_sources(paths, before, after)
        return self.store.save_verified_index(
            index,
            paths,
            after,
            display_name=display_name,
        )

    def inspect_documents(
        self,
        index_id: str,
    ) -> tuple[DocumentInspection, ...]:
        """Inspect sources without PDF processing, Ollama calls, or DB writes."""
        metadata = self.store.get_index_metadata(index_id)
        return tuple(
            self._inspect_document(metadata.index_id, document)
            for document in metadata.documents
        )

    def add_document(
        self,
        index_id: str,
        pdf_path: Path,
    ) -> StoredDocumentMetadata:
        """Prepare and atomically append one new PDF to a stored corpus."""
        metadata = self.store.get_index_metadata(index_id)
        path = _validate_new_pdf_paths((pdf_path,))[0]
        if path.name in {
            document.document_name for document in metadata.documents
        }:
            raise ValueError(
                f"document name already exists in stored index: {path.name}"
            )

        before = fingerprint_source_file(path)
        document_index = build_rag_index(
            (path,),
            embedding_model=metadata.embedding_model,
            client=self.client,
        )
        after = fingerprint_source_file(path)
        _require_unchanged_sources((path,), (before,), (after,))
        return self.store.append_document(
            metadata.index_id,
            document_index,
            path,
            after,
        )

    def remove_document(
        self,
        index_id: str,
        document_id: str,
    ) -> StoredDocumentMetadata:
        """Atomically remove one document without touching its source file."""
        return self.store.remove_document(index_id, document_id)

    def reindex_document(
        self,
        index_id: str,
        document_id: str,
    ) -> StoredDocumentMetadata:
        """Rebuild only one stored document from its recorded source path."""
        metadata = self.store.get_index_metadata(index_id)
        document = _find_document(metadata, document_id)
        path = _require_regular_file(document.source_path)

        before = fingerprint_source_file(path)
        document_index = build_rag_index(
            (path,),
            embedding_model=metadata.embedding_model,
            client=self.client,
        )
        after = fingerprint_source_file(path)
        _require_unchanged_sources((path,), (before,), (after,))
        return self.store.replace_document_chunks(
            metadata.index_id,
            document.document_id,
            document_index,
            after,
        )

    @staticmethod
    def _inspect_document(
        index_id: str,
        document: StoredDocumentMetadata,
    ) -> DocumentInspection:
        current: SourceFingerprint | None = None
        try:
            source_stat = document.source_path.stat()
        except (FileNotFoundError, NotADirectoryError):
            status = DocumentStatus.MISSING
        else:
            if not stat.S_ISREG(source_stat.st_mode):
                status = DocumentStatus.MISSING
            else:
                current = fingerprint_source_file(document.source_path)
                if document.content_sha256 is None:
                    status = DocumentStatus.UNKNOWN
                elif current.content_sha256 == document.content_sha256:
                    status = DocumentStatus.CURRENT
                else:
                    status = DocumentStatus.MODIFIED

        return DocumentInspection(
            index_id=index_id,
            document_id=document.document_id,
            document_name=document.document_name,
            source_path=document.source_path,
            position=document.position,
            status=status,
            stored_content_sha256=document.content_sha256,
            current_content_sha256=(
                current.content_sha256 if current is not None else None
            ),
            stored_file_size=document.file_size,
            current_file_size=current.file_size if current is not None else None,
            stored_mtime_ns=document.mtime_ns,
            current_mtime_ns=current.mtime_ns if current is not None else None,
            indexed_at=document.indexed_at,
        )


def _validate_new_pdf_paths(pdf_paths: Sequence[Path]) -> tuple[Path, ...]:
    paths = tuple(_require_regular_file(path) for path in pdf_paths)
    if not paths:
        raise ValueError("at least one PDF must be selected")
    names = [path.name for path in paths]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(
            "PDF document names must be unique; duplicate basename(s): "
            + ", ".join(duplicates)
        )
    return paths


def _require_regular_file(source_path: Path) -> Path:
    path = source_path.expanduser().resolve(strict=False)
    try:
        source_stat = path.stat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise FileNotFoundError(f"PDF source does not exist: {path}") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError(f"PDF source is not a regular file: {path}")
    return path


def _require_unchanged_sources(
    paths: Sequence[Path],
    before: Sequence[SourceFingerprint],
    after: Sequence[SourceFingerprint],
) -> None:
    for path, earlier, later in zip(paths, before, after, strict=True):
        if earlier.content_sha256 != later.content_sha256:
            raise SourceFileChangedError(
                f"PDF source changed while it was being indexed: {path}"
            )


def _find_document(
    metadata: StoredRagIndexMetadata,
    document_id: str,
) -> StoredDocumentMetadata:
    clean_document_id = document_id.strip()
    if not clean_document_id:
        raise ValueError("document_id must not be empty")
    try:
        clean_document_id = str(uuid.UUID(clean_document_id))
    except ValueError as exc:
        raise ValueError("document_id must be a valid UUID") from exc
    for document in metadata.documents:
        if document.document_id == clean_document_id:
            return document
    raise KeyError(
        f"Document {clean_document_id} does not belong to RAG index "
        f"{metadata.index_id}"
    )
