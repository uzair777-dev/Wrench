"""FR-1.8: Primary file system watcher via watchdog + Qt debounce."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .polling_fallback import PollingFallback

logger = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, on_change_callback):
        super().__init__()
        self._callback = on_change_callback

    def on_any_event(self, event):
        path = event.src_path
        # Ignore noisy/transient git paths that don't represent logical state changes
        if "/.git/objects/" in path or path.endswith(".git/index.lock"):
            return
        self._callback()


class RepoWatcher(QObject):
    """Watches a repository worktree and .git dir for changes."""

    status_changed = Signal()
    _raw_change_detected = Signal()

    def __init__(self, repo_path: Path, parent=None, debounce_ms: int = 150):
        super().__init__(parent)
        self._repo_path = repo_path
        self._observer: Observer | None = None
        self._fallback: PollingFallback | None = None

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(debounce_ms)
        self._debounce_timer.timeout.connect(self.status_changed.emit)

        # Connect thread-safe raw signal to debounce timer start
        self._raw_change_detected.connect(self._debounce_timer.start)

    def _schedule_notify(self):
        self._raw_change_detected.emit()

    def start(self) -> None:
        try:
            self._observer = Observer()
            handler = _Handler(self._schedule_notify)
            self._observer.schedule(handler, str(self._repo_path), recursive=True)
            self._observer.start()
        except OSError as e:
            logger.warning(
                "Inotify observer failed (%s); falling back to polling for %s",
                e,
                self._repo_path,
            )
            self._fallback = PollingFallback(self._repo_path, self.status_changed)
            self._fallback.start()

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)
            self._observer = None
        if self._fallback:
            self._fallback.stop()
            self._fallback = None
        self._debounce_timer.stop()
