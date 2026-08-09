from __future__ import annotations

import gc
import os
from collections.abc import Callable
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


def _delete_widgets(application: Any, widgets: list[Any]) -> None:
    from PySide6.QtCore import QCoreApplication, QEvent, Qt

    for widget in widgets:
        shutdown = getattr(widget, "shutdown_for_application_exit", None)
        if callable(shutdown):
            shutdown()
        delete_on_close = widget.testAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose
        )
        widget.close()
        if not delete_on_close:
            widget.deleteLater()

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()


@pytest.fixture
def delete_qt_widget(qt_app: Any) -> Callable[[Any], None]:
    """Delete one top-level widget deterministically on the GUI thread."""

    def delete(widget: Any) -> None:
        _delete_widgets(qt_app, [widget])

    return delete


@pytest.fixture(autouse=True)
def cleanup_qt_widgets(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    """Flush top-level QWidget trees before Python cyclic GC runs."""
    yield
    if "qt_app" not in request.fixturenames:
        return
    application = request.getfixturevalue("qt_app")
    root_widgets = [
        widget
        for widget in application.topLevelWidgets()
        if widget.parentWidget() is None
    ]
    _delete_widgets(application, root_widgets)
    gc.collect()
