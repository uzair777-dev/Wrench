"""Unit tests for MainWindow session persistence including History tab column sizes."""

import json
import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from wrench.storage import repo_registry, settings
from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


def test_main_window_history_column_sizes_persisted(multi_commit_repo):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    repo_registry.add_repo(conn, str(multi_commit_repo.path), "multi_repo")

    # 1. Launch MainWindow and resize history columns
    win1 = MainWindow(conn=conn)
    win1.show()
    win1._on_repo_changed(str(multi_commit_repo.path))

    header1 = win1.history_tab.graph_widget.horizontalHeader()
    header1.resizeSection(0, 160)
    header1.resizeSection(1, 420)
    header1.resizeSection(2, 210)
    header1.resizeSection(3, 150)
    header1.resizeSection(4, 110)

    # Save session
    win1._save_session_state()
    win1.close()

    # Verify session JSON contains history_tab state
    raw_state = settings.get_setting(conn, "ui.session_state")
    assert raw_state is not None
    state_dict = json.loads(raw_state)
    assert "history_tab" in state_dict
    assert "header_hex" in state_dict["history_tab"]
    assert state_dict["history_tab"]["header_hex"] != ""

    # 2. Relaunch MainWindow with same DB connection
    win2 = MainWindow(conn=conn)
    win2.show()

    header2 = win2.history_tab.graph_widget.horizontalHeader()
    assert header2.sectionSize(0) == 160
    assert header2.sectionSize(1) == 420
    assert header2.sectionSize(2) == 210
    assert header2.sectionSize(3) == 150
    assert header2.sectionSize(4) == 110
    win2.close()
