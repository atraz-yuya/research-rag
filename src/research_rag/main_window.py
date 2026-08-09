from __future__ import annotations

import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .document_manager import DocumentInspection
from .gui_service import RagGuiService, format_corpus_label
from .gui_settings import GuiSettingsStore
from .gui_settings_dialog import GuiSettingsDialog
from .gui_worker import QtTaskRunner, TaskRunner
from .index_store import StoredRagIndexMetadata
from .models import RagAnswer


_CORPUS_DISPLAY_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1
_CORPUS_EMBEDDING_MODEL_ROLE = int(Qt.ItemDataRole.UserRole) + 2


class MainWindow(QMainWindow):
    """Thin Qt Widgets adapter over RagGuiService and a background task runner."""

    def __init__(
        self,
        service: RagGuiService,
        *,
        task_runner: TaskRunner | None = None,
        settings_store: GuiSettingsStore | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self.task_runner = (
            task_runner if task_runner is not None else QtTaskRunner(self)
        )
        self.settings_store = settings_store
        self._settings_dialog: GuiSettingsDialog | None = None
        self._busy = False
        self._closing = False

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Research RAG")
        self.resize(1050, 760)
        self._build_ui()
        self._connect_signals()
        self.refresh_corpora()

    def _build_ui(self) -> None:
        central = QWidget(self)
        root_layout = QVBoxLayout(central)

        top_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        top_splitter.addWidget(self._build_corpus_panel())
        top_splitter.addWidget(self._build_document_panel())
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 3)
        root_layout.addWidget(top_splitter, stretch=2)
        root_layout.addWidget(self._build_question_panel(), stretch=3)

        self.setCentralWidget(central)
        self.statusBar().showMessage("準備完了")

    def _build_corpus_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("保存済み資料セット", panel))
        self.corpus_list = QListWidget(panel)
        self.corpus_list.setObjectName("corpusList")
        layout.addWidget(self.corpus_list)
        self.corpus_embedding_model_label = QLabel(
            "使用中のEmbedding model: —",
            panel,
        )
        self.corpus_embedding_model_label.setObjectName(
            "corpusEmbeddingModelLabel"
        )
        self.corpus_embedding_model_label.setWordWrap(True)
        layout.addWidget(self.corpus_embedding_model_label)
        self.new_corpus_button = QPushButton("新しい資料セット", panel)
        self.new_corpus_button.setObjectName("newCorpusButton")
        layout.addWidget(self.new_corpus_button)
        corpus_actions = QHBoxLayout()
        self.rename_corpus_button = QPushButton("名前を変更", panel)
        self.rename_corpus_button.setObjectName("renameCorpusButton")
        self.delete_corpus_button = QPushButton("資料セットを削除", panel)
        self.delete_corpus_button.setObjectName("deleteCorpusButton")
        corpus_actions.addWidget(self.rename_corpus_button)
        corpus_actions.addWidget(self.delete_corpus_button)
        layout.addLayout(corpus_actions)
        self.settings_button = QPushButton("設定", panel)
        self.settings_button.setObjectName("settingsButton")
        layout.addWidget(self.settings_button)
        return panel

    def _build_document_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.addWidget(QLabel("選択中の資料セット / 資料", panel))

        self.document_table = QTableWidget(0, 3, panel)
        self.document_table.setObjectName("documentTable")
        self.document_table.setHorizontalHeaderLabels(
            ["資料名", "状態", "保存元"]
        )
        self.document_table.horizontalHeader().setStretchLastSection(True)
        self.document_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.document_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.document_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        layout.addWidget(self.document_table)

        actions = QHBoxLayout()
        self.add_document_button = QPushButton("資料を追加", panel)
        self.reindex_button = QPushButton("再インデックス", panel)
        self.remove_button = QPushButton("削除", panel)
        self.refresh_button = QPushButton("状態を更新", panel)
        for button in (
            self.add_document_button,
            self.reindex_button,
            self.remove_button,
            self.refresh_button,
        ):
            actions.addWidget(button)
        layout.addLayout(actions)
        return panel

    def _build_question_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        question_layout = QHBoxLayout()
        self.question_input = QLineEdit(panel)
        self.question_input.setObjectName("questionInput")
        self.question_input.setPlaceholderText("選択中の資料セットへの質問")
        self.ask_button = QPushButton("質問する", panel)
        self.ask_button.setObjectName("askButton")
        question_layout.addWidget(QLabel("質問", panel))
        question_layout.addWidget(self.question_input, stretch=1)
        question_layout.addWidget(self.ask_button)
        layout.addLayout(question_layout)

        answer_layout = QFormLayout()
        self.answer_output = QPlainTextEdit(panel)
        self.answer_output.setObjectName("answerOutput")
        self.answer_output.setReadOnly(True)
        self.sources_output = QPlainTextEdit(panel)
        self.sources_output.setObjectName("sourcesOutput")
        self.sources_output.setReadOnly(True)
        answer_layout.addRow("回答", self.answer_output)
        answer_layout.addRow("参照", self.sources_output)
        layout.addLayout(answer_layout)
        return panel

    def _connect_signals(self) -> None:
        self.corpus_list.currentItemChanged.connect(
            self._on_corpus_selection_changed
        )
        self.document_table.itemSelectionChanged.connect(
            self._update_action_states
        )
        self.question_input.textChanged.connect(self._update_action_states)
        self.question_input.returnPressed.connect(self.ask_question)
        self.new_corpus_button.clicked.connect(self.create_corpus)
        self.rename_corpus_button.clicked.connect(self.rename_corpus)
        self.delete_corpus_button.clicked.connect(self.delete_corpus)
        self.settings_button.clicked.connect(self.open_settings)
        self.add_document_button.clicked.connect(self.add_document)
        self.reindex_button.clicked.connect(self.reindex_document)
        self.remove_button.clicked.connect(self.remove_document)
        self.refresh_button.clicked.connect(self.refresh_documents)
        self.ask_button.clicked.connect(self.ask_question)

    def refresh_corpora(self, select_index_id: str | None = None) -> None:
        """Reload lightweight metadata and asynchronously inspect selection."""
        if self._closing:
            return
        previous_id = select_index_id or self.selected_index_id()
        try:
            corpora = self.service.list_corpora()
        except Exception as exc:
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            self._show_error(str(exc))
            self._update_action_states()
            return

        self._populate_corpora(corpora, previous_id)
        if self.selected_index_id() is not None:
            self.refresh_documents()
        else:
            self._clear_selected_corpus_state()
            self._update_action_states()

    def _populate_corpora(
        self,
        corpora: Sequence[StoredRagIndexMetadata],
        preferred_index_id: str | None,
    ) -> None:
        self.corpus_list.blockSignals(True)
        self.corpus_list.clear()
        selected_row = -1
        for row, metadata in enumerate(corpora):
            item = QListWidgetItem(format_corpus_label(metadata))
            item.setData(Qt.ItemDataRole.UserRole, metadata.index_id)
            item.setData(
                _CORPUS_DISPLAY_NAME_ROLE,
                metadata.display_name,
            )
            item.setData(
                _CORPUS_EMBEDDING_MODEL_ROLE,
                metadata.embedding_model,
            )
            item.setToolTip(
                f"資料数: {len(metadata.documents)} / "
                f"Chunk数: {metadata.chunk_count} / "
                f"Embedding model: {metadata.embedding_model}"
            )
            self.corpus_list.addItem(item)
            if metadata.index_id == preferred_index_id:
                selected_row = row
        if selected_row < 0 and self.corpus_list.count() > 0:
            selected_row = 0
        self.corpus_list.setCurrentRow(selected_row)
        self.corpus_list.blockSignals(False)
        self._update_selected_corpus_info()

    def selected_index_id(self) -> str | None:
        item = self.corpus_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def selected_document_id(self) -> str | None:
        row = self.document_table.currentRow()
        if row < 0:
            return None
        item = self.document_table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def _on_corpus_selection_changed(self) -> None:
        self._update_selected_corpus_info()
        self.answer_output.clear()
        self.sources_output.clear()
        self.refresh_documents()

    def refresh_documents(self) -> None:
        index_id = self.selected_index_id()
        if index_id is None:
            self._clear_documents()
            self._update_action_states()
            return
        self._run_task(
            lambda: self.service.inspect_documents(index_id),
            on_success=self._render_documents,
            busy_message="資料の状態を確認中...",
        )

    def _render_documents(
        self,
        inspections: Sequence[DocumentInspection],
    ) -> None:
        self.document_table.setRowCount(0)
        for inspection in inspections:
            row = self.document_table.rowCount()
            self.document_table.insertRow(row)
            name_item = QTableWidgetItem(inspection.document_name)
            name_item.setData(
                Qt.ItemDataRole.UserRole,
                inspection.document_id,
            )
            status_item = QTableWidgetItem(inspection.status.value)
            path_item = QTableWidgetItem(str(inspection.source_path))
            path_item.setToolTip(str(inspection.source_path))
            self.document_table.setItem(row, 0, name_item)
            self.document_table.setItem(row, 1, status_item)
            self.document_table.setItem(row, 2, path_item)
        self.document_table.resizeColumnsToContents()
        self._update_action_states()

    def _clear_documents(self) -> None:
        self.document_table.setRowCount(0)

    def _clear_selected_corpus_state(self) -> None:
        self._clear_documents()
        self._update_selected_corpus_info()
        self.answer_output.clear()
        self.sources_output.clear()

    def create_corpus(self) -> None:
        selected_paths = self._choose_corpus_pdfs()
        if not selected_paths:
            return
        display_name = self._choose_corpus_name(
            title="資料セット名",
            initial_value=selected_paths[0].stem,
        )
        if display_name is None:
            return
        clean_display_name = display_name.strip()
        if not clean_display_name:
            self._show_warning("資料セット名を入力してください。")
            return

        self._run_task(
            lambda: self.service.create_corpus(
                selected_paths,
                display_name=clean_display_name,
            ),
            on_success=lambda _: None,
            after_success=lambda metadata: self.refresh_corpora(metadata.index_id),
            busy_message="資料セットを作成中...",
        )

    def rename_corpus(self) -> None:
        index_id = self.selected_index_id()
        item = self.corpus_list.currentItem()
        if index_id is None or item is None:
            self._show_warning("資料セットを選択してください。")
            return
        display_name = self._choose_corpus_name(
            title="資料セット名を変更",
            initial_value=item.text(),
        )
        if display_name is None:
            return
        clean_display_name = display_name.strip()
        if not clean_display_name:
            self._show_warning("資料セット名を入力してください。")
            return
        current_display_name = item.data(_CORPUS_DISPLAY_NAME_ROLE)
        if current_display_name == clean_display_name:
            return
        self._run_task(
            lambda: self.service.rename_corpus(index_id, clean_display_name),
            on_success=lambda _: None,
            after_success=lambda _: self.refresh_corpora(index_id),
            busy_message="資料セット名を変更中...",
        )

    def delete_corpus(self) -> None:
        index_id = self.selected_index_id()
        item = self.corpus_list.currentItem()
        if index_id is None or item is None:
            self._show_warning("資料セットを選択してください。")
            return
        if not self._confirm_corpus_deletion(item.text()):
            return
        self._run_task(
            lambda: self.service.delete_corpus(index_id),
            on_success=lambda _: None,
            after_success=lambda _: self._after_corpus_deleted(),
            busy_message="資料セットを削除中...",
        )

    def _after_corpus_deleted(self) -> None:
        self._clear_selected_corpus_state()
        self.refresh_corpora()

    def open_settings(self) -> None:
        """Open a non-blocking modal editor while no task is active."""
        if self._busy or self._closing:
            return
        if self.settings_store is None:
            self._show_error("設定の保存先が構成されていません。")
            return
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return

        dialog = GuiSettingsDialog(self.service.runtime_settings, self)
        self._settings_dialog = dialog
        dialog.accepted.connect(self._apply_open_settings)
        dialog.finished.connect(self._release_settings_dialog)
        dialog.open()

    def _apply_open_settings(self) -> None:
        dialog = self._settings_dialog
        settings_store = self.settings_store
        if self._closing or dialog is None or settings_store is None:
            return
        requested = dialog.selected_settings
        previous = self.service.runtime_settings
        if requested == previous:
            return
        previous_client = self.service.client
        try:
            applied = self.service.apply_runtime_settings(requested)
            try:
                settings_store.save(applied)
            except Exception:
                self.service.restore_runtime_settings(
                    previous,
                    previous_client,
                )
                raise
        except Exception as exc:
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            self._show_error(str(exc))
            return
        self.statusBar().showMessage("設定を保存しました")

    def _release_settings_dialog(self, _result: int = 0) -> None:
        self._settings_dialog = None

    def _update_selected_corpus_info(self) -> None:
        item = self.corpus_list.currentItem()
        if item is None:
            model = "—"
        else:
            value = item.data(_CORPUS_EMBEDDING_MODEL_ROLE)
            model = str(value) if value else "—"
        self.corpus_embedding_model_label.setText(
            f"使用中のEmbedding model: {model}"
        )

    def add_document(self) -> None:
        index_id = self.selected_index_id()
        if index_id is None:
            self._show_warning("資料セットを選択してください。")
            return
        pdf_path = self._choose_single_pdf("追加するPDFを選択")
        if pdf_path is None:
            return
        self._run_task(
            lambda: self.service.add_document(index_id, pdf_path),
            on_success=lambda _: None,
            after_success=lambda _: self.refresh_corpora(index_id),
            busy_message="資料を追加中...",
        )

    def remove_document(self) -> None:
        index_id = self.selected_index_id()
        document_id = self.selected_document_id()
        if index_id is None or document_id is None:
            self._show_warning("削除する資料を選択してください。")
            return
        document_name = self.document_table.item(
            self.document_table.currentRow(),
            0,
        ).text()
        if not self._confirm_document_removal(document_name):
            return
        self._run_task(
            lambda: self.service.remove_document(index_id, document_id),
            on_success=lambda _: None,
            after_success=lambda _: self.refresh_corpora(index_id),
            busy_message="資料を削除中...",
        )

    def reindex_document(self) -> None:
        index_id = self.selected_index_id()
        document_id = self.selected_document_id()
        if index_id is None or document_id is None:
            self._show_warning("再インデックスする資料を選択してください。")
            return
        self._run_task(
            lambda: self.service.reindex_document(index_id, document_id),
            on_success=lambda _: None,
            after_success=lambda _: self.refresh_corpora(index_id),
            busy_message="再インデックス中...",
        )

    def ask_question(self) -> None:
        index_id = self.selected_index_id()
        if index_id is None:
            self._show_warning("資料セットを選択してください。")
            return
        question = self.question_input.text().strip()
        if not question:
            self._show_warning("質問を入力してください。")
            return
        self._run_task(
            lambda: self.service.answer(index_id, question),
            on_success=self._render_answer,
            busy_message="回答を生成中...",
        )

    def _render_answer(self, answer: RagAnswer) -> None:
        self.answer_output.setPlainText(answer.text)
        blocks = []
        for source in answer.sources:
            blocks.append(
                "\n".join(
                    [
                        f"[{source.rank}] {source.chunk.document_name} "
                        f"p.{source.chunk.page_number}",
                        f"score: {source.score:.6f}",
                        source.chunk.text,
                    ]
                )
            )
        self.sources_output.setPlainText("\n\n".join(blocks))

    def _run_task(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        after_success: Callable[[Any], None] | None = None,
        busy_message: str,
    ) -> None:
        if self._busy or self._closing:
            return
        completed = False
        task_result: Any = None
        self._set_busy(True, busy_message)

        def handle_success(result: Any) -> None:
            nonlocal completed, task_result
            if self._closing:
                return
            try:
                on_success(result)
            except Exception as exc:
                traceback.print_exception(type(exc), exc, exc.__traceback__)
                self._show_error(str(exc))
            else:
                completed = True
                task_result = result

        def handle_error(error: Exception) -> None:
            if not self._closing:
                self._show_error(str(error))

        def handle_finished() -> None:
            if self._closing:
                return
            self._set_busy(False, "準備完了")
            if completed and after_success is not None:
                after_success(task_result)

        try:
            self.task_runner.submit(
                operation,
                on_success=handle_success,
                on_error=handle_error,
                on_finished=handle_finished,
            )
        except Exception as exc:
            traceback.print_exception(type(exc), exc, exc.__traceback__)
            self._set_busy(False, "準備完了")
            self._show_error(str(exc))

    def _set_busy(self, busy: bool, message: str) -> None:
        self._busy = busy
        self.statusBar().showMessage(message)
        if busy:
            for widget in self._interactive_widgets():
                widget.setEnabled(False)
        else:
            self._update_action_states()

    def _interactive_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.corpus_list,
            self.document_table,
            self.new_corpus_button,
            self.rename_corpus_button,
            self.delete_corpus_button,
            self.settings_button,
            self.add_document_button,
            self.reindex_button,
            self.remove_button,
            self.refresh_button,
            self.question_input,
            self.ask_button,
        )

    def _update_action_states(self) -> None:
        if self._busy or self._closing:
            return
        for widget in (self.corpus_list, self.document_table, self.question_input):
            widget.setEnabled(True)
        has_corpus = self.selected_index_id() is not None
        has_document = self.selected_document_id() is not None
        has_question = bool(self.question_input.text().strip())
        self.new_corpus_button.setEnabled(True)
        self.settings_button.setEnabled(self.settings_store is not None)
        self.rename_corpus_button.setEnabled(has_corpus)
        self.delete_corpus_button.setEnabled(has_corpus)
        self.add_document_button.setEnabled(has_corpus)
        self.refresh_button.setEnabled(has_corpus)
        self.reindex_button.setEnabled(has_corpus and has_document)
        self.remove_button.setEnabled(has_corpus and has_document)
        self.ask_button.setEnabled(has_corpus and has_question)

    def _choose_corpus_pdfs(self) -> tuple[Path, ...]:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "資料セットへ追加するPDFを選択",
            "",
            "PDF files (*.pdf)",
        )
        return tuple(Path(filename) for filename in filenames)

    def _choose_single_pdf(self, title: str) -> Path | None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            title,
            "",
            "PDF files (*.pdf)",
        )
        return Path(filename) if filename else None

    def _choose_corpus_name(
        self,
        *,
        title: str,
        initial_value: str,
    ) -> str | None:
        value, accepted = QInputDialog.getText(
            self,
            title,
            "名前",
            QLineEdit.EchoMode.Normal,
            initial_value,
        )
        return value if accepted else None

    def _confirm_document_removal(self, document_name: str) -> bool:
        result = QMessageBox.question(
            self,
            "資料を削除",
            f"{document_name} を資料セットから削除しますか？\n\n"
            "元のPDFファイルは削除されません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result is QMessageBox.StandardButton.Yes

    def _confirm_corpus_deletion(self, corpus_name: str) -> bool:
        result = QMessageBox.question(
            self,
            "資料セットを削除",
            f"{corpus_name} の索引データをすべて削除しますか？\n\n"
            "アプリ内の文書・Chunk・embeddingが削除されます。\n"
            "元のPDFファイルは削除されません。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result is QMessageBox.StandardButton.Yes

    def _show_warning(self, message: str) -> None:
        QMessageBox.warning(self, "確認", message)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "エラー", message)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Delay window destruction until all finite worker tasks finish."""
        if self.task_runner.active_task_count:
            if not self._closing:
                self._closing = True
                self._set_busy(True, "実行中の処理が終わるまで待機中...")
                self.task_runner.request_shutdown(self.close)
            event.ignore()
            return

        self._closing = True
        self.task_runner.shutdown(wait=True)
        super().closeEvent(event)

    def shutdown_for_application_exit(self) -> None:
        """Synchronously finish workers before QApplication tears down Qt."""
        self._closing = True
        self.task_runner.shutdown(wait=True)
