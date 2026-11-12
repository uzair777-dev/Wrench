"""Tests for Phase 4.1 clone-time account picker and rollback logic via CloneDialog."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from wrench.core.exceptions import GitCommandError
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.dialogs.clone_dialog import CloneDialog
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
        res = fn(*args, **{k: v for k, v in kwargs.items() if k in ("filter_spec", "sparse")})
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


def _drive_clone_dialog(url: str, target_dir: Path, *, accept: bool = True, row: int = 0):
    observed: list[bool] = []

    def _exec(dlg):
        if isinstance(dlg, CloneDialog):
            dlg.url_input.setText(url)
            dlg.dest_parent_input.setText(str(target_dir))
            # Check visibility via isHidden() since modal mock never calls .show()
            observed.append(not dlg.account_group.isHidden())
            if not dlg.account_group.isHidden() and dlg.account_list.count() > row:
                dlg.account_list.setCurrentRow(row)
            return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected
        return QDialog.DialogCode.Accepted

    return _exec, observed


class TestClonePicker:
    def test_clone_zero_accounts_proceeds_anonymous(self, db_conn, tmp_path):
        """With zero matching accounts, picker stays hidden and clone stays anonymous."""
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"
        exec_fn, picker_visible = _drive_clone_dialog(
            "https://github.com/org/repo.git", target_dir, accept=True
        )

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()) as mock_clone,
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
        ):
            win._on_clone_repo()

            assert picker_visible == [False]
            assert mock_bg.called
            assert mock_clone.called
            expected_dest = str(target_dir / "repo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()

    def test_clone_single_account_no_picker(self, db_conn, tmp_path):
        """With exactly one matching account, account picker stays hidden."""
        _add_dummy_account(db_conn, "Work Account", "alice")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"
        exec_fn, picker_visible = _drive_clone_dialog(
            "https://github.com/org/repo.git", target_dir, accept=True
        )

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
        ):
            win._on_clone_repo()

            assert picker_visible == [False]
            assert mock_bg.called
            expected_dest = str(target_dir / "repo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()

    def test_clone_two_accounts_picker_cancelled(self, db_conn, tmp_path):
        """Cancelling when multiple accounts match creates no directory, worker, or registry row."""
        _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"
        exec_fn, picker_visible = _drive_clone_dialog(
            "https://github.com/org/repo.git", target_dir, accept=False
        )

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
        ):
            win._on_clone_repo()

            assert picker_visible == [True]
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
        exec_fn, picker_visible = _drive_clone_dialog(
            "https://github.com/org/myrepo.git", target_dir, accept=True, row=0
        )

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch("wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background),
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
        ):
            win._on_clone_repo()

            assert picker_visible == [True]
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
        exec_fn, _ = _drive_clone_dialog(
            "https://github.com/org/failrepo.git", target_dir, accept=True
        )

        clone_error = GitCommandError(["clone"], 128, "fatal: repository not found")

        def fake_clone(*args, **kwargs):
            raise clone_error

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch("wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background),
            patch("wrench.core.engine.clone_repo", side_effect=fake_clone),
            patch.object(win, "_route_remote_error") as mock_route,
        ):
            win._on_clone_repo()

            expected_dest = str(target_dir / "failrepo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is None, "Pre-created repo row must be rolled back on clone failure"
            assert mock_route.called
            assert mock_route.call_args[0][0] == clone_error
        win.close()

    def test_clone_ssh_url_no_picker_even_with_multiple_accounts(self, db_conn, tmp_path):
        """SSH URLs do not trigger account matching or inline picker (HTTPS only rule)."""
        _add_dummy_account(db_conn, "Account 1", "alice")
        _add_dummy_account(db_conn, "Account 2", "bob")
        win = MainWindow(conn=db_conn)
        target_dir = tmp_path / "clone_dest"
        exec_fn, picker_visible = _drive_clone_dialog(
            "git@github.com:org/sshrepo.git", target_dir, accept=True
        )

        with (
            patch.object(win, "_exec_dialog", side_effect=exec_fn),
            patch(
                "wrench.ui.main_window.run_in_background", side_effect=_sync_run_in_background
            ) as mock_bg,
            patch("wrench.core.engine.clone_repo", return_value=MagicMock()),
            patch.object(win, "_on_repo_changed"),
            patch.object(win.changes_tab, "load_repos"),
        ):
            win._on_clone_repo()

            assert picker_visible == [False]
            assert mock_bg.called
            expected_dest = str(target_dir / "sshrepo")
            record = repo_registry.get_repo_by_path(db_conn, expected_dest)
            assert record is not None
        win.close()

    def test_clone_empty_dest_ux_and_repo_name_sanitization(self, db_conn, tmp_path):
        """Empty destination shows clean prompt text and traversal-like URLs sanitize safely."""
        dlg = CloneDialog(conn=db_conn)
        assert dlg.resolved_dest_label.text() == "Choose a folder above to set destination path"
        assert "<choose destination>" not in dlg.resolved_dest_label.text().lower()
        assert "<destination>/repository" in dlg.preview_bar.preview_text

        for evil_url in [
            "https://example.com/org/..",
            "https://example.com/org/..git",
            "https://example.com/org/.",
            "https://example.com/org/--upload-pack.git",
            "https://example.com/org/.git",
        ]:
            dlg.url_input.setText(evil_url)
            assert dlg.repo_name() == "repository"

        dlg.url_input.setText("https://example.com/org/")
        assert dlg.repo_name() == "org"

        dlg.url_input.setText("git@github.com:org/monorepo.git?tab=1#top")
        assert dlg.repo_name() == "monorepo"
        dlg.dest_parent_input.setText(str(tmp_path))
        assert dlg.resolved_dest_label.text() == str(tmp_path / "monorepo")
        dlg.close()

        # MainWindow boundary defense if a stubbed dialog injects a '..' repo_name()
        win = MainWindow(conn=db_conn)
        safe_parent = tmp_path / "safe_root"
        safe_parent.mkdir(parents=True, exist_ok=True)

        class _BadCloneStub(CloneDialog):
            def repo_name(self) -> str:
                return ".."

        def _fake_exec(d):
            d.url_input.setText("https://github.com/org/repo.git")
            d.dest_parent_input.setText(str(safe_parent))
            return QDialog.DialogCode.Accepted

        with (
            patch("wrench.ui.main_window.CloneDialog", _BadCloneStub),
            patch.object(win, "_exec_dialog", side_effect=_fake_exec),
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch("wrench.ui.main_window.QMessageBox.critical") as mock_crit,
        ):
            win._on_clone_repo()
            assert not mock_bg.called
            assert mock_crit.called
        win.close()
