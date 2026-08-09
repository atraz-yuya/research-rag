import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import time
import weakref
from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QWidget,
)

from research_rag.document_manager import DocumentInspection, DocumentStatus
from research_rag.index_store import (
    StoredDocumentMetadata,
    StoredRagIndexMetadata,
)
from research_rag.gui_worker import QtTaskRunner
from research_rag.main_window import MainWindow
from research_rag.models import Chunk, RagAnswer, SearchResult


def make_stored_document(
    name: str,
    document_id: str,
    position: int,
) -> StoredDocumentMetadata:
    return StoredDocumentMetadata(
        document_id=document_id,
        document_name=name,
        source_path=Path("/sources") / name,
        position=position,
    )


def make_corpus(
    index_id: str,
    *documents: StoredDocumentMetadata,
) -> StoredRagIndexMetadata:
    return StoredRagIndexMetadata(
        index_id=index_id,
        embedding_model="embedding-model",
        created_at="2026-08-09T00:00:00Z",
        documents=tuple(documents),
        chunk_count=len(documents),
    )


def make_inspection(
    index_id: str,
    document: StoredDocumentMetadata,
    status: DocumentStatus,
) -> DocumentInspection:
    return DocumentInspection(
        index_id=index_id,
        document_id=document.document_id,
        document_name=document.document_name,
        source_path=document.source_path,
        position=document.position,
        status=status,
        stored_content_sha256="a" * 64,
        current_content_sha256="a" * 64,
        stored_file_size=10,
        current_file_size=10,
        stored_mtime_ns=20,
        current_mtime_ns=20,
        indexed_at="2026-08-09T00:00:00Z",
    )


class StubGuiService:
    def __init__(self) -> None:
        first_documents = (
            make_stored_document("first.pdf", "doc-first", 0),
            make_stored_document("second.pdf", "doc-second", 1),
        )
        second_documents = (
            make_stored_document("other.pdf", "doc-other", 0),
        )
        self.corpora = [
            make_corpus("uuid-first", *first_documents),
            make_corpus("uuid-second", *second_documents),
        ]
        self.inspections = {
            "uuid-first": (
                make_inspection(
                    "uuid-first",
                    first_documents[0],
                    DocumentStatus.CURRENT,
                ),
                make_inspection(
                    "uuid-first",
                    first_documents[1],
                    DocumentStatus.MODIFIED,
                ),
            ),
            "uuid-second": (
                make_inspection(
                    "uuid-second",
                    second_documents[0],
                    DocumentStatus.UNKNOWN,
                ),
            ),
        }
        self.calls: list[tuple[Any, ...]] = []

    def list_corpora(self) -> tuple[StoredRagIndexMetadata, ...]:
        self.calls.append(("list",))
        return tuple(self.corpora)

    def inspect_documents(self, index_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("inspect", index_id))
        return self.inspections[index_id]

    def create_corpus(
        self,
        pdf_paths: tuple[Path, ...],
    ) -> StoredRagIndexMetadata:
        self.calls.append(("create", tuple(pdf_paths)))
        document = make_stored_document("created.pdf", "doc-created", 0)
        metadata = make_corpus("uuid-created", document)
        self.corpora.append(metadata)
        self.inspections[metadata.index_id] = (
            make_inspection(
                metadata.index_id,
                document,
                DocumentStatus.CURRENT,
            ),
        )
        return metadata

    def add_document(self, index_id: str, pdf_path: Path):  # type: ignore[no-untyped-def]
        self.calls.append(("add", index_id, pdf_path))
        return make_stored_document(pdf_path.name, "doc-added", 2)

    def remove_document(self, index_id: str, document_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("remove", index_id, document_id))
        return make_stored_document("removed.pdf", document_id, 0)

    def reindex_document(self, index_id: str, document_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("reindex", index_id, document_id))
        return make_stored_document("reindexed.pdf", document_id, 0)

    def answer(self, index_id: str, question: str) -> RagAnswer:
        self.calls.append(("answer", index_id, question))
        source = SearchResult(
            chunk=Chunk("first.pdf", 1, 0, "Grounded source text"),
            score=0.87654321,
            rank=1,
        )
        return RagAnswer("Grounded answer", (source,))


class BlockingInspectionService(StubGuiService):
    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()
        self.returned = Event()
        self.fail = fail
        self.delay = delay

    def inspect_documents(self, index_id: str):  # type: ignore[no-untyped-def]
        self.calls.append(("inspect", index_id))
        self.started.set()
        assert self.release.wait(timeout=3)
        if self.delay:
            time.sleep(self.delay)
        self.returned.set()
        if self.fail:
            raise RuntimeError("inspection failed")
        return self.inspections[index_id]


class ImmediateTaskRunner:
    def __init__(self) -> None:
        self.submissions = 0
        self.active_task_count = 0
        self.shutdown_calls = 0

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        self.submissions += 1
        self.active_task_count += 1
        try:
            result = operation()
        except Exception as exc:
            on_error(exc)
        else:
            on_success(result)
        finally:
            self.active_task_count -= 1
            on_finished()

    def request_shutdown(self, on_idle: Callable[[], None]) -> None:
        on_idle()

    def shutdown(self, *, wait: bool) -> None:
        self.shutdown_calls += 1
        assert not wait or self.active_task_count == 0


class QueuedTaskRunner:
    def __init__(self) -> None:
        self.tasks: list[
            tuple[
                Callable[[], Any],
                Callable[[Any], None],
                Callable[[Exception], None],
                Callable[[], None],
            ]
        ] = []
        self._idle_callbacks: list[Callable[[], None]] = []

    @property
    def active_task_count(self) -> int:
        return len(self.tasks)

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        self.tasks.append((operation, on_success, on_error, on_finished))

    def succeed_next(self) -> None:
        operation, on_success, _, on_finished = self.tasks.pop(0)
        on_success(operation())
        on_finished()
        self._notify_idle()

    def fail_next(self, error: Exception) -> None:
        _, _, on_error, on_finished = self.tasks.pop(0)
        on_error(error)
        on_finished()
        self._notify_idle()

    def request_shutdown(self, on_idle: Callable[[], None]) -> None:
        self._idle_callbacks.append(on_idle)
        self._notify_idle()

    def shutdown(self, *, wait: bool) -> None:
        assert not wait or not self.tasks

    def _notify_idle(self) -> None:
        if self.tasks:
            return
        callbacks, self._idle_callbacks = self._idle_callbacks, []
        for callback in callbacks:
            callback()


def make_window(
    qt_app: QApplication,
    *,
    service: StubGuiService | None = None,
    runner: ImmediateTaskRunner | QueuedTaskRunner | None = None,
) -> tuple[MainWindow, StubGuiService, ImmediateTaskRunner | QueuedTaskRunner]:
    selected_service = service if service is not None else StubGuiService()
    selected_runner = runner if runner is not None else ImmediateTaskRunner()
    window = MainWindow(
        selected_service,  # type: ignore[arg-type]
        task_runner=selected_runner,
    )
    return window, selected_service, selected_runner


def process_events_until(
    application: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        application.processEvents()
        if time.monotonic() >= deadline:
            raise TimeoutError("Qt window did not reach expected state")
        time.sleep(0.001)
    application.processEvents()


def test_main_window_constructs_and_startup_lists_corpora_without_loading(
    qt_app: QApplication,
) -> None:
    window, service, runner = make_window(qt_app)

    assert window.windowTitle() == "Research RAG"
    assert window.testAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    assert window.corpus_list.count() == 2
    assert window.corpus_list.item(0).text() == "first.pdf + 1件"
    assert window.corpus_list.item(0).data(Qt.ItemDataRole.UserRole) == "uuid-first"
    assert ("list",) in service.calls
    assert runner.submissions == 1
    window.close()


def test_plain_widget_tree_is_deterministically_deleted_without_rag(
    qt_app: QApplication,
    delete_qt_widget: Callable[[Any], None],
) -> None:
    for iteration in range(100):
        window = QMainWindow()
        central = QWidget(window)
        label = QLabel(f"label-{iteration}", central)
        window.setCentralWidget(central)
        window_destroyed = Event()
        label_destroyed = Event()
        window.destroyed.connect(lambda *_: window_destroyed.set())
        label.destroyed.connect(lambda *_: label_destroyed.set())

        delete_qt_widget(window)

        assert window_destroyed.is_set()
        assert label_destroyed.is_set()
        del label
        del central
        del window
        if iteration % 10 == 0:
            gc.collect()


def test_many_main_windows_are_deterministically_deleted(
    qt_app: QApplication,
    delete_qt_widget: Callable[[Any], None],
) -> None:
    for _ in range(50):
        window, service, runner = make_window(qt_app)
        destroyed = Event()
        window.destroyed.connect(lambda *_: destroyed.set())
        window_reference = weakref.ref(window)
        child_reference = weakref.ref(window.question_input)

        delete_qt_widget(window)

        assert destroyed.is_set()
        assert runner.active_task_count == 0
        del runner
        del service
        del window
        gc.collect()
        assert window_reference() is None
        assert child_reference() is None


def test_selecting_corpus_uses_uuid_item_data_and_renders_ordered_statuses(
    qt_app: QApplication,
) -> None:
    window, service, _ = make_window(qt_app)
    service.calls.clear()

    window.corpus_list.setCurrentRow(1)

    assert service.calls == [("inspect", "uuid-second")]
    assert window.selected_index_id() == "uuid-second"
    assert window.document_table.rowCount() == 1
    assert window.document_table.item(0, 0).text() == "other.pdf"
    assert window.document_table.item(0, 0).data(Qt.ItemDataRole.UserRole) == (
        "doc-other"
    )
    assert window.document_table.item(0, 1).text() == "UNKNOWN"
    assert window.document_table.item(0, 2).text() == "/sources/other.pdf"
    window.close()


def test_all_document_status_values_are_rendered_as_text(
    qt_app: QApplication,
) -> None:
    window, _, _ = make_window(qt_app)
    documents = tuple(
        make_stored_document(
            f"{status.value.lower()}.pdf",
            f"doc-{status.value.lower()}",
            position,
        )
        for position, status in enumerate(DocumentStatus)
    )
    inspections = tuple(
        make_inspection("uuid-first", document, status)
        for document, status in zip(documents, DocumentStatus, strict=True)
    )

    window._render_documents(inspections)

    displayed = tuple(
        window.document_table.item(row, 1).text()
        for row in range(window.document_table.rowCount())
    )
    assert displayed == tuple(status.value for status in DocumentStatus)
    window.close()


def test_create_cancel_performs_no_service_or_worker_call(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, service, runner = make_window(qt_app)
    service.calls.clear()
    initial_submissions = runner.submissions
    monkeypatch.setattr(window, "_choose_corpus_pdfs", lambda: ())

    window.create_corpus()

    assert service.calls == []
    assert runner.submissions == initial_submissions
    window.close()


def test_successful_create_refreshes_and_selects_new_corpus(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, service, _ = make_window(qt_app)
    selected = (Path("created.pdf"), Path("support.pdf"))
    monkeypatch.setattr(window, "_choose_corpus_pdfs", lambda: selected)
    service.calls.clear()

    window.create_corpus()

    assert ("create", selected) in service.calls
    assert window.selected_index_id() == "uuid-created"
    assert window.corpus_list.currentItem().text() == "created.pdf"
    assert ("inspect", "uuid-created") in service.calls
    window.close()


def test_add_cancel_and_success_keep_selected_corpus(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, service, _ = make_window(qt_app)
    service.calls.clear()
    monkeypatch.setattr(window, "_choose_single_pdf", lambda _: None)

    window.add_document()
    assert not any(call[0] == "add" for call in service.calls)

    monkeypatch.setattr(
        window,
        "_choose_single_pdf",
        lambda _: Path("added.pdf"),
    )
    window.add_document()

    assert ("add", "uuid-first", Path("added.pdf")) in service.calls
    assert window.selected_index_id() == "uuid-first"
    assert service.calls[-1] == ("inspect", "uuid-first")
    window.close()


def test_remove_confirmation_mentions_source_and_uses_durable_document_id(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window, service, _ = make_window(qt_app)
    window.document_table.setCurrentCell(1, 0)
    captured: list[str] = []

    def confirm(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        captured.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    service.calls.clear()

    window.remove_document()

    assert captured and "元のPDFファイルは削除されません" in captured[0]
    assert ("remove", "uuid-first", "doc-second") in service.calls
    window.close()


def test_reindex_and_refresh_use_selected_durable_ids(
    qt_app: QApplication,
) -> None:
    window, service, _ = make_window(qt_app)
    window.document_table.setCurrentCell(0, 0)
    service.calls.clear()

    window.reindex_document()
    window.refresh_documents()

    assert ("reindex", "uuid-first", "doc-first") in service.calls
    assert service.calls[-1] == ("inspect", "uuid-first")
    window.close()


def test_ask_is_disabled_without_corpus_and_whitespace_is_rejected(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubGuiService()
    service.corpora = []
    window, service, runner = make_window(qt_app, service=service)
    assert not window.ask_button.isEnabled()
    warnings: list[str] = []
    monkeypatch.setattr(window, "_show_warning", warnings.append)
    initial_submissions = runner.submissions

    window.ask_question()

    assert warnings == ["資料セットを選択してください。"]
    assert runner.submissions == initial_submissions
    window.close()

    window, service, runner = make_window(qt_app)
    warnings.clear()
    monkeypatch.setattr(window, "_show_warning", warnings.append)
    window.question_input.setText("  \n ")
    initial_submissions = runner.submissions
    window.ask_question()
    assert warnings == ["質問を入力してください。"]
    assert runner.submissions == initial_submissions
    assert not any(call[0] == "answer" for call in service.calls)
    window.close()


def test_successful_answer_renders_managed_citation_with_one_based_page(
    qt_app: QApplication,
) -> None:
    window, service, _ = make_window(qt_app)
    window.question_input.setText("Question?")
    service.calls.clear()

    window.ask_question()

    assert service.calls == [("answer", "uuid-first", "Question?")]
    assert window.answer_output.toPlainText() == "Grounded answer"
    sources = window.sources_output.toPlainText()
    assert "[1] first.pdf p.1" in sources
    assert "score: 0.876543" in sources
    assert "Grounded source text" in sources
    window.close()


def test_queued_work_disables_actions_and_success_restores_idle_state(
    qt_app: QApplication,
) -> None:
    service = StubGuiService()
    runner = QueuedTaskRunner()
    window, service, runner = make_window(qt_app, service=service, runner=runner)
    assert service.calls == [("list",)]
    assert len(runner.tasks) == 1
    assert not window.new_corpus_button.isEnabled()

    runner.succeed_next()

    assert service.calls[-1] == ("inspect", "uuid-first")
    assert window.new_corpus_button.isEnabled()
    assert window.statusBar().currentMessage() == "準備完了"

    window.question_input.setText("Question?")
    service.calls.clear()
    window.ask_question()
    assert service.calls == []
    assert len(runner.tasks) == 1
    assert not window.ask_button.isEnabled()
    runner.succeed_next()
    assert service.calls == [("answer", "uuid-first", "Question?")]
    assert window.ask_button.isEnabled()
    assert window.answer_output.toPlainText() == "Grounded answer"
    window.close()


def test_worker_failure_restores_ui_and_shows_error_without_clearing_question(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubGuiService()
    runner = QueuedTaskRunner()
    window, _, runner = make_window(qt_app, service=service, runner=runner)
    runner.succeed_next()
    errors: list[str] = []
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.question_input.setText("Keep this question")

    window.ask_question()
    runner.fail_next(RuntimeError("Ollama unavailable"))

    assert errors == ["Ollama unavailable"]
    assert window.question_input.text() == "Keep this question"
    assert window.ask_button.isEnabled()
    assert window.statusBar().currentMessage() == "準備完了"
    window.close()


def test_expensive_create_is_submitted_before_service_is_called(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = StubGuiService()
    runner = QueuedTaskRunner()
    window, service, runner = make_window(qt_app, service=service, runner=runner)
    runner.succeed_next()
    service.calls.clear()
    monkeypatch.setattr(
        window,
        "_choose_corpus_pdfs",
        lambda: (Path("created.pdf"),),
    )

    window.create_corpus()

    assert service.calls == []
    assert len(runner.tasks) == 1
    runner.succeed_next()
    assert service.calls[0] == ("create", (Path("created.pdf"),))
    runner.succeed_next()
    window.close()


def test_active_worker_defers_window_close_until_task_finishes(
    qt_app: QApplication,
) -> None:
    service = BlockingInspectionService()
    runner = QtTaskRunner()
    window = MainWindow(
        service,  # type: ignore[arg-type]
        task_runner=runner,
    )
    window.show()
    destroyed = Event()
    window.destroyed.connect(lambda *_: destroyed.set())
    assert service.started.wait(timeout=1)

    close_result = window.close()

    assert close_result is False
    assert window.isVisible()
    assert runner.active_task_count == 1
    service.release.set()
    process_events_until(qt_app, destroyed.is_set)
    assert runner.active_task_count == 0
    assert runner.thread_pool.activeThreadCount() == 0


def test_worker_failure_during_deferred_close_does_not_touch_closing_ui(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = BlockingInspectionService(fail=True)
    runner = QtTaskRunner()
    window = MainWindow(
        service,  # type: ignore[arg-type]
        task_runner=runner,
    )
    errors: list[str] = []
    destroyed = Event()
    window.destroyed.connect(lambda *_: destroyed.set())
    monkeypatch.setattr(window, "_show_error", errors.append)
    window.show()
    assert service.started.wait(timeout=1)

    assert window.close() is False
    service.release.set()
    process_events_until(qt_app, destroyed.is_set)

    assert errors == []
    assert runner.active_task_count == 0


def test_worker_completion_queued_immediately_before_close_is_safe(
    qt_app: QApplication,
) -> None:
    service = BlockingInspectionService()
    runner = QtTaskRunner()
    window = MainWindow(
        service,  # type: ignore[arg-type]
        task_runner=runner,
    )
    window.show()
    destroyed = Event()
    window.destroyed.connect(lambda *_: destroyed.set())
    assert service.started.wait(timeout=1)
    service.release.set()
    assert service.returned.wait(timeout=1)

    assert window.close() is False
    process_events_until(qt_app, destroyed.is_set)

    assert runner.active_task_count == 0
    assert runner.thread_pool.activeThreadCount() == 0


def test_application_exit_shutdown_waits_for_active_window_worker(
    qt_app: QApplication,
) -> None:
    service = BlockingInspectionService(delay=0.05)
    service.release.set()
    runner = QtTaskRunner()
    window = MainWindow(
        service,  # type: ignore[arg-type]
        task_runner=runner,
    )
    assert service.started.wait(timeout=1)

    window.shutdown_for_application_exit()
    qt_app.processEvents()

    assert service.returned.is_set()
    assert runner.active_task_count == 0
    assert runner.thread_pool.activeThreadCount() == 0
    window.close()
