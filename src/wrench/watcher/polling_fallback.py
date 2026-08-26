"""FR-1.8: Polling fallback when inotify limits are hit."""

from pathlib import Path

from PySide6.QtCore import Signal


class PollingFallback:
    def __init__(self, repo_path: Path, signal: Signal):
        self._repo_path = repo_path
        self._signal = signal

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError
