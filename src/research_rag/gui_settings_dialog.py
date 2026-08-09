from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .gui_settings import (
    MAX_GUI_TOP_K,
    GuiRuntimeSettings,
    default_gui_runtime_settings,
    validate_gui_runtime_settings,
)


class GuiSettingsDialog(QDialog):
    """Small modal editor for one complete runtime-settings snapshot."""

    def __init__(
        self,
        settings: GuiRuntimeSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._selected_settings = validate_gui_runtime_settings(settings)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("設定")
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.embedding_model_input = QLineEdit(self)
        self.embedding_model_input.setObjectName("embeddingModelInput")
        self.generation_model_input = QLineEdit(self)
        self.generation_model_input.setObjectName("generationModelInput")
        self.top_k_input = QSpinBox(self)
        self.top_k_input.setObjectName("topKInput")
        self.top_k_input.setRange(1, MAX_GUI_TOP_K)
        self.ollama_url_input = QLineEdit(self)
        self.ollama_url_input.setObjectName("ollamaUrlInput")
        form.addRow("Embedding model", self.embedding_model_input)
        form.addRow("Generation model", self.generation_model_input)
        form.addRow("Top-K", self.top_k_input)
        form.addRow("Ollama URL", self.ollama_url_input)
        layout.addLayout(form)

        note = QLabel(
            "Embedding modelの変更は新しい資料セットの作成時だけ適用されます。"
            "既存の資料セットは保存済みのembedding modelを使い続けます。",
            self,
        )
        note.setObjectName("embeddingModelNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.reset_button = QPushButton("デフォルトに戻す", self)
        self.reset_button.setObjectName("resetSettingsButton")
        layout.addWidget(self.reset_button)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        layout.addWidget(self.button_box)

        self.reset_button.clicked.connect(self.reset_fields_to_defaults)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self._populate_fields(self._selected_settings)

    @property
    def selected_settings(self) -> GuiRuntimeSettings:
        return self._selected_settings

    def accept(self) -> None:
        try:
            selected = validate_gui_runtime_settings(
                GuiRuntimeSettings(
                    embedding_model=self.embedding_model_input.text(),
                    generation_model=self.generation_model_input.text(),
                    top_k=self.top_k_input.value(),
                    ollama_base_url=self.ollama_url_input.text(),
                )
            )
        except (TypeError, ValueError) as exc:
            self._show_validation_error(str(exc))
            return
        self._selected_settings = selected
        super().accept()

    def reset_fields_to_defaults(self) -> None:
        """Edit fields only; persistence still requires pressing OK."""
        self._populate_fields(default_gui_runtime_settings())

    def _populate_fields(self, settings: GuiRuntimeSettings) -> None:
        self.embedding_model_input.setText(settings.embedding_model)
        self.generation_model_input.setText(settings.generation_model)
        self.top_k_input.setValue(settings.top_k)
        self.ollama_url_input.setText(settings.ollama_base_url)

    def _show_validation_error(self, message: str) -> None:
        QMessageBox.warning(self, "設定エラー", message)
