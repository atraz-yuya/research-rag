import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths

from research_rag import gui_app
from research_rag.gui_settings import GuiRuntimeSettings, GuiSettingsStore
from research_rag.index_store import SCHEMA_VERSION


class FakeClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url


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


def test_default_settings_path_is_separate_and_beside_database(
    tmp_path: Path,
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    application_data = tmp_path / "ResearchRAG"
    monkeypatch.setattr(
        QStandardPaths,
        "writableLocation",
        lambda _: str(application_data),
    )

    assert gui_app.default_settings_path() == application_data / "settings.ini"
    assert gui_app.default_settings_path() != gui_app.default_database_path()


def test_create_gui_service_loads_settings_before_building_shared_client(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "data" / "indexes.sqlite3"
    settings_path = tmp_path / "preferences" / "settings.ini"
    persisted = GuiRuntimeSettings(
        embedding_model="persisted-embedding",
        generation_model="persisted-generation",
        top_k=11,
        ollama_base_url="https://ollama.example.test:11434",
    )
    GuiSettingsStore(settings_path).save(persisted)
    factory_calls: list[str] = []

    def client_factory(base_url: str):  # type: ignore[no-untyped-def]
        factory_calls.append(base_url)
        return FakeClient(base_url)

    service = gui_app.create_gui_service(
        db_path=db_path,
        settings_path=settings_path,
        client_factory=client_factory,  # type: ignore[arg-type]
    )

    assert service.runtime_settings == persisted
    assert factory_calls == [persisted.ollama_base_url]
    assert service.client is service.manager.client
    assert SCHEMA_VERSION == 3


def test_persisted_settings_survive_service_reconstruction(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "app" / "indexes.sqlite3"
    settings_path = tmp_path / "app" / "settings.ini"
    selected = GuiRuntimeSettings(
        "restart-embedding",
        "restart-generation",
        5,
        "http://restart.example.test:11434",
    )
    GuiSettingsStore(settings_path).save(selected)

    first = gui_app.create_gui_service(
        db_path=db_path,
        settings_path=settings_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
    )
    second = gui_app.create_gui_service(
        db_path=db_path,
        settings_path=settings_path,
        client_factory=FakeClient,  # type: ignore[arg-type]
    )

    assert first.runtime_settings == selected
    assert second.runtime_settings == selected
    assert settings_path.parent == db_path.parent
