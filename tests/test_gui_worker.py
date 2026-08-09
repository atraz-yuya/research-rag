import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable

import pytest
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication

from research_rag.gui_worker import QtTaskRunner


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    application = QApplication.instance()
    if application is None:
        application = QApplication([])
    return application


@pytest.fixture(scope="module")
def runner(qt_app: QApplication) -> QtTaskRunner:
    return QtTaskRunner()


def _run_task_until_finished(
    runner: QtTaskRunner,
    operation: Callable[[], object],
) -> tuple[list[object], list[Exception], list[QThread]]:
    loop = QEventLoop()
    results: list[object] = []
    errors: list[Exception] = []
    callback_threads: list[QThread] = []

    def on_success(result: object) -> None:
        callback_threads.append(QThread.currentThread())
        results.append(result)

    def on_error(error: Exception) -> None:
        callback_threads.append(QThread.currentThread())
        errors.append(error)

    def on_finished() -> None:
        callback_threads.append(QThread.currentThread())
        loop.quit()

    runner.submit(
        operation,
        on_success=on_success,
        on_error=on_error,
        on_finished=on_finished,
    )
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    return results, errors, callback_threads


def test_worker_returns_success_on_gui_thread(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    results, errors, callback_threads = _run_task_until_finished(
        runner,
        lambda: "done",
    )

    assert results == ["done"]
    assert errors == []
    assert callback_threads
    assert all(thread is qt_app.thread() for thread in callback_threads)


def test_worker_returns_failure_and_still_finishes_on_gui_thread(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    def fail() -> None:
        raise RuntimeError("worker failed")

    results, errors, callback_threads = _run_task_until_finished(runner, fail)

    assert results == []
    assert len(errors) == 1
    assert str(errors[0]) == "worker failed"
    assert callback_threads
    assert all(thread is qt_app.thread() for thread in callback_threads)
