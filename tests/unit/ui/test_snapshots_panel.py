"""Unit tests for SnapshotsPanel widget (Phase 2)."""

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from wrench.core import snapshots
from wrench.storage import repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.snapshots_panel.snapshots_panel import SnapshotsPanel


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestSnapshotsPanel:
    def test_snapshots_panel_lists_snapshots(self, simple_repo, db_conn):
        repo_registry.add_repo(db_conn, str(simple_repo.path))
        panel = SnapshotsPanel(db_conn)
        panel.show()
        panel.set_repo(simple_repo)

        assert panel.table.rowCount() == 0

        # Create snapshots
        snapshots.take_snapshot(simple_repo, "commit", label="Auto 1", conn=db_conn)
        snapshots.take_snapshot(simple_repo, "manual", label="Manual 1", conn=db_conn)

        panel.refresh()
        assert panel.table.rowCount() == 2
