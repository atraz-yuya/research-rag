from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QLabel

from research_rag import gui_settings
from research_rag.defaults import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_TOP_K,
)
from research_rag.gui_settings import (
    GuiRuntimeSettings,
    GuiSettingsError,
    GuiSettingsStore,
    default_gui_runtime_settings,
    validate_gui_runtime_settings,
)
from research_rag.gui_settings_dialog import GuiSettingsDialog
from research_rag.ollama_client import DEFAULT_OLLAMA_BASE_URL


def custom_settings() -> GuiRuntimeSettings:
    return GuiRuntimeSettings(
        embedding_model="custom-embedding",
        generation_model="custom-generation",
        top_k=7,
        ollama_base_url="https://ollama.example.test:11434",
    )


def test_defaults_match_shared_production_constants_exactly() -> None:
    assert default_gui_runtime_settings() == GuiRuntimeSettings(
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        generation_model=DEFAULT_GENERATION_MODEL,
        top_k=DEFAULT_TOP_K,
        ollama_base_url=DEFAULT_OLLAMA_BASE_URL,
    )


def test_first_run_store_returns_defaults_without_creating_file(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "isolated" / "settings.ini"

    loaded = GuiSettingsStore(settings_path).load()

    assert loaded == default_gui_runtime_settings()
    assert not settings_path.exists()


def test_save_load_round_trip_survives_new_store_instance(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "injected" / "settings.ini"
    store = GuiSettingsStore(settings_path)

    store.save(custom_settings())
    loaded = GuiSettingsStore(settings_path).load()

    assert loaded == custom_settings()
    assert settings_path.exists()
    assert settings_path.is_relative_to(tmp_path)
    assert tuple(settings_path.parent.iterdir()) == (settings_path,)


def test_validation_trims_models_and_normalizes_trailing_url_slashes() -> None:
    normalized = validate_gui_runtime_settings(
        GuiRuntimeSettings(
            embedding_model="  embedding-model  ",
            generation_model=" generation-model\n",
            top_k=5,
            ollama_base_url="  http://localhost:11434///  ",
        )
    )

    assert normalized == GuiRuntimeSettings(
        embedding_model="embedding-model",
        generation_model="generation-model",
        top_k=5,
        ollama_base_url="http://localhost:11434",
    )


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (
            GuiRuntimeSettings(" ", "generation", 3, "http://localhost"),
            "embedding_model",
        ),
        (
            GuiRuntimeSettings("embedding", "\n", 3, "http://localhost"),
            "generation_model",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 0, "http://localhost"),
            "top_k",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", -1, "http://localhost"),
            "top_k",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 101, "http://localhost"),
            "top_k",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 3, " "),
            "ollama_base_url",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 3, "localhost:11434"),
            "http or https",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 3, "ftp://host"),
            "http or https",
        ),
        (
            GuiRuntimeSettings("embedding", "generation", 3, "http://"),
            "valid host",
        ),
        (
            GuiRuntimeSettings(
                "embedding",
                "generation",
                3,
                "http://localhost:bad-port",
            ),
            "valid URL",
        ),
    ],
)
def test_invalid_runtime_settings_are_rejected(
    settings: GuiRuntimeSettings,
    message: str,
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        validate_gui_runtime_settings(settings)


def test_malformed_persisted_snapshot_falls_back_wholly_to_defaults(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.ini"
    persisted = QSettings(str(settings_path), QSettings.Format.IniFormat)
    persisted.setValue("runtime/embedding_model", "custom-model")
    persisted.setValue("runtime/generation_model", "custom-generation")
    persisted.setValue("runtime/top_k", "not-an-integer")
    persisted.setValue("runtime/ollama_base_url", "not-a-url")
    persisted.sync()
    del persisted

    loaded = GuiSettingsStore(settings_path).load()

    assert loaded == default_gui_runtime_settings()


def test_atomic_save_failure_preserves_previous_persisted_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings_path = tmp_path / "settings.ini"
    store = GuiSettingsStore(settings_path)
    previous = default_gui_runtime_settings()
    store.save(previous)

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError("read-only settings location")

    monkeypatch.setattr(gui_settings.os, "replace", fail_replace)

    with pytest.raises(GuiSettingsError, match="Failed to save"):
        store.save(custom_settings())

    assert GuiSettingsStore(settings_path).load() == previous


def test_reset_to_defaults_persists_defaults(tmp_path: Path) -> None:
    store = GuiSettingsStore(tmp_path / "settings.ini")
    store.save(custom_settings())

    reset = store.reset_to_defaults()

    assert reset == default_gui_runtime_settings()
    assert store.load() == default_gui_runtime_settings()


def test_dialog_initially_displays_current_values(qt_app) -> None:  # type: ignore[no-untyped-def]
    dialog = GuiSettingsDialog(custom_settings())

    assert dialog.embedding_model_input.text() == "custom-embedding"
    assert dialog.generation_model_input.text() == "custom-generation"
    assert dialog.top_k_input.value() == 7
    assert dialog.ollama_url_input.text() == (
        "https://ollama.example.test:11434"
    )
    note = dialog.findChild(QLabel, "embeddingModelNote")
    assert note is not None
    assert "新しい資料セット" in note.text()
    assert "既存の資料セット" in note.text()
    dialog.close()


def test_invalid_dialog_input_stays_open_and_does_not_change_snapshot(
    qt_app,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = custom_settings()
    dialog = GuiSettingsDialog(original)
    errors: list[str] = []
    monkeypatch.setattr(dialog, "_show_validation_error", errors.append)
    dialog.open()
    dialog.embedding_model_input.setText("   ")

    dialog.accept()

    assert dialog.isVisible()
    assert errors == ["embedding_model must not be empty"]
    assert dialog.selected_settings == original
    dialog.close()


def test_reset_button_only_edits_fields_until_ok(qt_app) -> None:  # type: ignore[no-untyped-def]
    original = custom_settings()
    dialog = GuiSettingsDialog(original)

    dialog.reset_fields_to_defaults()

    defaults = default_gui_runtime_settings()
    assert dialog.embedding_model_input.text() == defaults.embedding_model
    assert dialog.generation_model_input.text() == defaults.generation_model
    assert dialog.top_k_input.value() == defaults.top_k
    assert dialog.ollama_url_input.text() == defaults.ollama_base_url
    assert dialog.selected_settings == original
    dialog.close()
