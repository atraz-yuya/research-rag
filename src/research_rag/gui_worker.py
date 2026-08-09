from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any, Protocol

from PySide6.QtCore import (
    Qt,
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)


class TaskRunner(Protocol):
    """Submit finite work and deliver callbacks on the GUI thread."""

    @property
    def active_task_count(self) -> int: ...

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None: ...

    def request_shutdown(self, on_idle: Callable[[], None]) -> None: ...

    def shutdown(self, *, wait: bool) -> None: ...


class _WorkerSignals(QObject):
    succeeded = Signal()
    failed = Signal()
    finished = Signal()


class _TaskState:
    def __init__(self) -> None:
        self.result: Any = None
        self.error: Exception | None = None


class _Worker(QRunnable):
    def __init__(
        self,
        operation: Callable[[], Any],
        state: _TaskState,
        signals: _WorkerSignals,
    ) -> None:
        super().__init__()
        self.operation = operation
        self.state = state
        self.signals = signals
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            self.state.result = self.operation()
        except Exception as exc:
            self.state.error = exc
            self.signals.failed.emit()
        else:
            self.signals.succeeded.emit()
        finally:
            self.signals.finished.emit()


class _CallbackRelay(QObject):
    def __init__(
        self,
        owner: QtTaskRunner,
        state: _TaskState,
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        super().__init__(owner)
        self.owner = owner
        self.state = state
        self.signals = _WorkerSignals(self)
        self.on_success = on_success
        self.on_error = on_error
        self.on_finished = on_finished
        self.cancelled = False

    @Slot()
    def deliver_success(self) -> None:
        if not self.cancelled:
            self.on_success(self.state.result)

    @Slot()
    def deliver_error(self) -> None:
        if self.cancelled:
            return
        error = self.state.error
        if error is None:
            error = RuntimeError("GUI worker failed without exception details")
        traceback.print_exception(type(error), error, error.__traceback__)
        self.on_error(error)

    @Slot()
    def deliver_finished(self) -> None:
        try:
            if not self.cancelled:
                self.on_finished()
        finally:
            self.owner._release(self)

    def cancel_callbacks(self) -> None:
        """Prevent queued callbacks from touching a tearing-down GUI."""
        self.cancelled = True


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
            else QThreadPool(self)
        )
        self._active_workers: dict[_CallbackRelay, _Worker] = {}
        self._accepting_work = True
        self._idle_callbacks: list[Callable[[], None]] = []

    @property
    def active_task_count(self) -> int:
        return len(self._active_workers)

    def submit(
        self,
        operation: Callable[[], Any],
        *,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
        on_finished: Callable[[], None],
    ) -> None:
        if not self._accepting_work:
            raise RuntimeError("GUI task runner is shutting down")
        state = _TaskState()
        relay = _CallbackRelay(
            self,
            state,
            on_success=on_success,
            on_error=on_error,
            on_finished=on_finished,
        )
        worker = _Worker(operation, state, relay.signals)
        self._active_workers[relay] = worker
        relay.signals.succeeded.connect(
            relay.deliver_success,
            Qt.ConnectionType.QueuedConnection,
        )
        relay.signals.failed.connect(
            relay.deliver_error,
            Qt.ConnectionType.QueuedConnection,
        )
        relay.signals.finished.connect(
            relay.deliver_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self.thread_pool.start(worker)

    def request_shutdown(self, on_idle: Callable[[], None]) -> None:
        """Stop accepting work and invoke a GUI callback once tasks finish."""
        self._accepting_work = False
        self._idle_callbacks.append(on_idle)
        if not self._active_workers:
            self._schedule_idle_callbacks()

    def shutdown(self, *, wait: bool) -> None:
        """Stop submissions and optionally wait before QObject teardown."""
        self._accepting_work = False
        if not wait:
            return

        for relay in tuple(self._active_workers):
            relay.cancel_callbacks()
        self.thread_pool.waitForDone()
        self._idle_callbacks.clear()
        for relay in tuple(self._active_workers):
            self._release(relay, notify_idle=False)

    def _release(
        self,
        relay: _CallbackRelay,
        *,
        notify_idle: bool = True,
    ) -> None:
        worker = self._active_workers.pop(relay, None)
        if worker is None:
            return
        relay.deleteLater()
        if notify_idle and not self._active_workers:
            self._schedule_idle_callbacks()

    def _schedule_idle_callbacks(self) -> None:
        callbacks, self._idle_callbacks = self._idle_callbacks, []
        for callback in callbacks:
            QTimer.singleShot(0, callback)
