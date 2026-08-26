"""Background worker for long-running git operations (§4.8).

All blocking git operations initiated by the UI run in a background QThread.
Module-level _active_threads set prevents Python GC from destroying QThread
objects while their OS thread is still executing.
"""

from PySide6.QtCore import QObject, QThread, Signal

_active_threads: set[QThread] = set()


class GitOperationWorker(QObject):
    finished = Signal(object)
    failed = Signal(Exception)
    progress = Signal(int)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            if hasattr(self._fn, "__code__") and "progress_cb" in self._fn.__code__.co_varnames:
                self._kwargs.setdefault("progress_cb", self.progress.emit)
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(e)


def run_in_background(
    fn, *args, on_finished=None, on_failed=None, on_progress=None, **kwargs
) -> QThread:
    thread = QThread()
    worker = GitOperationWorker(fn, *args, **kwargs)
    worker.moveToThread(thread)

    # Retain thread reference until finished
    _active_threads.add(thread)

    thread.started.connect(worker.run)

    if on_finished:
        worker.finished.connect(on_finished)
    if on_failed:
        worker.failed.connect(on_failed)
    if on_progress:
        worker.progress.connect(on_progress)

    def _cleanup():
        thread.quit()

    worker.finished.connect(_cleanup)
    worker.failed.connect(_cleanup)

    def _on_thread_finished():
        _active_threads.discard(thread)
        worker.deleteLater()
        thread.deleteLater()

    thread.finished.connect(_on_thread_finished)

    thread.start()
    return thread
