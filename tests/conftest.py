"""Root pytest configuration and fixture registration."""

import os

# Ensure headless Qt test environment
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest_plugins = ["tests.fixtures.git_repos"]
