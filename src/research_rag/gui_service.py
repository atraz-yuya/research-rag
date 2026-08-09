from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from .defaults import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_TOP_K,
)
from .document_manager import DocumentInspection, PersistentRagDocumentManager
from .index_store import (
    SQLiteRagIndexStore,
    StoredDocumentMetadata,
    StoredRagIndexMetadata,
)
from .models import RagAnswer
from .ollama_client import OllamaClient
from .rag_service import answer_question_from_index


class RagGuiService:
    """Application-facing adapter over persistence and production RAG services."""

    def __init__(
        self,
        store: SQLiteRagIndexStore,
        *,
        client: OllamaClient | None = None,
        manager: PersistentRagDocumentManager | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        generation_model: str = DEFAULT_GENERATION_MODEL,
        top_k: int = DEFAULT_TOP_K,
    ) -> None:
        self.store = store
        self.client = client if client is not None else OllamaClient()
        self.manager = (
            manager
            if manager is not None
            else PersistentRagDocumentManager(store, client=self.client)
        )
        self.embedding_model = embedding_model
        self.generation_model = generation_model
        self.top_k = top_k

    def initialize(self) -> None:
        """Initialize or migrate the persistent store."""
        self.store.initialize()

    def list_corpora(self) -> tuple[StoredRagIndexMetadata, ...]:
        """List lightweight corpus metadata without loading embeddings."""
        return self.store.list_indexes()

    def inspect_documents(
        self,
        index_id: str,
    ) -> tuple[DocumentInspection, ...]:
        """Inspect ordered document source statuses for one corpus."""
        return self.manager.inspect_documents(index_id)

    def create_corpus(
        self,
        pdf_paths: Sequence[Path],
        *,
        display_name: str | None = None,
    ) -> StoredRagIndexMetadata:
        """Create a managed persistent corpus from one or more PDFs."""
        return self.manager.create_index(
            pdf_paths,
            embedding_model=self.embedding_model,
            display_name=display_name,
        )

    def rename_corpus(
        self,
        index_id: str,
        display_name: str,
    ) -> StoredRagIndexMetadata:
        """Rename a corpus without loading or rebuilding its RAG contents."""
        return self.store.rename_index(index_id, display_name)

    def delete_corpus(self, index_id: str) -> bool:
        """Delete indexed corpus data without touching original PDFs."""
        return self.store.delete_index(index_id)

    def add_document(
        self,
        index_id: str,
        pdf_path: Path,
    ) -> StoredDocumentMetadata:
        """Append one PDF to a selected corpus."""
        return self.manager.add_document(index_id, pdf_path)

    def remove_document(
        self,
        index_id: str,
        document_id: str,
    ) -> StoredDocumentMetadata:
        """Remove one indexed document without deleting its source PDF."""
        return self.manager.remove_document(index_id, document_id)

    def reindex_document(
        self,
        index_id: str,
        document_id: str,
    ) -> StoredDocumentMetadata:
        """Reindex one selected document from its stored source path."""
        return self.manager.reindex_document(index_id, document_id)

    def answer(self, index_id: str, question: str) -> RagAnswer:
        """Load a stored corpus and answer one independent question."""
        clean_question = question.strip()
        if not clean_question:
            raise ValueError("question must not be empty")
        index = self.store.load_index(index_id)
        return answer_question_from_index(
            index,
            clean_question,
            generation_model=self.generation_model,
            top_k=self.top_k,
            client=self.client,
        )


def format_corpus_label(metadata: StoredRagIndexMetadata) -> str:
    """Derive a stable human-readable label without exposing the UUID."""
    if metadata.display_name and metadata.display_name.strip():
        return metadata.display_name
    if not metadata.documents:
        return "資料なし"
    first_name = metadata.documents[0].document_name
    additional_count = len(metadata.documents) - 1
    if additional_count == 0:
        return first_name
    return f"{first_name} + {additional_count}件"
