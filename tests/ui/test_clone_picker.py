"""Tests for Phase 4.1 clone-time account picker and rollback logic."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog

from wrench.core.exceptions import GitCommandError
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn(tmp_path: Path):
    db_file = tmp_path / "test_clone_picker.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


def _sync_run_in_background(fn, *args, on_finished=None, on_failed=None, **kwargs):
    try:
        res = fn(*args)
        if on_finished:
            on_finished(res)
    except Exception as exc:
        if on_failed:
            on_failed(exc)


def _add_dummy_account(conn, label, username, instance_url="https://github.com"):
    mock_backend = MagicMock()
    mock_backend.get_secret.return_value = "token_xyz"
    with patch("wrench.credentials.get_backend", return_value=mock_backend):
        return forge_accounts.add_account(
            conn,
            provider="github",
            instance_url=instance_url,
            label=label,
            username=username,
            token="ghp_dummy",
        )


class TestClonePicker:
    def test_clone_zero_accounts_proceeds_anonymous(self, db_conn, tmp_path):
        """With zero matching accounts, clone proceeds without picker dialog."""
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        with (
            patch.object(
                QInputDialog, "getText", return_value=("https://github.com/org/repo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()) as mock_clone,
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
            patch("PySide6.QtWidgets.QDialog.exec") as mock_dialog_exec,
        ):
            win._on_clone_repo()

            assert mock_dialog_exec.call_count == 0
            assert mock_bg.called
            assert mock_clone.called
            expected_dest = str(target_dir / "repo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()

    def test_clone_single_account_no_picker(self, db_conn, tmp_path):
        """With exactly one matching account, no picker is shown."""
        _add_dummy_account(db_conn, "Work Account", "alice")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        with (
            patch.object(
                QInputDialog, "getText", return_value=("https://github.com/org/repo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
            patch("PySide6.QtWidgets.QDialog.exec") as mock_dialog_exec,
        ):
            win._on_clone_repo()

            assert mock_dialog_exec.call_count == 0
            assert mock_bg.called
            expected_dest = str(target_dir / "repo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()

    def test_clone_two_accounts_picker_cancelled(self, db_conn, tmp_path):
        """Cancelling the picker creates no directory, no clone worker, no registry row."""
        _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        with (
            patch.object(
                QInputDialog, "getText", return_value=("https://github.com/org/repo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch(
                "PySide6.QtWidgets.QDialog.exec", return_value=QDialog.Rejected
            ) as mock_dialog_exec,
        ):
            win._on_clone_repo()

            assert mock_dialog_exec.called
            assert not mock_bg.called
            expected_dest = str(target_dir / "repo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is None
        win.close()

    def test_clone_two_accounts_picker_chosen_success(self, db_conn, tmp_path):
        """Choosing an account pre-creates row + link, and successful clone preserves it."""
        acc1_id = _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        with (
            patch.object(
                QInputDialog, "getText", return_value=("https://github.com/org/myrepo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch("wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background),
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
            patch("PySide6.QtWidgets.QDialog.exec", return_value=QDialog.Accepted),
        ):
            win._on_clone_repo()

            expected_dest = str(target_dir / "myrepo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
            link = forge_accounts.get_link_for_remote(db_conn, record.id, "origin")
            assert link is not None
            assert link.forge_account_id == acc1_id
            assert link.owner_slug == "org"
            assert link.repo_slug == "myrepo"
        win.close()

    def test_clone_failure_rollsback_precreated_row(self, db_conn, tmp_path):
        """Pre-created registry row is removed on clone failure (mandatory rollback)."""
        _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        clone_error = GitCommandError(["clone"], 128, "fatal: repository not found")

        def fake_clone(*args, **kwargs):
            raise clone_error

        with (
            patch.object(
                QInputDialog, "getText", return_value=("https://github.com/org/failrepo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch("wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background),
            patch("wrench.core.engine.clone_repo", side_effect=fake_clone),
            patch.object(win, "_route_remote_error") as mock_route,
            patch("PySide6.QtWidgets.QDialog.exec", return_value=QDialog.Accepted),
        ):
            win._on_clone_repo()

            expected_dest = str(target_dir / "failrepo")
            # Must be rolled back
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is None, "Pre-created repo row must be rolled back on clone failure"
            assert mock_route.called
            assert mock_route.call_args[0][0] == clone_error
        win.close()

    def test_clone_ssh_url_no_picker_even_with_multiple_accounts(self, db_conn, tmp_path):
        """SSH URLs do not trigger account matching or picker (HTTPS only rule)."""
        _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"

        with (
            patch.object(
                QInputDialog, "getText", return_value=("git@github.com:org/sshrepo.git", True)
            ),
            patch.object(QFileDialog, "getExistingDirectory", return_value=str(target_dir)),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
            patch("PySide6.QtWidgets.QDialog.exec") as mock_dialog_exec,
        ):
            win._on_clone_repo()

            assert mock_dialog_exec.call_count == 0
            assert mock_bg.called
            expected_dest = str(target_dir / "sshrepo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()
