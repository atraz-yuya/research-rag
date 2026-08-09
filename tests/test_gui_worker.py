import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import subprocess
import sys
import textwrap
import time
import weakref
from collections.abc import Callable
from threading import Event

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication

from research_rag.gui_worker import QtTaskRunner


def test_suite_uses_one_qapplication_instance(qt_app: QApplication) -> None:
    assert QApplication.instance() is qt_app


@pytest.fixture
def runner(qt_app: QApplication):  # type: ignore[no-untyped-def]
    task_runner = QtTaskRunner()
    yield task_runner
    task_runner.shutdown(wait=True)
    qt_app.processEvents()


def _process_events_until(
    application: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout: float = 3.0,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        application.processEvents()
        if time.monotonic() >= deadline:
            raise TimeoutError("Qt callback did not finish")
        time.sleep(0.001)
    application.processEvents()


def _run_task_until_finished(
    application: QApplication,
    runner: QtTaskRunner,
    operation: Callable[[], object],
) -> tuple[list[object], list[Exception], list[QThread]]:
    results: list[object] = []
    errors: list[Exception] = []
    callback_threads: list[QThread] = []
    finished = False

    def on_success(result: object) -> None:
        callback_threads.append(QThread.currentThread())
        results.append(result)

    def on_error(error: Exception) -> None:
        callback_threads.append(QThread.currentThread())
        errors.append(error)

    def on_finished() -> None:
        nonlocal finished
        callback_threads.append(QThread.currentThread())
        finished = True

    runner.submit(
        operation,
        on_success=on_success,
        on_error=on_error,
        on_finished=on_finished,
    )
    _process_events_until(application, lambda: finished)
    return results, errors, callback_threads


def test_worker_returns_success_on_gui_thread(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    results, errors, callback_threads = _run_task_until_finished(
        qt_app,
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

    results, errors, callback_threads = _run_task_until_finished(
        qt_app,
        runner,
        fail,
    )

    assert results == []
    assert len(errors) == 1
    assert str(errors[0]) == "worker failed"
    assert callback_threads
    assert all(thread is qt_app.thread() for thread in callback_threads)


def test_multiple_workers_run_sequentially_without_retaining_active_tasks(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    results: list[int] = []

    for value in range(25):
        task_results, errors, _ = _run_task_until_finished(
            qt_app,
            runner,
            lambda value=value: value,
        )
        assert errors == []
        results.extend(task_results)  # type: ignore[arg-type]
        assert runner.active_task_count == 0

    assert results == list(range(25))


def test_completed_worker_and_relay_are_released(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    finished = False

    def on_finished() -> None:
        nonlocal finished
        finished = True

    runner.submit(
        lambda: "done",
        on_success=lambda _: None,
        on_error=lambda _: None,
        on_finished=on_finished,
    )
    relay, worker = next(iter(runner._active_workers.items()))
    relay_reference = weakref.ref(relay)
    worker_reference = weakref.ref(worker)
    del relay
    del worker

    _process_events_until(qt_app, lambda: finished)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()
    gc.collect()

    assert runner.active_task_count == 0
    assert relay_reference() is None
    assert worker_reference() is None


def test_shutdown_waits_for_active_worker_and_discards_queued_callbacks(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    started = Event()
    callbacks: list[str] = []

    def operation() -> str:
        started.set()
        time.sleep(0.05)
        return "done"

    runner.submit(
        operation,
        on_success=lambda _: callbacks.append("success"),
        on_error=lambda _: callbacks.append("error"),
        on_finished=lambda: callbacks.append("finished"),
    )
    assert started.wait(timeout=1)

    runner.shutdown(wait=True)
    qt_app.processEvents()

    assert runner.active_task_count == 0
    assert runner.thread_pool.activeThreadCount() == 0
    assert callbacks == []


def test_shutdown_after_worker_run_before_queued_delivery_is_safe(
    qt_app: QApplication,
    runner: QtTaskRunner,
) -> None:
    operation_finished = Event()
    callbacks: list[str] = []

    def operation() -> str:
        operation_finished.set()
        return "done"

    runner.submit(
        operation,
        on_success=lambda _: callbacks.append("success"),
        on_error=lambda _: callbacks.append("error"),
        on_finished=lambda: callbacks.append("finished"),
    )
    assert operation_finished.wait(timeout=1)

    runner.shutdown(wait=True)
    qt_app.processEvents()

    assert runner.active_task_count == 0
    assert callbacks == []


def test_qapplication_teardown_waits_for_active_worker_in_subprocess() -> None:
    script = textwrap.dedent(
        """
        import os
        import time
        from threading import Event

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from research_rag.gui_worker import QtTaskRunner

        application = QApplication([])
        runner = QtTaskRunner()
        started = Event()

        def operation():
            started.set()
            time.sleep(0.05)

        runner.submit(
            operation,
            on_success=lambda _: None,
            on_error=lambda _: None,
            on_finished=lambda: None,
        )
        application.aboutToQuit.connect(lambda: runner.shutdown(wait=True))
        QTimer.singleShot(0, application.quit)
        exit_code = application.exec()

        assert started.is_set()
        assert runner.active_task_count == 0
        assert runner.thread_pool.activeThreadCount() == 0
        raise SystemExit(exit_code)
        """
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
