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
    from PySide6.QtCore import QThreadPool, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    from wrench.ui import workers

    for widget in list(app.topLevelWidgets()):
        if shiboken6.isValid(widget):
            widget.close()

    app.processEvents()
    QThreadPool.globalInstance().waitForDone(2000)
    workers.wait_for_active_workers(2.0)
    app.processEvents()

    for widget in list(app.topLevelWidgets()):
        if shiboken6.isValid(widget):
            widget.close()
        if shiboken6.isValid(widget):
            for timer in list(widget.findChildren(QTimer)):
                if shiboken6.isValid(timer) and timer.isActive():
                    timer.stop()

    workers.clear_activity_log()
    app.processEvents()
