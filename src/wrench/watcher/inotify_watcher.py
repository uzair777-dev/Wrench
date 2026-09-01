"""FR-1.8: Primary file system watcher via watchdog + Qt debounce.

Follows implementation plan §1013:
- Ignores internal .git/ directory events.
- Listens for modified, created, deleted, and moved/renamed atomic saves.
- Debounces via single-shot QTimer (300ms).
- Uses Qt QueuedConnection for thread-safe cross-thread signal dispatching.
"""

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .polling_fallback import PollingFallback

logger = logging.getLogger(__name__)


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def _is_git_internal(self, path_str: str) -> bool:
        return "/.git/" in path_str or path_str.endswith("/.git") or path_str.endswith(".git")

    def on_modified(self, event):
        if not self._is_git_internal(event.src_path):
            self._callback()

    def on_created(self, event):
        if not self._is_git_internal(event.src_path):
            self._callback()

    def on_deleted(self, event):
        if not self._is_git_internal(event.src_path):
            self._callback()

    def on_moved(self, event):
        # Check if destination path is inside worktree and not git internal
        dest = getattr(event, "dest_path", "")
        if dest and not self._is_git_internal(dest):
            self._callback()
        elif not self._is_git_internal(event.src_path):
            self._callback()


class RepoWatcher(QObject):
    """Watches a repository worktree for changes and emits status_changed."""

    status_changed = Signal()
    _raw_event_signal = Signal()

    def __init__(
        self,
        repo_path: Path | str,
        on_change=None,
        parent=None,
        debounce_ms: int = 300,
    ):
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._observer: Observer | None = None
        self._fallback: PollingFallback | None = None
        self._is_stopped = False
        self._lock = threading.Lock()
        self._start_thread: threading.Thread | None = None
        self._ready_event = threading.Event()

        if on_change:
            self.status_changed.connect(on_change)

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(debounce_ms)
        self._debounce_timer.timeout.connect(self._on_timer_timeout)

        # Cross-thread safe: Qt queues event to GUI main thread
        self._raw_event_signal.connect(self._on_fs_event_queued, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _on_fs_event_queued(self):
        self._debounce_timer.start()

    @Slot()
    def _on_timer_timeout(self):
        logger.debug(
            "[watcher] Debounce timer expired, emitting status_changed for %s",
            self._repo_path,
        )
        self.status_changed.emit()

    def _on_watchdog_event(self):
        self._raw_event_signal.emit()

    def start(self) -> None:
        """Starts the filesystem observer in a background daemon thread to avoid blocking UI."""
        with self._lock:
            self._is_stopped = False
            self._ready_event.clear()

        def _async_start():
            try:
                observer = Observer()
                handler = _WatchdogHandler(self._on_watchdog_event)
                observer.schedule(handler, str(self._repo_path), recursive=True)
                with self._lock:
                    if self._is_stopped:
                        return
                    self._observer = observer
                    self._observer.start()
                logger.debug(
                    "[watcher] Started watchdog inotify observer for %s",
                    self._repo_path,
                )
            except (OSError, Exception) as e:
                with self._lock:
                    if self._is_stopped:
                        return
                logger.warning(
                    "Inotify observer failed (%s); falling back to polling for %s",
                    e,
                    self._repo_path,
                )
                fallback = PollingFallback(self._repo_path, self.status_changed)
                with self._lock:
                    if self._is_stopped:
                        return
                    self._fallback = fallback
                    self._fallback.start()
            finally:
                self._ready_event.set()

        self._start_thread = threading.Thread(
            target=_async_start,
            name=f"RepoWatcher-{self._repo_path.name}",
            daemon=True,
        )
        self._start_thread.start()

    def wait_until_ready(self, timeout: float = 3.0) -> bool:
        """Waits until the background watcher initialization completes."""
        return self._ready_event.wait(timeout)

    @Slot()
    def stop(self) -> None:
        with self._lock:
            self._is_stopped = True
        self._debounce_timer.stop()
        if self._observer:
            try:
                self._observer.stop()
                self._observer.join(timeout=0.5)
            except Exception:
                pass
            self._observer = None
        if self._fallback:
            self._fallback.stop()
            self._fallback = None
        logger.debug("[watcher] Stopped watcher for %s", self._repo_path)
