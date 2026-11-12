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


def _resolve_common_git_dir(git_dir: Path) -> Path:
    """Resolve the shared common git directory for linked worktrees."""
    resolved = git_dir.resolve()
    commondir_file = resolved / "commondir"
    if commondir_file.is_file():
        try:
            raw = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                candidate = Path(raw)
                return candidate if candidate.is_absolute() else (resolved / candidate).resolve()
        except OSError:
            return resolved
    return resolved


def _normalize_dir_prefix(path: Path | str | None) -> str | None:
    if path is None:
        return None
    try:
        s = str(Path(path).resolve())
    except OSError:
        s = str(path)
    s = s.replace("\\", "/").rstrip("/")
    return s or None


def _is_inside_git_metadata(
    norm: str,
    git_dir_prefix: str | None = None,
    common_dir_prefix: str | None = None,
) -> bool:
    """Return True if *norm* resides under a .git metadata dir or known git_dir/commondir."""
    if "/.git/" in norm or norm.startswith(".git/"):
        return True
    for prefix in (git_dir_prefix, common_dir_prefix):
        if prefix and norm.startswith(prefix + "/"):
            return True
    return False


def _is_commit_graph_housekeeping(
    path_str: str,
    *,
    git_dir_prefix: str | None = None,
    common_dir_prefix: str | None = None,
) -> bool:
    """Return True for internal git commit-graph maintenance artifacts inside git metadata."""
    if not path_str:
        return False
    norm = path_str.replace("\\", "/")
    if not _is_inside_git_metadata(norm, git_dir_prefix, common_dir_prefix):
        return False
    name = norm.rsplit("/", 1)[-1]
    if name == "commit-graph.lock" or (
        name.startswith("commit-graph") and name.endswith(".lock")
    ):
        return True
    if "/objects/info/commit-graph" in norm:
        return True
    return False


class _WatchdogHandler(FileSystemEventHandler):
    def __init__(
        self,
        callback,
        *,
        git_dir: Path | str | None = None,
        common_dir: Path | str | None = None,
    ):
        super().__init__()
        self._callback = callback
        self._git_dir_prefix = _normalize_dir_prefix(git_dir)
        self._common_dir_prefix = _normalize_dir_prefix(common_dir)

    def _is_git_internal(self, path_str: str) -> bool:
        if _is_commit_graph_housekeeping(
            path_str,
            git_dir_prefix=self._git_dir_prefix,
            common_dir_prefix=self._common_dir_prefix,
        ):
            return True
        norm = path_str.replace("\\", "/")
        return "/.git/" in norm or norm.endswith("/.git") or norm.endswith(".git")

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

    def __init__(self, callback, git_dir: Path, *, common_dir: Path | str | None = None):
        super().__init__()
        self._callback = callback
        resolved_git = git_dir.resolve()
        self._git_dir_prefix = _normalize_dir_prefix(resolved_git)
        resolved_common = (
            Path(common_dir).resolve()
            if common_dir is not None
            else _resolve_common_git_dir(resolved_git)
        )
        self._common_dir_prefix = _normalize_dir_prefix(resolved_common)
        self._refs_prefix = str(resolved_git / "refs")
        self._tracked_files = frozenset(
            {
                str(resolved_git / "HEAD"),
                str(resolved_git / "index"),
                str(resolved_git / "packed-refs"),
                str(resolved_git / "config"),
                str(resolved_git / "config.worktree"),
                str(resolved_git / "info" / "sparse-checkout"),
            }
        )

    def _is_relevant(self, raw_path: str) -> bool:
        if (
            not raw_path
            or raw_path.endswith(".lock")
            or _is_commit_graph_housekeeping(
                raw_path,
                git_dir_prefix=self._git_dir_prefix,
                common_dir_prefix=self._common_dir_prefix,
            )
        ):
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
        debounce_ms: int | None = None,
        settings_registry: SettingsRegistry | None = None,
    ):
        super().__init__(parent)
        self._repo_path = Path(repo_path)
        self._settings_registry = settings_registry
        self._settings_connected = False
        self._observer: Observer | None = None
        self._fallback: PollingFallback | None = None
        self._is_stopped = False
        self._event_pending = False
        self._suppress_depth = 0
        self._pending_resumes = 0
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

        reg = self._resolve_registry()
        if debounce_ms is not None:
            effective_debounce = debounce_ms
        elif reg is not None:
            effective_debounce = reg.get_int("watcher.debounce_ms", str(self._repo_path))
        else:
            effective_debounce = 300

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(max(50, effective_debounce))
        self._debounce_timer.timeout.connect(self._on_timer_timeout)

        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.timeout.connect(self._on_resume_timer_timeout)

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

    def suspend(self) -> None:
        """Suppress filesystem event queuing during internal mass worktree writes."""
        with self._lock:
            self._suppress_depth = max(0, self._suppress_depth - self._pending_resumes) + 1
            self._pending_resumes = 0
            self._event_pending = False
        if qt_is_valid(self):
            self._resume_timer.stop()
            self._debounce_timer.stop()

    @Slot()
    def _on_resume_timer_timeout(self) -> None:
        with self._lock:
            if self._is_stopped:
                self._suppress_depth = 0
                self._pending_resumes = 0
                return
            consume = self._pending_resumes
            self._pending_resumes = 0
            self._suppress_depth = max(0, self._suppress_depth - consume)
            self._event_pending = False

    def resume(self, grace_ms: int = 150) -> None:
        """Re-enable event queuing immediately or after a grace window for kernel tail events."""
        if grace_ms <= 0 or not qt_is_valid(self):
            with self._lock:
                if self._is_stopped:
                    self._suppress_depth = 0
                    self._pending_resumes = 0
                    return
                self._suppress_depth = max(0, self._suppress_depth - 1)
                if self._pending_resumes > self._suppress_depth:
                    self._pending_resumes = self._suppress_depth
                self._event_pending = False
            if qt_is_valid(self) and self._pending_resumes == 0:
                self._resume_timer.stop()
            return
        with self._lock:
            if self._is_stopped:
                return
            self._pending_resumes += 1
        if qt_is_valid(self):
            self._resume_timer.start(grace_ms)

    @Slot()
    def _on_fs_event_queued(self):
        with self._lock:
            self._event_pending = False
            if self._is_stopped or self._suppress_depth > 0:
                return
        if qt_is_valid(self):
            self._debounce_timer.start()

    @Slot()
    def _on_timer_timeout(self):
        if not qt_is_valid(self):
            return
        with self._lock:
            if self._is_stopped or self._suppress_depth > 0:
                return
        logger.debug(
            "[watcher] Debounce timer expired, emitting status_changed for %s",
            self._repo_path,
        )
        self.status_changed.emit()

    def _on_watchdog_event(self):
        with self._lock:
            if self._is_stopped or self._suppress_depth > 0 or self._event_pending:
                return
            self._event_pending = True
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
            self._event_pending = False
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
        common_dir = _resolve_common_git_dir(git_dir)
        with self._lock:
            self._git_dir = git_dir

        def _async_start():
            try:
                observer = Observer()
                handler = _WatchdogHandler(
                    self._on_watchdog_event,
                    git_dir=git_dir,
                    common_dir=common_dir,
                )
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
        if qt_is_valid(self):
            self._resume_timer.stop()
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
            self._event_pending = False
            self._suppress_depth = 0
            self._pending_resumes = 0
        self._disconnect_settings_registry()
        self._stop_active_backends()
        logger.debug("[watcher] Stopped watcher for %s", self._repo_path)
