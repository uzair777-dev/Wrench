"""Unit tests for MainWindow repository menu, remote operations, and error routing."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from wrench.core.engine import RepoHandle
from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CloneAbortedError,
    MergeRequiredError,
    PushRejectedError,
    RemoteNotFoundError,
)
from wrench.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def test_db(tmp_path: Path):
    db_file = tmp_path / "test_app.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.execute("""CREATE TABLE repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            last_opened_at TEXT,
            is_pinned INTEGER DEFAULT 0
        )""")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def repo_with_remote(tmp_path: Path):
    repo_path = tmp_path / "remote_repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))

    sig = pygit2.Signature("Test", "test@example.com")
    tree = pygit2_repo.TreeBuilder().write()
    pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])

    pygit2_repo.remotes.create("origin", "https://github.com/example/repo.git")
    return RepoHandle(pygit2_repo, repo_path)


class TestMainWindowRemotes:
    def test_repository_menu_exists(self, test_db):
        win = MainWindow(conn=test_db)
        menu_bar = win.menuBar()

        # Check Repository menu
        repo_menu = None
        for action in menu_bar.actions():
            if action.menu() and "Repository" in action.menu().title():
                repo_menu = action.menu()
                break

        assert repo_menu is not None, "Repository menu not found in menu bar"

        action_texts = [a.text() for a in repo_menu.actions()]
        assert any("Fetch" in t for t in action_texts)
        assert any("Pull" in t for t in action_texts)
        assert any("Push" in t for t in action_texts)
        assert any("Remotes" in t for t in action_texts)

        win.close()

    def test_get_default_remote_resolves_upstream_tracking(self, test_db, tmp_path):
        repo_path = tmp_path / "tracking_repo"
        repo_path.mkdir()
        pygit2_repo = pygit2.init_repository(str(repo_path))

        sig = pygit2.Signature("Test", "test@example.com")
        tree = pygit2_repo.TreeBuilder().write()
        pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])

        pygit2_repo.remotes.create("origin", "https://github.com/example/repo.git")
        pygit2_repo.remotes.create("upstream", "https://github.com/upstream/repo.git")

        # Configure master branch to track upstream
        branch_name = pygit2_repo.head.shorthand
        pygit2_repo.config[f"branch.{branch_name}.remote"] = "upstream"

        win = MainWindow(conn=test_db)
        win._current_repo = RepoHandle(pygit2_repo, repo_path)

        assert win._get_default_remote() == "upstream"
        win.close()

    def test_get_default_remote_falls_back_to_origin(self, test_db, tmp_path):
        repo_path = tmp_path / "fallback_repo"
        repo_path.mkdir()
        pygit2_repo = pygit2.init_repository(str(repo_path))

        sig = pygit2.Signature("Test", "test@example.com")
        tree = pygit2_repo.TreeBuilder().write()
        pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])

        pygit2_repo.remotes.create("mirror", "https://github.com/mirror/repo.git")
        pygit2_repo.remotes.create("origin", "https://github.com/example/repo.git")

        win = MainWindow(conn=test_db)
        win._current_repo = RepoHandle(pygit2_repo, repo_path)

        assert win._get_default_remote() == "origin"
        win.close()

    def test_get_default_remote_falls_back_to_first_remote(self, test_db, tmp_path):
        repo_path = tmp_path / "no_origin_repo"
        repo_path.mkdir()
        pygit2_repo = pygit2.init_repository(str(repo_path))

        sig = pygit2.Signature("Test", "test@example.com")
        tree = pygit2_repo.TreeBuilder().write()
        pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])

        pygit2_repo.remotes.create("custom_remote", "https://github.com/custom/repo.git")

        win = MainWindow(conn=test_db)
        win._current_repo = RepoHandle(pygit2_repo, repo_path)

        assert win._get_default_remote() == "custom_remote"
        win.close()

    def test_fetch_remote_triggers_background_fetch(self, test_db, repo_with_remote):
        win = MainWindow(conn=test_db)
        win._current_repo = repo_with_remote

        with (
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch("wrench.ui.main_window.BusyOperationDialog") as mock_dialog,
        ):
            mock_dlg_instance = MagicMock()
            mock_dialog.return_value = mock_dlg_instance

            win._on_fetch_remote()

            assert mock_bg.called
            fn = mock_bg.call_args[0][0]
            from wrench.core import engine

            assert fn == engine.fetch
            assert mock_bg.call_args[0][1] == repo_with_remote
            assert mock_bg.call_args[0][2] == "origin"

        win.close()

    def test_pull_remote_triggers_background_pull(self, test_db, repo_with_remote):
        win = MainWindow(conn=test_db)
        win._current_repo = repo_with_remote

        with (
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch("wrench.ui.main_window.BusyOperationDialog") as mock_dialog,
        ):
            mock_dlg_instance = MagicMock()
            mock_dialog.return_value = mock_dlg_instance

            win._on_pull_remote()

            assert mock_bg.called
            fn = mock_bg.call_args[0][0]
            from wrench.core import engine

            assert fn == engine.pull
            assert mock_bg.call_args[0][1] == repo_with_remote
            assert mock_bg.call_args[0][2] == "origin"

        win.close()

    def test_push_remote_triggers_background_push(self, test_db, repo_with_remote):
        win = MainWindow(conn=test_db)
        win._current_repo = repo_with_remote

        with (
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch("wrench.ui.main_window.BusyOperationDialog") as mock_dialog,
        ):
            mock_dlg_instance = MagicMock()
            mock_dialog.return_value = mock_dlg_instance

            win._on_push_remote()

            assert mock_bg.called
            fn = mock_bg.call_args[0][0]
            from wrench.core import engine

            assert fn == engine.push
            assert mock_bg.call_args[0][1] == repo_with_remote
            assert mock_bg.call_args[0][2] == "origin"

        win.close()

    def test_manage_remotes_opens_dialog(self, test_db, repo_with_remote):
        win = MainWindow(conn=test_db)
        win._current_repo = repo_with_remote

        with patch("wrench.ui.main_window.RemotesDialog") as mock_dialog_cls:
            mock_dlg = MagicMock()
            mock_dialog_cls.return_value = mock_dlg

            win._on_manage_remotes()

            assert mock_dialog_cls.called
            assert mock_dlg.exec.called

        win.close()

    def test_clone_repo_routes_through_background_worker(self, test_db, tmp_path):
        win = MainWindow(conn=test_db)

        with (
            patch(
                "wrench.ui.main_window.QInputDialog.getText",
                return_value=("https://github.com/org/repo.git", True),
            ),
            patch(
                "wrench.ui.main_window.QFileDialog.getExistingDirectory",
                return_value=str(tmp_path),
            ),
            patch("wrench.ui.main_window.run_in_background") as mock_bg,
            patch("wrench.ui.main_window.BusyOperationDialog"),
        ):
            win._on_clone_repo()

            assert mock_bg.called
            from wrench.core import engine

            assert mock_bg.call_args[0][0] == engine.clone_repo
            assert mock_bg.call_args[0][1] == "https://github.com/org/repo.git"

        win.close()

    def test_error_routing_auth_required(self, test_db):
        win = MainWindow(conn=test_db)
        exc = AuthRequiredError("github.com")

        with patch.object(QMessageBox, "warning") as mock_warn:
            win._route_remote_error(exc, "origin")
            assert mock_warn.called
            assert "github.com" in mock_warn.call_args[0][2]

        win.close()

    def test_error_routing_auth_failed(self, test_db):
        win = MainWindow(conn=test_db)
        exc = AuthFailedError("gitlab.com")

        with patch.object(QMessageBox, "critical") as mock_crit:
            win._route_remote_error(exc, "origin")
            assert mock_crit.called
            assert "gitlab.com" in mock_crit.call_args[0][2]

        win.close()

    def test_error_routing_clone_aborted_clean(self, test_db):
        win = MainWindow(conn=test_db)
        exc = CloneAbortedError()

        with (
            patch.object(QMessageBox, "critical") as mock_crit,
            patch.object(QMessageBox, "warning") as mock_warn,
        ):
            win._route_remote_error(exc, "origin", op="clone")
            assert not mock_crit.called
            assert not mock_warn.called

        win.close()

    def test_error_routing_remote_not_found(self, test_db):
        win = MainWindow(conn=test_db)
        exc = RemoteNotFoundError("upstream")

        with (
            patch.object(QMessageBox, "warning"),
            patch.object(win, "_on_manage_remotes") as mock_remotes,
        ):
            win._route_remote_error(exc, "upstream")
            assert mock_remotes.called

        win.close()

    def test_error_routing_push_rejected(self, test_db):
        win = MainWindow(conn=test_db)
        exc = PushRejectedError("rejected non-fast-forward")

        with patch.object(QMessageBox, "exec", return_value=0):
            win._route_remote_error(exc, "origin", branch="main", op="push")

        win.close()

    def test_error_routing_merge_required(self, test_db):
        win = MainWindow(conn=test_db)
        exc = MergeRequiredError("Not possible to fast-forward")

        with patch.object(QMessageBox, "exec", return_value=0):
            win._route_remote_error(exc, "origin", branch="main", op="pull")

        win.close()

    def test_repo_changed_triggers_async_probe(self, test_db, repo_with_remote):
        win = MainWindow(conn=test_db)
        with (
            patch("wrench.ui.main_window.RepoWatcher"),
            patch("wrench.core.engine.probe_remotes_async") as mock_probe,
        ):
            win._on_repo_changed(str(repo_with_remote.path))
            assert mock_probe.called
            assert mock_probe.call_args[0][0].path == repo_with_remote.path

        win.close()
