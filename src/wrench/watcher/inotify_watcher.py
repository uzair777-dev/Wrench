"""FR-1.8: Primary file system watcher via watchdog + Qt debounce."""

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class RepoWatcher(QObject):
    status_changed = Signal()

    def __init__(self, repo_path: Path, parent=None):
        super().__init__(parent)
        self._repo_path = repo_path

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
