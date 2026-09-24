"""UI tests for Accounts and Link dialogs (FR-5.6, FR-8.1 - FR-8.7)."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from wrench.core.engine import RepoHandle
from wrench.forge.exceptions import ForgeAuthenticationError
from wrench.forge.oauth.github_device_flow import DeviceFlowCodes
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.dialogs.accounts_dialog import (
    AccountsDialog,
    AddAccountDialog,
    EditAccountDialog,
)
from wrench.ui.dialogs.link_dialog import LinkRepoDialog
from wrench.ui.forge_panel.info_popover import InfoButton


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

    def test_link_repo_auto_aligns_identity(self, tmp_path: Path, db_conn):
        db_path = db_file_path(db_conn)
        repo_path = tmp_path / "align_repo"
        repo_path.mkdir()
        pygit2_repo = pygit2.init_repository(str(repo_path))
        sig = pygit2.Signature("Old Name", "old@example.com")
        tree = pygit2_repo.TreeBuilder().write()
        pygit2_repo.create_commit("HEAD", sig, sig, "Initial", tree, [])
        pygit2_repo.remotes.create("origin", "https://github.com/alice/coolproject.git")

        repo_registry.add_repo(db_conn, str(repo_path), "align_repo")

        mock_backend = MagicMock()
        mock_backend.get_secret.return_value = "ghp_mock_token"
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub Acc",
                username="alice",
                token="tok_gh",
            )

        with (
            patch(
                "wrench.storage.db.get_connection",
                side_effect=lambda: sqlite3.connect(db_path),
            ),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch(
                "wrench.ui.dialogs.link_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
            patch(
                "wrench.forge.adapters.github.GitHubAdapter.get_primary_email",
                return_value="alice@example.com",
            ),
        ):
            dlg = LinkRepoDialog(str(repo_path))
            dlg._auto_match_remotes()
            dlg._save_links()

            # Verify local identity was aligned
            from wrench.core.identity import check_identity

            name, email = check_identity(str(repo_path))
            assert name == "alice"
            assert email == "alice@example.com"


class TestAssistedFlowUI:
    """UI tests for AddAccountDialog assisted flow, chooser, and tooltips."""

    def test_add_dialog_shows_method_chooser_first(self):
        dlg = AddAccountDialog()
        assert dlg._stack.currentIndex() == 0
        buttons = dlg._chooser_page.findChildren(QPushButton)
        btn_texts = [b.text() for b in buttons]
        assert any("Assisted" in t for t in btn_texts)
        assert any("Manual" in t for t in btn_texts)

    def test_assisted_button_goes_to_device_flow_page(self):
        dlg = AddAccountDialog()
        dlg.assisted_btn.click()
        assert dlg._stack.currentIndex() == 1

    def test_manual_button_goes_to_manual_form_page(self):
        dlg = AddAccountDialog()
        dlg.manual_btn.click()
        assert dlg._stack.currentIndex() == 2

    def test_back_button_returns_to_chooser(self):
        dlg = AddAccountDialog()
        # From assisted page
        dlg.assisted_btn.click()
        assert dlg._stack.currentIndex() == 1
        dlg.assisted_back_btn.click()
        assert dlg._stack.currentIndex() == 0

        # From manual page
        dlg.manual_btn.click()
        assert dlg._stack.currentIndex() == 2
        dlg.manual_back_btn.click()
        assert dlg._stack.currentIndex() == 0

    def test_enterprise_radio_reveals_instance_url(self):
        dlg = AddAccountDialog()
        dlg.show()
        dlg.assisted_btn.click()
        dlg.enterprise_radio.setChecked(True)
        assert not dlg.assisted_url_edit.isHidden()
        assert dlg.assisted_url_container.isVisible()

    def test_personal_radio_hides_instance_url(self):
        dlg = AddAccountDialog()
        dlg.show()
        dlg.assisted_btn.click()
        dlg.enterprise_radio.setChecked(True)
        assert not dlg.assisted_url_edit.isHidden()
        dlg.personal_radio.setChecked(True)
        assert dlg.assisted_url_edit.isHidden()
        assert not dlg.assisted_url_container.isVisible()

    def test_scope_chooser_defaults_to_full(self):
        dlg = AddAccountDialog()
        dlg.assisted_btn.click()
        assert dlg.full_scope_radio.isChecked()
        assert not dlg.public_scope_radio.isChecked()

    def test_manual_form_has_info_buttons(self):
        dlg = AddAccountDialog()
        dlg.manual_btn.click()
        info_buttons = dlg._manual_page.findChildren(InfoButton)
        assert len(info_buttons) >= 5

    def test_info_button_toggles_popover(self):
        dlg = AddAccountDialog()
        dlg.show()
        dlg.manual_btn.click()
        info_buttons = dlg._manual_page.findChildren(InfoButton)
        assert len(info_buttons) > 0
        btn = info_buttons[0]

        # First click opens popover
        btn.click()
        assert btn._popover is not None
        assert btn._popover.isVisible()

        # Second click closes popover
        btn.click()
        assert not btn._popover.isVisible()

    def test_tooltip_updates_on_provider_change(self):
        dlg = AddAccountDialog()
        dlg.manual_btn.click()
        idx = dlg.provider_combo.findData("gitlab")
        assert idx >= 0
        dlg.provider_combo.setCurrentIndex(idx)
        assert "gitlab" in dlg.token_info_btn._tooltip_html.lower()

    def test_assisted_flow_connect_and_success(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()
        mock_codes = DeviceFlowCodes(
            device_code="dc_test",
            user_code="TEST-1234",
            verification_uri="https://github.com/login/device",
            interval=1,
            expires_in=60,
        )

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch(
                "wrench.ui.dialogs.accounts_dialog.request_device_code",
                return_value=mock_codes,
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.poll_for_token",
                return_value="gho_oauth_token",
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog._validate_credentials_probe",
                return_value={"ok": True, "inferred_user": "octocat"},
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            dlg = AddAccountDialog()
            dlg.assisted_btn.click()
            dlg.assisted_connect_btn.click()

            records = forge_accounts.list_accounts(db_conn)
            assert len(records) == 1
            assert records[0].provider == "github"
            assert records[0].username == "octocat"
            assert "GitHub" in records[0].label

    def test_assisted_flow_error_denied(self):
        with (
            patch(
                "wrench.ui.dialogs.accounts_dialog.request_device_code",
                side_effect=ForgeAuthenticationError("access_denied"),
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            dlg = AddAccountDialog()
            dlg.show()
            dlg.assisted_btn.click()
            dlg.assisted_connect_btn.click()

            assert "denied" in dlg.waiting_status_label.text().lower()
            assert dlg.assisted_try_again_btn.isVisible()
            assert dlg.assisted_manual_fallback_btn.isVisible()

    def test_assisted_flow_requests_workflow_scope(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()
        mock_codes = DeviceFlowCodes(
            device_code="dc_test",
            user_code="TEST-1234",
            verification_uri="https://github.com/login/device",
            interval=1,
            expires_in=60,
        )

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch(
                "wrench.ui.dialogs.accounts_dialog.request_device_code",
                return_value=mock_codes,
            ) as mock_req,
            patch(
                "wrench.ui.dialogs.accounts_dialog.poll_for_token",
                return_value="gho_oauth_token",
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog._validate_credentials_probe",
                return_value={"ok": True, "inferred_user": "octocat"},
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            dlg = AddAccountDialog()
            dlg.assisted_btn.click()
            dlg.assisted_connect_btn.click()

            mock_req.assert_called_once()
            _, kwargs = mock_req.call_args
            assert "workflow" in kwargs["scope"]
            assert "repo" in kwargs["scope"]

    def test_assisted_flow_reauth_updates_existing_account(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub (octocat)",
                username="octocat",
                token="old_token",
            )

        mock_codes = DeviceFlowCodes(
            device_code="dc_test",
            user_code="TEST-1234",
            verification_uri="https://github.com/login/device",
            interval=1,
            expires_in=60,
        )

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch(
                "wrench.ui.dialogs.accounts_dialog.request_device_code",
                return_value=mock_codes,
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.poll_for_token",
                return_value="new_token_with_workflow",
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog._validate_credentials_probe",
                return_value={"ok": True, "inferred_user": "octocat"},
            ),
            patch(
                "wrench.ui.dialogs.accounts_dialog.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            dlg = AddAccountDialog(initial_page=1)
            dlg.assisted_connect_btn.click()

            # Verify no duplicate account was inserted
            records = forge_accounts.list_accounts(db_conn)
            assert len(records) == 1
            assert records[0].id == acc_id
            # Verify secret store was updated with new token
            mock_backend.store_secret.assert_called_with(
                f"wrench:forge:{acc_id}",
                "new_token_with_workflow",
                label=f"Wrench: {records[0].label}",
            )

    def test_reauth_button_presence(self, db_conn):
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub (octocat)",
                username="octocat",
                token="old_token",
            )
        records = forge_accounts.list_accounts(db_conn)

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
        ):
            dlg = AccountsDialog()
            assert hasattr(dlg, "reauth_btn")

            edit_dlg = EditAccountDialog(records[0])
            assert hasattr(edit_dlg, "reauth_btn")

    def test_reauth_account_flow_no_attribute_error(self, db_conn):
        """Verify _reauth_account and _reauth_github instantiate
        AddAccountDialog without AttributeError.
        """
        db_path = db_file_path(db_conn)
        mock_backend = MagicMock()

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub (octocat)",
                username="octocat",
                token="old_token",
            )
        records = forge_accounts.list_accounts(db_conn)

        # Test AddAccountDialog directly for cloud_radio alias
        add_dlg = AddAccountDialog(initial_page=1, reauth_account_id=acc_id)
        assert hasattr(add_dlg, "cloud_radio")
        assert hasattr(add_dlg, "personal_radio")
        assert add_dlg.cloud_radio is add_dlg.personal_radio
        assert add_dlg.windowTitle() == "Re-authenticate GitHub Account"

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.credentials.get_backend", return_value=mock_backend),
            patch.object(AddAccountDialog, "exec", return_value=1),
        ):
            # Test AccountsDialog._reauth_account
            acc_dlg = AccountsDialog()
            acc_dlg.table.selectRow(0)
            acc_dlg._reauth_account()

            # Test EditAccountDialog._reauth_github
            edit_dlg = EditAccountDialog(records[0])
            edit_dlg._reauth_github()


class TestAdvancedScopes:
    """Test the advanced OAuth scope configuration UI."""

    def test_advanced_scopes_exist_on_assisted_page(self, db_conn):
        """Verify the advanced scope widgets are present."""
        dlg = AddAccountDialog(initial_page=1)
        assert hasattr(dlg, "advanced_scopes_btn"), "Missing advanced_scopes_btn toggle"
        assert hasattr(dlg, "scope_workflow_cb"), "Missing workflow checkbox"
        assert hasattr(dlg, "scope_user_email_cb"), "Missing user:email checkbox"
        assert hasattr(dlg, "scope_read_org_cb"), "Missing read:org checkbox"

    def test_full_scope_preset_checks_all(self, db_conn):
        """Full Access preset should check all optional scopes."""
        dlg = AddAccountDialog(initial_page=1)
        assert dlg.full_scope_radio.isChecked()
        assert dlg.scope_workflow_cb.isChecked()
        assert dlg.scope_user_email_cb.isChecked()
        assert dlg.scope_read_org_cb.isChecked()

    def test_public_scope_preset_unchecks_workflow_and_org(self, db_conn):
        """Public Only preset should uncheck workflow and read:org."""
        dlg = AddAccountDialog(initial_page=1)
        dlg.public_scope_radio.setChecked(True)
        assert not dlg.scope_workflow_cb.isChecked()
        assert not dlg.scope_read_org_cb.isChecked()
        # user:email should still be checked
        assert dlg.scope_user_email_cb.isChecked()

    def test_get_selected_scopes_public(self, db_conn):
        """Public scope string should contain public_repo and user:email."""
        dlg = AddAccountDialog(initial_page=1)
        dlg.public_scope_radio.setChecked(True)
        scopes = dlg._get_selected_scopes()
        assert "public_repo" in scopes
        assert "user:email" in scopes
        assert "workflow" not in scopes
        assert "read:org" not in scopes

    def test_get_selected_scopes_full(self, db_conn):
        """Full scope string should contain repo, workflow, user:email, read:org."""
        dlg = AddAccountDialog(initial_page=1)
        scopes = dlg._get_selected_scopes()
        assert "repo" in scopes
        assert "workflow" in scopes
        assert "user:email" in scopes
        assert "read:org" in scopes

    def test_custom_scope_override(self, db_conn):
        """User can manually toggle workflow on even with Public preset."""
        dlg = AddAccountDialog(initial_page=1)
        dlg.public_scope_radio.setChecked(True)
        dlg.scope_workflow_cb.setChecked(True)
        scopes = dlg._get_selected_scopes()
        assert "workflow" in scopes
        assert "public_repo" in scopes
