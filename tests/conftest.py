from __future__ import annotations

import os
from typing import Any

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_QT_APPLICATION: Any = None


@pytest.fixture(scope="session")
def qt_app():  # type: ignore[no-untyped-def]
    """Keep exactly one QApplication wrapper alive for the full test session."""
    global _QT_APPLICATION
    from PySide6.QtWidgets import QApplication

    if _QT_APPLICATION is None:
        _QT_APPLICATION = QApplication.instance() or QApplication([])
        _QT_APPLICATION.setQuitOnLastWindowClosed(False)
    return _QT_APPLICATION
