from __future__ import annotations

import sys
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from .gui_service import RagGuiService
from .gui_settings import (
    GuiRuntimeSettings,
    GuiSettingsStore,
)
from .index_store import SQLiteRagIndexStore
from .main_window import MainWindow
from .ollama_client import OllamaClient


APPLICATION_NAME = "ResearchRAG"
DATABASE_FILENAME = "indexes.sqlite3"
SETTINGS_FILENAME = "settings.ini"


def configure_application_identity() -> None:
    """Set stable names before resolving Qt application-data locations."""
    QCoreApplication.setOrganizationName("")
    QCoreApplication.setApplicationName(APPLICATION_NAME)


def default_database_path() -> Path:
    """Resolve the persistent GUI DB beneath Qt's application-data location."""
    configure_application_identity()
    location = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppDataLocation
    )
    if not location:
        raise RuntimeError("Qt application data location is unavailable")
    return Path(location) / DATABASE_FILENAME


def default_settings_path() -> Path:
    """Resolve GUI preferences beside, but separate from, the corpus DB."""
    return default_database_path().with_name(SETTINGS_FILENAME)


def create_gui_service(
    *,
    db_path: Path | None = None,
    settings_path: Path | None = None,
    settings_store: GuiSettingsStore | None = None,
    settings: GuiRuntimeSettings | None = None,
    client: OllamaClient | None = None,
    client_factory: Callable[[str], OllamaClient] | None = None,
) -> RagGuiService:
    """Load preferences, then construct an initialized GUI service."""
    selected_db_path = (
        db_path if db_path is not None else default_database_path()
    )
    selected_settings_store = settings_store or GuiSettingsStore(
        settings_path
        if settings_path is not None
        else selected_db_path.with_name(SETTINGS_FILENAME)
    )
    runtime_settings = (
        settings if settings is not None else selected_settings_store.load()
    )
    store = SQLiteRagIndexStore(selected_db_path)
    service = RagGuiService(
        store,
        client=client,
        runtime_settings=runtime_settings,
        client_factory=client_factory,
    )
    service.initialize()
    return service


def main(argv: Sequence[str] | None = None) -> int:
    """Launch one QApplication and one Research RAG main window."""
    application = QApplication.instance()
    if application is None:
        application = QApplication(
            list(argv) if argv is not None else list(sys.argv)
        )
    configure_application_identity()

    try:
        settings_store = GuiSettingsStore(default_settings_path())
        service = create_gui_service(settings_store=settings_store)
    except Exception as exc:
        traceback.print_exc()
        QMessageBox.critical(
            None,
            "Research RAG 起動エラー",
            f"保存データベースを初期化できませんでした。\n\n{exc}",
        )
        return 1

    window = MainWindow(service, settings_store=settings_store)
    application.aboutToQuit.connect(window.shutdown_for_application_exit)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
