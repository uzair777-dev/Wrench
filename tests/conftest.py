"""Root pytest configuration and fixture registration."""

import os
import tempfile
from pathlib import Path

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
