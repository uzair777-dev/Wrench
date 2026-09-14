"""Background worker for long-running git operations (§4.8).

All blocking git operations initiated by the UI run in a background QThread.
Callbacks are dispatched to the Qt main thread via a queued dispatcher to ensure
complete thread safety with GUI widgets.
"""

import logging

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

logger = logging.getLogger(__name__)

_active_workers: set[tuple[QThread, QObject]] = set()


class _Dispatcher(QObject):
    """Dispatches worker results to the GUI main thread."""

    dispatch_finished = Signal(object, object)
    dispatch_failed = Signal(object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dispatch_finished.connect(self._handle_finished, Qt.ConnectionType.QueuedConnection)
        self.dispatch_failed.connect(self._handle_failed, Qt.ConnectionType.QueuedConnection)

    @Slot(object, object)
    def _handle_finished(self, callback, result):
        if callback:
            try:
                callback(result)
            except Exception as e:
                logger.exception("Error in background worker on_finished callback: %s", e)

    @Slot(object, object)
    def _handle_failed(self, callback, exc):
        if callback:
            try:
                callback(exc)
            except Exception as e:
                logger.exception("Error in background worker on_failed callback: %s", e)


_dispatcher: _Dispatcher | None = None


def _get_dispatcher() -> _Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = _Dispatcher()
    return _dispatcher


class GitOperationWorker(QObject):
    finished = Signal(object)
    failed = Signal(Exception)
    progress = Signal(int)

    def __init__(self, fn, *args, cancel_event=None, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.cancel_event = cancel_event

    def run(self):
        try:
            if hasattr(self._fn, "__code__"):
                varnames = self._fn.__code__.co_varnames
                if "progress_cb" in varnames and "progress_cb" not in self._kwargs:
                    self._kwargs["progress_cb"] = lambda pct, stage=None: self.progress.emit(pct)
                if (
                    "cancel_event" in varnames
                    and "cancel_event" not in self._kwargs
                    and self.cancel_event is not None
                ):
                    self._kwargs["cancel_event"] = self.cancel_event
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(e)


def run_in_background(
    fn,
    *args,
    on_finished=None,
    on_failed=None,
    on_progress=None,
    cancel_event=None,
    **kwargs,
) -> QThread:
    dispatcher = _get_dispatcher()
    thread = QThread()
    worker = GitOperationWorker(fn, *args, cancel_event=cancel_event, **kwargs)
    thread.worker = worker  # type: ignore[attr-defined]
    thread.cancel_event = cancel_event  # type: ignore[attr-defined]
    worker.moveToThread(thread)

    pair = (thread, worker)
    _active_workers.add(pair)

    thread.started.connect(worker.run)

    if on_finished:
        worker.finished.connect(lambda res: dispatcher.dispatch_finished.emit(on_finished, res))
    if on_failed:
        worker.failed.connect(lambda err: dispatcher.dispatch_failed.emit(on_failed, err))
    if on_progress:
        worker.progress.connect(on_progress)

    # Schedule worker deletion inside thread event loop, then quit thread
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)

    def _cleanup():
        _active_workers.discard(pair)
        thread.deleteLater()

    thread.finished.connect(_cleanup)

    thread.start()
    return thread
