"""Unit tests for RemotesDialog (Phase 3)."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from wrench.core.engine import RepoHandle
from wrench.ui.dialogs.remotes_dialog import RemotesDialog


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn(tmp_path: Path):
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def repo_with_remote(tmp_path: Path):
    """Create a temporary repo with an 'origin' remote configured."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))

    # Add initial commit
    sig = pygit2.Signature("Test", "test@example.com")
    tree = pygit2_repo.TreeBuilder().write()
    pygit2_repo.create_commit("HEAD", sig, sig, "Initial commit", tree, [])

    # Configure a remote
    pygit2_repo.remotes.create("origin", "https://github.com/example/repo.git")

    handle = RepoHandle(pygit2_repo, repo_path)
    return handle


class TestRemotesDialog:
    def test_remotes_dialog_loads_remotes(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)
        assert dialog.windowTitle() == "Manage Remotes"

        table = dialog.table
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "origin"
        assert table.item(0, 1).text() == "https://github.com/example/repo.git"
        assert table.item(0, 2).text() == "Never"
        assert "Unknown" in table.item(0, 3).text()

        dialog.close()

    def test_remotes_dialog_add_remote(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)

        with patch("wrench.ui.dialogs.remotes_dialog.AddRemoteDialog.get_remote_data") as mock_get:
            mock_get.return_value = ("upstream", "https://github.com/upstream/repo.git")
            dialog._on_add_remote()

        table = dialog.table
        assert table.rowCount() == 2
        names = [table.item(i, 0).text() for i in range(2)]
        assert "origin" in names
        assert "upstream" in names

        remotes = [r.name for r in repo_with_remote.pygit2_repo.remotes]
        assert "upstream" in remotes

        dialog.close()

    def test_remotes_dialog_add_remote_validation_error(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)

        # Duplicate remote name
        with (
            patch("wrench.ui.dialogs.remotes_dialog.AddRemoteDialog.get_remote_data") as mock_get,
            patch.object(QMessageBox, "warning") as mock_warn,
        ):
            mock_get.return_value = ("origin", "https://github.com/another/repo.git")
            dialog._on_add_remote()

            assert mock_warn.called
            assert dialog.table.rowCount() == 1

        dialog.close()

    def test_remotes_dialog_edit_remote_url(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)

        # Select first row
        dialog.table.selectRow(0)

        with patch(
            "wrench.ui.dialogs.remotes_dialog.QInputDialog.getText",
            return_value=("https://github.com/new/repo.git", True),
        ):
            dialog._on_edit_remote()

        assert dialog.table.item(0, 1).text() == "https://github.com/new/repo.git"
        remote = repo_with_remote.pygit2_repo.remotes["origin"]
        assert remote.url == "https://github.com/new/repo.git"

        dialog.close()

    def test_remotes_dialog_remove_remote(self, repo_with_remote, db_conn):
        # Add another remote first
        repo_with_remote.pygit2_repo.remotes.create(
            "upstream", "https://github.com/upstream/repo.git"
        )
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)
        assert dialog.table.rowCount() == 2

        # Select upstream row (row 1 after sorting)
        row_to_select = 0 if dialog.table.item(0, 0).text() == "upstream" else 1
        dialog.table.selectRow(row_to_select)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog._on_remove_remote()

        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "origin"
        remotes = [r.name for r in repo_with_remote.pygit2_repo.remotes]
        assert "upstream" not in remotes

        dialog.close()

    def test_remotes_dialog_refresh_status(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)

        with patch("wrench.core.write_ops.run_git") as mock_run_git:
            from unittest.mock import MagicMock

            res = MagicMock()
            res.returncode = 0
            mock_run_git.return_value = res

            dialog._on_refresh_status()

            assert "Reachable" in dialog.table.item(0, 3).text()

        dialog.close()

    def test_remotes_dialog_auto_probe_and_async_refresh(self, repo_with_remote, db_conn):
        with patch("wrench.core.engine.probe_remotes_async") as mock_probe:
            dialog = RemotesDialog(repo_with_remote, db_conn=db_conn, auto_probe=True)
            assert mock_probe.called
            dialog.close()

    def test_remotes_dialog_async_refresh_clicked(self, repo_with_remote, db_conn):
        dialog = RemotesDialog(repo_with_remote, db_conn=db_conn)
        with patch("wrench.core.engine.probe_remotes_async") as mock_probe:
            dialog.refresh_btn.click()
            assert mock_probe.called
            assert dialog.refresh_btn.text() == "Probing..."
            assert not dialog.refresh_btn.isEnabled()

            # Emitting probe_finished resets button and refreshes
            dialog.probe_finished.emit()
            assert dialog.refresh_btn.text() == "Refresh Status"
            assert dialog.refresh_btn.isEnabled()

        dialog.close()
