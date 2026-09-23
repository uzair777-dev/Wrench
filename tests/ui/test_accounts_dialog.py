"""UI tests for Accounts and Link dialogs (FR-5.6, FR-8.1 - FR-8.7)."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from wrench.core.engine import RepoHandle
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.dialogs.accounts_dialog import (
    AccountsDialog,
    AddAccountDialog,
    EditAccountDialog,
)
from wrench.ui.dialogs.link_dialog import LinkRepoDialog


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn(tmp_path: Path):
    db_file = tmp_path / "test_acc.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


def db_file_path(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA database_list")
    return cur.fetchone()[2]


def _sync_run_in_background(fn, *args, on_finished=None, on_failed=None, **kwargs):
    try:
        res = fn(*args)
        if on_finished:
            on_finished(res)
    except Exception as exc:
        if on_failed:
            on_failed(exc)


class TestAccountsDialog:
    def test_accounts_dialog_lists_and_deletes(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="My GitHub",
                username="alice",
                token="token123",
            )

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
        ):
            dlg = AccountsDialog()
            assert dlg.table.rowCount() == 1
            assert dlg.table.item(0, 0).text() == "Github"
            assert dlg.table.item(0, 3).text() == "My GitHub"

            # Test delete account
            dlg.table.selectRow(0)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
                dlg._delete_account()

            assert dlg.table.rowCount() == 0
            records = forge_accounts.list_accounts(db_conn)
            assert len(records) == 0
            mock_backend.delete_secret.assert_called_once_with(f"wrench:forge:{acc_id}")

    def test_add_account_dialog_success(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch(
                "wrench.ui.dialogs.accounts_dialog._validate_credentials_probe",
                return_value={"ok": True, "inferred_user": "bob"},
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):

            dlg = AddAccountDialog()
            dlg.url_edit.setText("https://github.com")
            dlg.label_edit.setText("Bob Account")
            dlg.token_edit.setText("ghp_validtoken")
            dlg.insecure_cb.setChecked(False)

            dlg._validate_and_save()

            records = forge_accounts.list_accounts(db_conn)
            assert len(records) == 1
            assert records[0].label == "Bob Account"
            assert records[0].username == "bob"

    def test_add_account_dialog_failure(self, db_conn):
        db_path = db_file_path(db_conn)

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch(
                "wrench.ui.dialogs.accounts_dialog._validate_credentials_probe",
                side_effect=RuntimeError("Invalid Token"),
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):

            dlg = AddAccountDialog()
            dlg.token_edit.setText("invalid_token")
            dlg._validate_and_save()

            assert "Validation failed: Invalid Token" in dlg.status_label.text()
            assert dlg.save_btn.isEnabled()

    def test_edit_account_dialog(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="gitlab",
                instance_url="https://gitlab.com",
                label="Old Label",
                username="charlie",
                token="glpat-token",
            )
        record = forge_accounts.list_accounts(db_conn)[0]

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
        ):

            dlg = EditAccountDialog(record)
            dlg.label_edit.setText("Updated GitLab")
            dlg.username_edit.setText("charlie_new")
            dlg._save_changes()

            updated = forge_accounts.get_account_full(db_conn, acc_id)
            assert updated.label == "Updated GitLab"
            assert updated.username == "charlie_new"


class TestLinkRepoDialog:
    def test_link_repo_auto_match_and_save(self, tmp_path: Path, db_conn):
        db_path = db_file_path(db_conn)
        repo_path = tmp_path / "link_repo"
        repo_path.mkdir()
        pygit2_repo = pygit2.init_repository(str(repo_path))

        sig = pygit2.Signature("Dev", "dev@example.com")
        tree = pygit2_repo.TreeBuilder().write()
        pygit2_repo.create_commit("HEAD", sig, sig, "Initial", tree, [])

        # Configure two remotes: GitHub and GitLab
        pygit2_repo.remotes.create("origin", "https://github.com/alice/coolproject.git")
        pygit2_repo.remotes.create("gitlab", "git@gitlab.com:alice/coolproject.git")

        repo_id = repo_registry.add_repo(db_conn, str(repo_path), "link_repo")

        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_gh = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub Acc",
                username="alice",
                token="tok_gh",
            )
            acc_gl = forge_accounts.add_account(
                db_conn,
                provider="gitlab",
                instance_url="https://gitlab.com",
                label="GitLab Acc",
                username="alice",
                token="tok_gl",
            )

        with patch(
            "wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)
        ):
            dlg = LinkRepoDialog(str(repo_path))
            assert dlg.table.rowCount() == 2

            # Run auto-match by host
            dlg._auto_match_remotes()

            row_map = {dlg._row_data[r][0]: r for r in dlg._row_data}
            assert dlg._combos[row_map["origin"]].currentData() == acc_gh
            assert dlg._combos[row_map["gitlab"]].currentData() == acc_gl

            # Save links
            dlg._save_links()

            # Verify links in DB
            links = forge_accounts.list_links_for_repo(db_conn, repo_id)
            assert len(links) == 2
            link_map = {lnk.remote_name: lnk for lnk in links}
            assert link_map["origin"].forge_account_id == acc_gh
            assert link_map["origin"].owner_slug == "alice"
            assert link_map["origin"].repo_slug == "coolproject"

            assert link_map["gitlab"].forge_account_id == acc_gl
            assert link_map["gitlab"].owner_slug == "alice"
            assert link_map["gitlab"].repo_slug == "coolproject"

            # Verify git config credential.useHttpPath was set to true
            handle = RepoHandle(pygit2_repo, str(repo_path))
            assert handle.pygit2_repo.config["credential.useHttpPath"] == "true"
