"""Root pytest configuration and fixture registration."""

import os
import tempfile
from pathlib import Path

import pytest

# Ensure headless Qt test environment
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Ensure deterministic git test identity for isolated test environments (e.g. CI)
os.environ.setdefault("GIT_AUTHOR_NAME", "Test Runner")
os.environ.setdefault("GIT_AUTHOR_EMAIL", "runner@wrench.test")
os.environ.setdefault("GIT_COMMITTER_NAME", "Test Runner")
os.environ.setdefault("GIT_COMMITTER_EMAIL", "runner@wrench.test")

# Ensure isolated XDG paths for tests so tests never touch host directories
# or fail on read-only environments
_test_xdg_base = Path(tempfile.gettempdir()) / "wrench_test_xdg"
_test_xdg_base.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_DATA_HOME", str(_test_xdg_base / "data"))
os.environ.setdefault("XDG_CONFIG_HOME", str(_test_xdg_base / "config"))
os.environ.setdefault("XDG_STATE_HOME", str(_test_xdg_base / "state"))
os.environ.setdefault("XDG_CACHE_HOME", str(_test_xdg_base / "cache"))

pytest_plugins = ["tests.fixtures.git_repos"]


@pytest.fixture(autouse=True)
def _cleanup_qt_after_test():
    """Safety-net teardown preventing Qt widget, timer, and worker leaks across tests."""
    yield
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    from wrench.ui import workers
    from wrench.watcher.inotify_watcher import stop_all_active_watchers

    stop_all_active_watchers()

    top_levels = list(app.topLevelWidgets())
    for widget in top_levels:
        if shiboken6.isValid(widget):
            watcher = getattr(widget, "_watcher", None)
            if watcher is not None:
                try:
                    widget._watcher = None
                    watcher.stop()
                except Exception:
                    pass
            for timer in list(widget.findChildren(QTimer)):
                if shiboken6.isValid(timer) and timer.isActive():
                    timer.stop()
            widget.close()
            widget.deleteLater()

    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()

    pool = QThreadPool.globalInstance()
    if pool.activeThreadCount() > 0:
        pool.waitForDone(150)
    if workers._active_workers:
        workers.wait_for_active_workers(0.15)

    workers.clear_activity_log()
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
