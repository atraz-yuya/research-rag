from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QSettings

from .defaults import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_TOP_K,
)
from .ollama_client import DEFAULT_OLLAMA_BASE_URL


MAX_GUI_TOP_K = 100

_EMBEDDING_MODEL_KEY = "runtime/embedding_model"
_GENERATION_MODEL_KEY = "runtime/generation_model"
_TOP_K_KEY = "runtime/top_k"
_OLLAMA_BASE_URL_KEY = "runtime/ollama_base_url"


class GuiSettingsError(RuntimeError):
    """Raised when GUI preferences cannot be persisted safely."""


@dataclass(frozen=True)
class GuiRuntimeSettings:
    """Validated runtime preferences used by future GUI operations."""

    embedding_model: str
    generation_model: str
    top_k: int
    ollama_base_url: str


def default_gui_runtime_settings() -> GuiRuntimeSettings:
    """Return one snapshot based on shared production defaults."""
    return GuiRuntimeSettings(
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        generation_model=DEFAULT_GENERATION_MODEL,
        top_k=DEFAULT_TOP_K,
        ollama_base_url=DEFAULT_OLLAMA_BASE_URL,
    )


def validate_gui_runtime_settings(
    settings: GuiRuntimeSettings,
) -> GuiRuntimeSettings:
    """Validate and normalize a complete GUI runtime-settings snapshot."""
    embedding_model = _normalize_model_name(
        settings.embedding_model,
        field_name="embedding_model",
    )
    generation_model = _normalize_model_name(
        settings.generation_model,
        field_name="generation_model",
    )
    if isinstance(settings.top_k, bool) or not isinstance(settings.top_k, int):
        raise ValueError("top_k must be an integer")
    if settings.top_k <= 0:
        raise ValueError("top_k must be greater than 0")
    if settings.top_k > MAX_GUI_TOP_K:
        raise ValueError(f"top_k must be {MAX_GUI_TOP_K} or less")

    return GuiRuntimeSettings(
        embedding_model=embedding_model,
        generation_model=generation_model,
        top_k=settings.top_k,
        ollama_base_url=_normalize_ollama_base_url(
            settings.ollama_base_url
        ),
    )


class GuiSettingsStore:
    """Persist GUI preferences in one explicit INI file, outside corpus DBs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> GuiRuntimeSettings:
        """Load a valid snapshot, falling back wholly to defaults if invalid."""
        defaults = default_gui_runtime_settings()
        if not self.path.exists():
            return defaults

        settings = self._open_settings(self.path)
        try:
            raw_top_k = settings.value(_TOP_K_KEY, defaults.top_k)
            loaded = GuiRuntimeSettings(
                embedding_model=str(
                    settings.value(
                        _EMBEDDING_MODEL_KEY,
                        defaults.embedding_model,
                    )
                ),
                generation_model=str(
                    settings.value(
                        _GENERATION_MODEL_KEY,
                        defaults.generation_model,
                    )
                ),
                top_k=int(str(raw_top_k).strip()),
                ollama_base_url=str(
                    settings.value(
                        _OLLAMA_BASE_URL_KEY,
                        defaults.ollama_base_url,
                    )
                ),
            )
            if settings.status() != QSettings.Status.NoError:
                return defaults
            return validate_gui_runtime_settings(loaded)
        except (TypeError, ValueError):
            return defaults

    def save(self, settings: GuiRuntimeSettings) -> None:
        """Atomically persist one normalized snapshot using QSettings INI."""
        normalized = validate_gui_runtime_settings(settings)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, raw_temporary_path = tempfile.mkstemp(
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
            )
            os.close(descriptor)
        except OSError as exc:
            raise GuiSettingsError(
                f"Failed to prepare GUI settings file: {self.path}"
            ) from exc

        temporary_path = Path(raw_temporary_path)
        try:
            temporary_settings = self._open_settings(temporary_path)
            temporary_settings.clear()
            temporary_settings.setValue(
                _EMBEDDING_MODEL_KEY,
                normalized.embedding_model,
            )
            temporary_settings.setValue(
                _GENERATION_MODEL_KEY,
                normalized.generation_model,
            )
            temporary_settings.setValue(_TOP_K_KEY, normalized.top_k)
            temporary_settings.setValue(
                _OLLAMA_BASE_URL_KEY,
                normalized.ollama_base_url,
            )
            temporary_settings.sync()
            status = temporary_settings.status()
            del temporary_settings
            if status != QSettings.Status.NoError:
                raise GuiSettingsError(
                    f"Failed to write GUI settings file: {self.path}"
                )
            os.replace(temporary_path, self.path)
        except OSError as exc:
            raise GuiSettingsError(
                f"Failed to save GUI settings file: {self.path}"
            ) from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def reset_to_defaults(self) -> GuiRuntimeSettings:
        """Persist and return the production defaults."""
        defaults = default_gui_runtime_settings()
        self.save(defaults)
        return defaults

    @staticmethod
    def _open_settings(path: Path) -> QSettings:
        settings = QSettings(str(path), QSettings.Format.IniFormat)
        settings.setFallbacksEnabled(False)
        return settings


def _normalize_model_name(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_ollama_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("ollama_base_url must be a string")
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("ollama_base_url must not be empty")
    try:
        parsed = urlsplit(normalized)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("ollama_base_url must be a valid URL") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("ollama_base_url must use http or https")
    if parsed.hostname is None or any(
        character.isspace() for character in parsed.netloc
    ):
        raise ValueError("ollama_base_url must include a valid host")
    if parsed.query or parsed.fragment:
        raise ValueError("ollama_base_url must not include a query or fragment")
    return normalized
