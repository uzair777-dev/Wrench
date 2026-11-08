"""Background worker for long-running git operations (§4.8).

All blocking git and network operations initiated by the UI run in a background daemon thread.
Callbacks are dispatched to the Qt main GUI thread via a queued QObject dispatcher to ensure
complete thread safety with GUI widgets without secondary Qt event loops or Shiboken deadlocks.
"""

import logging
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal, Slot

logger = logging.getLogger(__name__)

_activity_log: Any = None


def set_activity_log(log: Any) -> None:
    """Register the global activity log model for background workers."""
    global _activity_log
    _activity_log = log


def _post_activity(text: str, level: str = "info") -> None:
    """Post an activity message safely to the activity log via the Qt dispatcher."""
    if _activity_log is not None:
        dispatcher = _get_dispatcher()
        dispatcher.dispatch_activity.emit(text, level)


class _Dispatcher(QObject):
    """Dispatches worker results to the GUI main thread."""

    dispatch_finished = Signal(object, object)
    dispatch_failed = Signal(object, object)
    dispatch_progress = Signal(object, int)
    dispatch_activity = Signal(str, str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.dispatch_finished.connect(self._handle_finished, Qt.ConnectionType.QueuedConnection)
        self.dispatch_failed.connect(self._handle_failed, Qt.ConnectionType.QueuedConnection)
        self.dispatch_progress.connect(self._handle_progress, Qt.ConnectionType.QueuedConnection)
        self.dispatch_activity.connect(self._handle_activity, Qt.ConnectionType.QueuedConnection)

    @Slot(object, object)
    def _handle_finished(self, callback: Callable[[Any], None] | None, result: Any) -> None:
        if callback:
            try:
                callback(result)
            except Exception as e:
                logger.exception("Error in background worker on_finished callback: %s", e)

    @Slot(object, object)
    def _handle_failed(self, callback: Callable[[Exception], None] | None, exc: Exception) -> None:
        if callback:
            try:
                callback(exc)
            except Exception as e:
                logger.exception("Error in background worker on_failed callback: %s", e)

    @Slot(object, int)
    def _handle_progress(self, callback: Callable[[int], None] | None, pct: int) -> None:
        if callback:
            try:
                callback(pct)
            except Exception as e:
                logger.exception("Error in background worker on_progress callback: %s", e)

    @Slot(str, str)
    def _handle_activity(self, text: str, level: str) -> None:
        if _activity_log is not None:
            try:
                _activity_log.post(text, level)
            except Exception as e:
                logger.exception("Error posting to activity log: %s", e)


_dispatcher: _Dispatcher | None = None


def _get_dispatcher() -> _Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        app = QCoreApplication.instance()
        _dispatcher = _Dispatcher(parent=app)
    return _dispatcher


class GitOperationWorker(QObject):
    """Worker object maintaining backward compatibility for direct callers/tests."""

    finished = Signal(object)
    failed = Signal(Exception)
    progress = Signal(int)

    def __init__(
        self,
        fn: Callable[..., Any],
        *args: Any,
        cancel_event: threading.Event | None = None,
        **kwargs: Any,
    ):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.cancel_event = cancel_event

    def run(self) -> None:
        try:
            kw = dict(self._kwargs)
            if hasattr(self._fn, "__code__"):
                varnames = self._fn.__code__.co_varnames
                if "progress_cb" in varnames and "progress_cb" not in kw:
                    kw["progress_cb"] = lambda pct, stage=None: self.progress.emit(pct)
                if (
                    "cancel_event" in varnames
                    and "cancel_event" not in kw
                    and self.cancel_event is not None
                ):
                    kw["cancel_event"] = self.cancel_event
            result = self._fn(*self._args, **kw)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(e)


class WorkerThread(threading.Thread):
    """Background worker thread providing QThread compatibility methods."""

    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        op_name: str = "",
        on_finished: Callable[[Any], None] | None = None,
        on_failed: Callable[[Exception], None] | None = None,
        on_progress: Callable[[int], None] | None = None,
        cancel_event: threading.Event | None = None,
    ):
        super().__init__(daemon=True)
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self._op_name = op_name
        self.on_finished = on_finished
        self.on_failed = on_failed
        self.on_progress = on_progress
        self.cancel_event = cancel_event
        self.worker: GitOperationWorker | None = None

    def run(self) -> None:
        dispatcher = _get_dispatcher()
        start_time = time.time()
        if self._op_name:
            _post_activity(f"Started: {self._op_name}", level="info")
        try:
            kw = dict(self._kwargs)
            if hasattr(self._fn, "__code__"):
                varnames = self._fn.__code__.co_varnames
                if "progress_cb" in varnames and "progress_cb" not in kw:

                    def _progress_cb(pct: int, stage: Any = None) -> None:
                        if self.on_progress:
                            dispatcher.dispatch_progress.emit(self.on_progress, pct)

                    kw["progress_cb"] = _progress_cb
                if (
                    "cancel_event" in varnames
                    and "cancel_event" not in kw
                    and self.cancel_event is not None
                ):
                    kw["cancel_event"] = self.cancel_event

            result = self._fn(*self._args, **kw)
            elapsed = time.time() - start_time
            if self._op_name:
                _post_activity(f"Finished: {self._op_name} ({elapsed:.1f}s)", level="ok")
            if self.on_finished:
                dispatcher.dispatch_finished.emit(self.on_finished, result)
        except Exception as e:
            if self._op_name:
                _post_activity(f"Failed: {type(e).__name__}", level="error")
            if self.on_failed:
                dispatcher.dispatch_failed.emit(self.on_failed, e)
            else:
                logger.exception("Unhandled error in background worker: %s", e)
        finally:
            _active_workers.discard(self)

    # QThread API compatibility methods
    def isRunning(self) -> bool:
        return self.is_alive()

    def wait(self, timeout: float | None = None) -> bool:
        self.join(timeout=timeout)
        return not self.is_alive()

    def quit(self) -> None:
        pass


_active_workers: set[WorkerThread] = set()


def run_in_background(
    fn: Callable[..., Any],
    *args: Any,
    op_name: str = "",
    on_finished: Callable[[Any], None] | None = None,
    on_failed: Callable[[Exception], None] | None = None,
    on_progress: Callable[[int], None] | None = None,
    cancel_event: threading.Event | None = None,
    **kwargs: Any,
) -> WorkerThread:
    _get_dispatcher()  # Ensure dispatcher is initialized on main thread
    thread = WorkerThread(
        fn,
        args,
        kwargs,
        op_name=op_name,
        on_finished=on_finished,
        on_failed=on_failed,
        on_progress=on_progress,
        cancel_event=cancel_event,
    )
    _active_workers.add(thread)
    thread.start()
    return thread
