"""Tests for Phase 4.2 auto-fetch on open/switch (FR-4.7)."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from wrench.core import engine
from wrench.storage import settings
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


class TestAutoFetchSetting:
    """Verifies the auto-fetch setting read/write and menu toggle."""

    def test_auto_fetch_enabled_by_default(self, qapp, db_conn):
        """When no setting is stored, auto-fetch should be enabled (True)."""
        mw = MainWindow(conn=db_conn)
        assert mw._is_auto_fetch_enabled() is True

    def test_auto_fetch_disabled_when_false(self, qapp, db_conn):
        """When setting is 'false', auto-fetch should be disabled."""
        settings.set_setting(db_conn, "repo.auto_fetch_on_open", "false")
        mw = MainWindow(conn=db_conn)
        assert mw._is_auto_fetch_enabled() is False

    def test_set_auto_fetch_persists(self, qapp, db_conn):
        """_set_auto_fetch writes to the database."""
        mw = MainWindow(conn=db_conn)
        mw._set_auto_fetch(False)
        assert settings.get_setting(db_conn, "repo.auto_fetch_on_open") == "false"

        mw._set_auto_fetch(True)
        assert settings.get_setting(db_conn, "repo.auto_fetch_on_open") == "true"

    def test_sync_auto_fetch_action(self, qapp, db_conn):
        """_sync_auto_fetch_action updates the menu checkmark without firing toggled."""
        mw = MainWindow(conn=db_conn)
        mw._set_auto_fetch(False)
        mw._sync_auto_fetch_action()
        assert mw.act_auto_fetch.isChecked() is False

        mw._set_auto_fetch(True)
        mw._sync_auto_fetch_action()
        assert mw.act_auto_fetch.isChecked() is True


class TestAutoFetchDecisionTree:
    """Verifies _maybe_auto_fetch respects setting, remotes, and generation."""

    @patch("wrench.ui.main_window.run_in_background")
    def test_auto_fetch_skipped_when_disabled(self, mock_run, qapp, db_conn):
        settings.set_setting(db_conn, "repo.auto_fetch_on_open", "false")
        mw = MainWindow(conn=db_conn)
        mw._maybe_auto_fetch(gen=1)
        mock_run.assert_not_called()

    @patch("wrench.ui.main_window.run_in_background")
    def test_auto_fetch_skipped_when_no_repo(self, mock_run, qapp, db_conn):
        mw = MainWindow(conn=db_conn)
        mw._current_repo = None
        mw._maybe_auto_fetch(gen=1)
        mock_run.assert_not_called()

    @patch("wrench.ui.main_window.run_in_background")
    def test_auto_fetch_skipped_when_no_remotes(self, mock_run, qapp, db_conn):
        mw = MainWindow(conn=db_conn)
        mw._current_repo = MagicMock()
        mw._get_default_remote = MagicMock(return_value=None)
        mw._maybe_auto_fetch(gen=1)
        mock_run.assert_not_called()

    @patch("wrench.ui.main_window.run_in_background")
    def test_auto_fetch_triggered_when_enabled(self, mock_run, qapp, db_conn):
        mw = MainWindow(conn=db_conn)
        mw._current_repo = MagicMock()
        mw._get_default_remote = MagicMock(return_value="origin")
        mw._maybe_auto_fetch(gen=1)
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        # First positional arg should be engine.fetch
        assert call_args[0][0] is engine.fetch

    def test_stale_gen_discards_finished(self, qapp, db_conn):
        """If generation has moved on, _on_auto_fetch_finished is a no-op."""
        mw = MainWindow(conn=db_conn)
        mw._repo_switch_generation = 5
        mw._refresh_after_git_op = MagicMock()

        mw._on_auto_fetch_finished("origin", gen=3)
        mw._refresh_after_git_op.assert_not_called()

        mw._on_auto_fetch_finished("origin", gen=5)
        mw._refresh_after_git_op.assert_called_once()

    def test_stale_gen_discards_failed(self, qapp, db_conn):
        """If generation has moved on, _on_auto_fetch_failed is a no-op."""
        mw = MainWindow(conn=db_conn)
        mw._repo_switch_generation = 5

        # Should not raise or show anything for stale gen
        mw._on_auto_fetch_failed(Exception("network error"), gen=3)

    def test_failed_shows_status_bar_transient(self, qapp, db_conn):
        """On current-gen failure, a transient status bar message is shown."""
        mw = MainWindow(conn=db_conn)
        mw._repo_switch_generation = 1

        mw._on_auto_fetch_failed(Exception("auth timeout"), gen=1)
        # The status bar should contain the message (not a modal)
        msg = mw.statusBar().currentMessage()
        assert "Auto-fetch skipped" in msg
