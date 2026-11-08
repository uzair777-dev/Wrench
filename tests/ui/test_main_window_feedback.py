"""Integration tests for Phase 4.6 MainWindow wiring."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QKeySequence

from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


def test_activity_dock_exists(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    win.show()
    assert hasattr(win, "_activity_dock")
    assert win._activity_dock is not None
    assert hasattr(win, "_activity_log")
    assert win._activity_log is not None
    assert win._activity_dock.isVisible()
    win.close()


def test_about_menu_action_exists(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    help_menu = None
    for action in win.menuBar().actions():
        if "help" in action.text().lower():
            help_menu = action.menu()
            break
    assert help_menu is not None
    about_actions = [a for a in help_menu.actions() if "about" in a.text().lower()]
    assert len(about_actions) >= 1

    with patch("wrench.ui.main_window.AboutDialog") as mock_about_cls:
        mock_instance = MagicMock()
        mock_about_cls.return_value = mock_instance
        about_actions[0].trigger()
        mock_about_cls.assert_called_once_with(parent=win)
        mock_instance.exec.assert_called_once()
    win.close()


def test_humor_toggle_menu_action(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    assert hasattr(win, "act_humor_lines")
    assert win.act_humor_lines.isCheckable()
    assert win.act_humor_lines.isChecked()  # default on

    # Toggle off
    win.act_humor_lines.setChecked(False)
    assert not win._is_humor_lines_enabled()

    # Toggle on
    win.act_humor_lines.setChecked(True)
    assert win._is_humor_lines_enabled()
    win.close()


def test_toggle_activity_dock_action(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    win.show()
    assert hasattr(win, "act_toggle_activity_dock")
    assert win.act_toggle_activity_dock.shortcut() == QKeySequence("Ctrl+`")

    assert not win._activity_dock._expanded
    win.act_toggle_activity_dock.trigger()
    assert win._activity_dock._expanded
    assert win._activity_dock.scrollback.isVisible()

    win.act_toggle_activity_dock.trigger()
    assert not win._activity_dock._expanded
    assert not win._activity_dock.scrollback.isVisible()
    win.close()
