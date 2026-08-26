"""FR-1.8: Polling fallback when inotify limits are hit."""

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal


class PollingFallback(QObject):
    """Fallback directory watcher polling mtimes periodically."""

    def __init__(
        self,
        repo_path: Path,
        signal: Signal,
        parent=None,
        interval_ms: int = 2000,
    ):
        super().__init__(parent)
        self._repo_path = repo_path
        self._signal = signal
        self._last_head_mtime: float | None = None
        self._last_index_mtime: float | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check_changes)

    def _check_changes(self) -> None:
        head_path = self._repo_path / ".git" / "HEAD"
        index_path = self._repo_path / ".git" / "index"

        changed = False

        if head_path.exists():
            mtime = head_path.stat().st_mtime
            if self._last_head_mtime is not None and mtime != self._last_head_mtime:
                changed = True
            self._last_head_mtime = mtime

        if index_path.exists():
            mtime = index_path.stat().st_mtime
            if self._last_index_mtime is not None and mtime != self._last_index_mtime:
                changed = True
            self._last_index_mtime = mtime

        if changed:
            self._signal.emit()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
