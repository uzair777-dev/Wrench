"""Background worker for long-running git operations."""

from PySide6.QtCore import QObject, QThread, Signal


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
            self.finished.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.failed.emit(e)


def run_in_background(
    fn, *args, on_finished=None, on_failed=None, on_progress=None, **kwargs
) -> QThread:
    thread = QThread()
    worker = GitOperationWorker(fn, *args, **kwargs)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    if on_finished:
        worker.finished.connect(on_finished)
    if on_failed:
        worker.failed.connect(on_failed)
    if on_progress:
        worker.progress.connect(on_progress)

    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)

    thread.start()
    return thread
