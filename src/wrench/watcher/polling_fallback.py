"""FR-1.8 / VP-16: Polling fallback when inotify limits are hit."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from wrench.core.exceptions import WrenchRepoNotFoundError
from wrench.core.paths import resolve_git_dir

logger = logging.getLogger(__name__)

_MAX_REFS_SCAN = 500


class PollingFallback(QObject):
    """Fallback directory watcher polling git metadata mtimes periodically."""

    def __init__(
        self,
        repo_path: Path,
        signal: Signal,
        parent=None,
        interval_ms: int = 2000,
        git_dir: Path | None = None,
    ):
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._signal = signal
        if git_dir is not None:
            self._git_dir = Path(git_dir)
        else:
            try:
                self._git_dir = resolve_git_dir(self._repo_path)
            except WrenchRepoNotFoundError:
                self._git_dir = self._repo_path / ".git"

        self._last_head_mtime: float | None = None
        self._last_index_mtime: float | None = None
        self._last_mtimes: dict[Path, float] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._check_changes)

    def _collect_watched_files(self) -> list[Path]:
        files = [
            self._git_dir / "HEAD",
            self._git_dir / "index",
            self._git_dir / "packed-refs",
            self._git_dir / "info" / "sparse-checkout",
        ]
        refs_dir = self._git_dir / "refs"
        if refs_dir.is_dir():
            count = 0
            try:
                for p in refs_dir.rglob("*"):
                    if count >= _MAX_REFS_SCAN:
                        break
                    if p.name.endswith(".lock"):
                        continue
                    try:
                        if p.is_file():
                            files.append(p)
                            count += 1
                    except OSError as exc:
                        logger.debug("Polling stat check skipped for %s: %s", p, exc)
            except OSError as exc:
                logger.debug("Polling refs walk skipped for %s: %s", refs_dir, exc)
        return files

    def _check_changes(self) -> None:
        changed = False
        head_path = self._git_dir / "HEAD"
        index_path = self._git_dir / "index"

        for target in self._collect_watched_files():
            try:
                if not target.exists():
                    continue
                mtime = target.stat().st_mtime
            except OSError as exc:
                logger.debug("Polling mtime stat failed for %s: %s", target, exc)
                continue

            if target == head_path:
                self._last_head_mtime = mtime
            elif target == index_path:
                self._last_index_mtime = mtime

            prev = self._last_mtimes.get(target)
            if prev is not None and mtime != prev:
                changed = True
            self._last_mtimes[target] = mtime

        if changed:
            self._signal.emit()

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
