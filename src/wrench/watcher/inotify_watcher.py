"""FR-1.8 / VP-16: Watchdog watcher with Qt debounce and adaptive monorepo fallback.

Follows implementation plan §1013 and VP-16 Tier-1/Tier-2/Tier-3 architecture:
- Ignores internal .git/ directory events during full-tree watching.
- Adapts cleanly to .git-only metadata watching on ENOSPC/EMFILE inotify limits.
- Falls back to Qt-thread PollingFallback when inotify is unavailable or disabled.
- Debounces via single-shot QTimer (configurable via SettingsRegistry watcher.debounce_ms).
"""

from __future__ import annotations

import errno
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from shiboken6 import isValid as qt_is_valid
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from wrench.core.exceptions import WrenchRepoNotFoundError
from wrench.core.models import WatcherStatusInfo
from wrench.core.paths import resolve_git_dir
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry

from .polling_fallback import PollingFallback

logger = logging.getLogger(__name__)

_WATCH_LIMIT_ERRNOS = frozenset({errno.ENOSPC, errno.EMFILE})


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
        dest = getattr(event, "dest_path", "")
        if dest and not self._is_git_internal(dest):
            self._callback()
        elif not self._is_git_internal(event.src_path):
            self._callback()


class _GitDirMetadataHandler(FileSystemEventHandler):
    """Lightweight handler for Tier-2 .git-only watching (HEAD, index, refs, sparse)."""

    def __init__(self, callback, git_dir: Path):
        super().__init__()
        self._callback = callback
        resolved_git = git_dir.resolve()
        self._refs_prefix = str(resolved_git / "refs")
        self._tracked_files = frozenset(
            {
                str(resolved_git / "HEAD"),
                str(resolved_git / "index"),
                str(resolved_git / "packed-refs"),
                str(resolved_git / "info" / "sparse-checkout"),
            }
        )

    def _is_relevant(self, raw_path: str) -> bool:
        if not raw_path or raw_path.endswith(".lock"):
            return False
        try:
            normalized = str(Path(raw_path).resolve())
        except OSError:
            normalized = raw_path
        if normalized in self._tracked_files:
            return True
        return normalized.startswith(self._refs_prefix + "/") or normalized == self._refs_prefix

    def on_modified(self, event):
        if self._is_relevant(event.src_path):
            self._callback()

    def on_created(self, event):
        if self._is_relevant(event.src_path):
            self._callback()

    def on_deleted(self, event):
        if self._is_relevant(event.src_path):
            self._callback()

    def on_moved(self, event):
        dest = getattr(event, "dest_path", "")
        if dest and self._is_relevant(dest):
            self._callback()
        elif self._is_relevant(event.src_path):
            self._callback()


def _is_watch_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, OSError):
        if getattr(exc, "errno", None) in _WATCH_LIMIT_ERRNOS:
            return True
        msg = str(exc).lower()
        return "inotify" in msg or "no space left" in msg or "too many open files" in msg
    return "inotify" in str(exc).lower()


class RepoWatcher(QObject):
    """Watches a repository worktree for changes with 3-tier monorepo fallback."""

    status_changed = Signal()
    adaptive_fallback_activated = Signal(str, str)
    _raw_event_signal = Signal()
    _adaptive_signal = Signal(str, str)
    _start_polling_signal = Signal(str)

    def __init__(
        self,
        repo_path: Path | str,
        on_change=None,
        parent=None,
        debounce_ms: int = 300,
        settings_registry: SettingsRegistry | None = None,
    ):
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._settings_registry = settings_registry
        self._settings_connected = False
        self._observer: Observer | None = None
        self._fallback: PollingFallback | None = None
        self._is_stopped = False
        self._lock = threading.Lock()
        self._start_thread: threading.Thread | None = None
        self._ready_event = threading.Event()
        self._git_dir: Path | None = None
        self._status_info = WatcherStatusInfo(
            mode="disabled",
            is_fallback=False,
            watched_paths=(),
            reason=None,
        )

        if on_change:
            self.status_changed.connect(on_change)

        effective_debounce = debounce_ms
        reg = self._resolve_registry()
        if reg is not None:
            effective_debounce = reg.get_int("watcher.debounce_ms", str(self._repo_path))

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(max(50, effective_debounce))
        self._debounce_timer.timeout.connect(self._on_timer_timeout)

        # Cross-thread safe: Qt queues worker events to the owning GUI thread
        self._raw_event_signal.connect(self._on_fs_event_queued, Qt.ConnectionType.QueuedConnection)
        self._adaptive_signal.connect(
            self._on_adaptive_signal_queued,
            Qt.ConnectionType.QueuedConnection,
        )
        self._start_polling_signal.connect(
            self._on_start_polling_queued,
            Qt.ConnectionType.QueuedConnection,
        )

        self._connect_settings_registry()
        self.destroyed.connect(self._disconnect_settings_registry)

    def _resolve_registry(self) -> SettingsRegistry | None:
        return self._settings_registry or peek_settings_registry()

    def _connect_settings_registry(self) -> None:
        reg = self._resolve_registry()
        if reg is not None and not self._settings_connected:
            reg.setting_changed.connect(
                self._on_setting_changed,
                Qt.ConnectionType.QueuedConnection,
            )
            self._settings_connected = True

    @Slot()
    def _disconnect_settings_registry(self) -> None:
        if not self._settings_connected:
            return
        reg = self._resolve_registry()
        if reg is not None and qt_is_valid(reg):
            try:
                reg.setting_changed.disconnect(self._on_setting_changed)
            except (RuntimeError, TypeError) as exc:
                logger.debug("Settings signal disconnect skipped: %s", exc)
        self._settings_connected = False

    @property
    def status_info(self) -> WatcherStatusInfo:
        with self._lock:
            return self._status_info

    def _inotify_enabled(self) -> bool:
        reg = self._resolve_registry()
        if reg is None:
            return True
        return reg.is_enabled("watcher.inotify.enabled", str(self._repo_path))

    def _adaptive_fallback_enabled(self) -> bool:
        reg = self._resolve_registry()
        if reg is None:
            return True
        return reg.is_enabled("watcher.monorepo_adaptive_fallback.enabled", str(self._repo_path))

    def _resolve_repo_git_dir(self) -> Path:
        try:
            return resolve_git_dir(self._repo_path)
        except WrenchRepoNotFoundError:
            return self._repo_path / ".git"

    @Slot(str, object, object)
    def _on_setting_changed(self, key: str, value: object, repo_path: object) -> None:
        if not qt_is_valid(self):
            return
        repo_str = str(self._repo_path)
        if repo_path is not None and str(repo_path) != repo_str:
            return

        if key == "watcher.debounce_ms":
            reg = self._resolve_registry()
            new_ms = reg.get_int("watcher.debounce_ms", repo_str) if reg else int(value or 300)
            self._debounce_timer.setInterval(max(50, new_ms))
        elif key == "watcher.inotify.enabled":
            if not self._inotify_enabled():
                self._disable_monitoring("Disabled by setting")
            else:
                with self._lock:
                    was_disabled = self._status_info.mode == "disabled" and not self._is_stopped
                if was_disabled:
                    self.start()
        elif key == "watcher.monorepo_adaptive_fallback.enabled":
            with self._lock:
                currently_git_dir = self._status_info.mode == "git_dir_inotify"
            if currently_git_dir and not self._adaptive_fallback_enabled():
                self._stop_active_backends()
                self._on_start_polling_queued("Adaptive .git fallback disabled by setting")

    def _disable_monitoring(self, reason: str) -> None:
        self._stop_active_backends()
        with self._lock:
            self._status_info = WatcherStatusInfo(
                mode="disabled",
                is_fallback=False,
                watched_paths=(),
                reason=reason,
            )
        self.adaptive_fallback_activated.emit("disabled", reason)

    @Slot(str, str)
    def _on_adaptive_signal_queued(self, mode: str, reason: str) -> None:
        if qt_is_valid(self):
            self.adaptive_fallback_activated.emit(mode, reason)

    @Slot(str)
    def _on_start_polling_queued(self, reason: str) -> None:
        if not qt_is_valid(self):
            return
        with self._lock:
            if self._is_stopped:
                return
            if not self._inotify_enabled():
                return
            git_dir = self._git_dir or self._resolve_repo_git_dir()
            if self._fallback is not None:
                self._fallback.stop()
            fallback = PollingFallback(
                self._repo_path,
                self.status_changed,
                parent=self,
                git_dir=git_dir,
            )
            self._fallback = fallback
            self._status_info = WatcherStatusInfo(
                mode="polling",
                is_fallback=True,
                watched_paths=(str(git_dir),),
                reason=reason,
            )
            fallback.start()
        self.adaptive_fallback_activated.emit("polling", reason)

    @Slot()
    def _on_fs_event_queued(self):
        if qt_is_valid(self):
            self._debounce_timer.start()

    @Slot()
    def _on_timer_timeout(self):
        if not qt_is_valid(self):
            return
        logger.debug(
            "[watcher] Debounce timer expired, emitting status_changed for %s",
            self._repo_path,
        )
        self.status_changed.emit()

    def _on_watchdog_event(self):
        self._raw_event_signal.emit()

    def _schedule_git_dir_inotify(self, git_dir: Path, reason: str) -> WatcherStatusInfo:
        observer = Observer()
        handler = _GitDirMetadataHandler(self._on_watchdog_event, git_dir)
        watched_paths: list[str] = []

        observer.schedule(handler, str(git_dir), recursive=False)
        watched_paths.append(str(git_dir))

        refs_dir = git_dir / "refs"
        if refs_dir.is_dir():
            observer.schedule(handler, str(refs_dir), recursive=True)
            watched_paths.append(str(refs_dir))

        info_dir = git_dir / "info"
        if info_dir.is_dir():
            observer.schedule(handler, str(info_dir), recursive=False)
            watched_paths.append(str(info_dir))

        try:
            observer.start()
        except Exception:
            try:
                observer.stop()
                observer.join(timeout=0.5)
            except (OSError, RuntimeError) as stop_exc:
                logger.debug("Cleanup of failed Tier-2 observer raised: %s", stop_exc)
            raise

        with self._lock:
            if self._is_stopped:
                try:
                    observer.stop()
                    observer.join(timeout=0.5)
                except (OSError, RuntimeError) as stop_exc:
                    logger.debug("Cleanup of stopped Tier-2 observer raised: %s", stop_exc)
                return self._status_info
            self._observer = observer
            info = WatcherStatusInfo(
                mode="git_dir_inotify",
                is_fallback=True,
                watched_paths=tuple(watched_paths),
                reason=reason,
            )
            self._status_info = info
        return info

    def start(self) -> None:
        """Starts the filesystem observer in a background daemon thread to avoid blocking UI."""
        self._connect_settings_registry()
        with self._lock:
            self._is_stopped = False
            self._ready_event.clear()

        if not self._inotify_enabled():
            with self._lock:
                self._status_info = WatcherStatusInfo(
                    mode="disabled",
                    is_fallback=False,
                    watched_paths=(),
                    reason="Disabled by setting",
                )
            self._ready_event.set()
            return

        git_dir = self._resolve_repo_git_dir()
        with self._lock:
            self._git_dir = git_dir

        def _async_start():
            try:
                observer = Observer()
                handler = _WatchdogHandler(self._on_watchdog_event)
                try:
                    observer.schedule(handler, str(self._repo_path), recursive=True)
                    observer.start()
                except Exception:
                    try:
                        observer.stop()
                        observer.join(timeout=0.5)
                    except (OSError, RuntimeError) as stop_exc:
                        logger.debug("Cleanup of failed Tier-1 observer raised: %s", stop_exc)
                    raise

                with self._lock:
                    if self._is_stopped:
                        try:
                            observer.stop()
                            observer.join(timeout=0.5)
                        except (OSError, RuntimeError) as stop_exc:
                            logger.debug("Cleanup of stopped Tier-1 observer raised: %s", stop_exc)
                        return
                    self._observer = observer
                    self._status_info = WatcherStatusInfo(
                        mode="full_inotify",
                        is_fallback=False,
                        watched_paths=(str(self._repo_path),),
                        reason=None,
                    )
                logger.debug(
                    "[watcher] Started full inotify observer for %s",
                    self._repo_path,
                )
            except (OSError, Exception) as exc:
                with self._lock:
                    if self._is_stopped:
                        return
                reason = str(exc) or exc.__class__.__name__
                if _is_watch_limit_error(exc) and self._adaptive_fallback_enabled():
                    logger.warning(
                        "Full inotify hit watch limit (%s); switching to .git-only watching for %s",
                        exc,
                        self._repo_path,
                    )
                    try:
                        self._schedule_git_dir_inotify(git_dir, reason)
                        self._adaptive_signal.emit("git_dir_inotify", reason)
                        return
                    except (OSError, Exception) as tier2_exc:
                        reason = str(tier2_exc) or tier2_exc.__class__.__name__
                        logger.warning(
                            "Tier-2 .git inotify failed (%s); falling back to polling for %s",
                            tier2_exc,
                            self._repo_path,
                        )
                else:
                    logger.warning(
                        "Inotify observer failed (%s); falling back to polling for %s",
                        exc,
                        self._repo_path,
                    )

                self._start_polling_signal.emit(reason)
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

    def _stop_active_backends(self) -> None:
        self._debounce_timer.stop()
        with self._lock:
            obs = self._observer
            self._observer = None
            fb = self._fallback
            self._fallback = None
        if obs is not None:
            try:
                obs.stop()
                obs.join(timeout=0.5)
            except (OSError, RuntimeError) as e:
                logger.debug("Error stopping observer: %s", e)
        if fb is not None:
            fb.stop()

    @Slot()
    def stop(self) -> None:
        with self._lock:
            self._is_stopped = True
        self._disconnect_settings_registry()
        self._stop_active_backends()
        logger.debug("[watcher] Stopped watcher for %s", self._repo_path)
