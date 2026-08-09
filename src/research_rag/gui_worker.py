from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal, Slot


class TaskRunner(Protocol):
    """Submit finite work and deliver callbacks on the GUI thread."""

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None: ...


class _WorkerSignals(QObject):
    succeeded = Signal()
    failed = Signal()
    finished = Signal()


class _Worker(QRunnable):
    def __init__(self, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.operation = operation
        self.signals = _WorkerSignals()
        self.result: Any = None
        self.error: Exception | None = None
        # The relay owns the worker until queued GUI-thread callbacks finish.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            self.result = self.operation()
        except Exception as exc:
            self.error = exc
            self.signals.failed.emit()
        else:
            self.signals.succeeded.emit()
        finally:
            self.signals.finished.emit()


class _CallbackRelay(QObject):
    def __init__(
        self,
        owner: QtTaskRunner,
        worker: _Worker,
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.worker = worker
        self.on_success = on_success
        self.on_error = on_error
        self.on_finished = on_finished

    @Slot()
    def deliver_success(self) -> None:
        self.on_success(self.worker.result)

    @Slot()
    def deliver_error(self) -> None:
        error = self.worker.error
        if error is None:
            error = RuntimeError("GUI worker failed without exception details")
        traceback.print_exception(type(error), error, error.__traceback__)
        self.on_error(error)

    @Slot()
    def deliver_finished(self) -> None:
        try:
            self.on_finished()
        finally:
            self.owner._release(self)


class QtTaskRunner(QObject):
    """Run operations in QThreadPool and marshal callbacks to the GUI thread."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self.thread_pool = (
            thread_pool
            if thread_pool is not None
            else QThreadPool.globalInstance()
        )
        self._active_workers: dict[_CallbackRelay, _Worker] = {}

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        worker = _Worker(operation)
        relay = _CallbackRelay(
            self,
            worker,
            on_success=on_success,
            on_error=on_error,
            on_finished=on_finished,
        )
        self._active_workers[relay] = worker
        worker.signals.succeeded.connect(
            relay.deliver_success,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.failed.connect(
            relay.deliver_error,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.signals.finished.connect(
            relay.deliver_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self.thread_pool.start(worker)

    def _release(self, relay: _CallbackRelay) -> None:
        self._active_workers.pop(relay, None)
        relay.deleteLater()
