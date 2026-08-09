import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths

from research_rag import gui_app


def test_default_database_path_uses_qt_application_data_location(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    application_data = tmp_path / "outside-repository" / "ResearchRAG"
    monkeypatch.setattr(
        QStandardPaths,
        "writableLocation",
        lambda _: str(application_data),
    )

    path = gui_app.default_database_path()

    assert path == application_data / "indexes.sqlite3"
    assert gui_app.APPLICATION_NAME == "ResearchRAG"
    assert QCoreApplication.organizationName() == ""
    assert QCoreApplication.applicationName() == "ResearchRAG"


def test_gui_service_accepts_injected_tmp_database_path(tmp_path: Path) -> None:
    db_path = tmp_path / "gui" / "indexes.sqlite3"

    service = gui_app.create_gui_service(db_path=db_path)

    assert service.store.db_path == db_path
    assert db_path.exists()
    assert service.list_corpora() == ()
