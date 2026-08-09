from __future__ import annotations

import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths
from PySide6.QtWidgets import QApplication, QMessageBox

from .gui_service import RagGuiService
from .index_store import SQLiteRagIndexStore
from .main_window import MainWindow
from .ollama_client import OllamaClient


APPLICATION_NAME = "ResearchRAG"
DATABASE_FILENAME = "indexes.sqlite3"


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


def create_gui_service(
    *,
    db_path: Path | None = None,
    client: OllamaClient | None = None,
) -> RagGuiService:
    """Construct and initialize the GUI service with an injectable DB path."""
    store = SQLiteRagIndexStore(
        db_path if db_path is not None else default_database_path()
    )
    service = RagGuiService(store, client=client)
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
        service = create_gui_service()
    except Exception as exc:
        traceback.print_exc()
        QMessageBox.critical(
            None,
            "Research RAG 起動エラー",
            f"保存データベースを初期化できませんでした。\n\n{exc}",
        )
        return 1

    window = MainWindow(service)
    application.aboutToQuit.connect(window.shutdown_for_application_exit)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
