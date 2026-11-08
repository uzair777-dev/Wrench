import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from wrench.core.exceptions import GitNetworkTransferError
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


def test_route_remote_error_network_dialog(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    exc = GitNetworkTransferError(
        ["git", "push"],
        1,
        "error: RPC failed; HTTP 408",
        kind="timeout_408",
        status_code=408,
    )

    with patch("wrench.ui.main_window.GitNetworkRecoveryDialog") as mock_dlg_cls:
        mock_dlg = MagicMock()
        mock_dlg_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 0  # Rejected/Cancelled

        win._route_remote_error(exc, "origin", branch="main", op="push")
        mock_dlg_cls.assert_called_once()
        mock_dlg.exec.assert_called_once()
    win.close()


def test_retry_push_with_config_invokes_background(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    fake_repo.path = "/fake/repo"
    win._current_repo = fake_repo

    with patch("wrench.ui.main_window.run_in_background") as mock_run:
        win._retry_push_with_config("origin", "main", {"http.postBuffer": "524288000"})
        mock_run.assert_called_once()
        args = mock_run.call_args[0]
        assert args[1] == fake_repo
        assert args[2] == "origin"
        assert args[3] == "main"
        assert mock_run.call_args[1]["extra_config"] == {"http.postBuffer": "524288000"}
    win.close()


def test_start_incremental_push_invokes_background(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    fake_repo.path = "/fake/repo"
    win._current_repo = fake_repo

    with patch("wrench.ui.main_window.run_in_background") as mock_run:
        win._start_incremental_push("origin", "main")
        mock_run.assert_called_once()
        args = mock_run.call_args[0]
        assert args[1] == fake_repo
        assert args[2] == "origin"
        assert args[3] == "main"
        assert mock_run.call_args[1]["chunk_size"] == 20
    win.close()


def test_prompt_save_network_config(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    fake_repo.path = "/fake/repo"
    win._current_repo = fake_repo

    with (
        patch("wrench.ui.main_window.QMessageBox") as mock_box_cls,
        patch("wrench.core.engine.set_git_config") as mock_set,
    ):
        mock_box = MagicMock()
        mock_box_cls.return_value = mock_box
        repo_btn = MagicMock()
        mock_box.addButton.side_effect = [repo_btn, MagicMock(), MagicMock()]
        mock_box.clickedButton.return_value = repo_btn

        win._prompt_save_network_config({"http.postBuffer": "524288000"})
        mock_set.assert_called_once_with(fake_repo, "http.postBuffer", "524288000", scope="local")
    win.close()


def test_on_push_remote_large_blobs_cancel(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    win._current_repo = fake_repo
    win._get_default_remote = MagicMock(return_value="origin")
    win._get_current_branch = MagicMock(return_value="main")

    with (
        patch("wrench.core.engine.scan_unpushed_large_blobs", return_value=[("large.bin", 120.0)]),
        patch("wrench.ui.main_window.PrePushLargeFilesDialog") as mock_dlg_cls,
        patch("wrench.ui.main_window.run_in_background") as mock_run,
    ):
        mock_dlg = MagicMock()
        mock_dlg_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 0  # Rejected / Cancelled

        win._on_push_remote()
        mock_dlg_cls.assert_called_once()
        mock_run.assert_not_called()
    win.close()


def test_on_push_remote_large_blobs_extreme_compression(db_conn, qapp):
    win = MainWindow(conn=db_conn)
    fake_repo = MagicMock()
    win._current_repo = fake_repo
    win._get_default_remote = MagicMock(return_value="origin")
    win._get_current_branch = MagicMock(return_value="main")

    with (
        patch("wrench.core.engine.scan_unpushed_large_blobs", return_value=[("large.bin", 120.0)]),
        patch("wrench.ui.main_window.PrePushLargeFilesDialog") as mock_dlg_cls,
        patch("wrench.ui.main_window.run_in_background") as mock_run,
        patch("wrench.ui.main_window.BusyOperationDialog"),
    ):
        mock_dlg = MagicMock()
        mock_dlg_cls.return_value = mock_dlg
        mock_dlg.exec.return_value = 1  # Accepted
        mock_dlg.action = "extreme_compression"

        win._on_push_remote()
        mock_dlg_cls.assert_called_once()
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["extra_config"]["core.compression"] == "9"
        assert call_kwargs["extra_config"]["pack.window"] == "10"
    win.close()
