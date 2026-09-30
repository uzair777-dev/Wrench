"""Tests for Phase 4.1 open-time forge link resolution."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication

from wrench.storage import forge_accounts, repo_registry, settings
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
    db_file = tmp_path / "test_link_res.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


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


def _create_git_repo(path: Path, remote_url: str, remote_name: str = "origin"):
    path.mkdir(parents=True, exist_ok=True)
    repo = pygit2.init_repository(str(path))
    sig = pygit2.Signature("Dev", "dev@example.com")
    tree = repo.TreeBuilder().write()
    repo.create_commit("HEAD", sig, sig, "Initial", tree, [])
    repo.remotes.create(remote_name, remote_url)
    return repo


class TestMaybeOfferForgeLink:
    """Tests for _maybe_offer_forge_link on MainWindow."""

    def test_single_candidate_auto_links_silently(self, db_conn, tmp_path):
        """With exactly one matching account, auto-link and show status bar note."""
        acc_id = _add_dummy_account(db_conn, "Personal GitHub", "alice")
        repo_dir = tmp_path / "single_account_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "single_account_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))

        # Banner should NOT be visible
        assert win.changes_tab.forge_link_banner.isHidden()

        # Remote should be auto-linked
        link = forge_accounts.get_link_for_remote(db_conn, repo_id, "origin")
        assert link is not None
        assert link.forge_account_id == acc_id
        assert link.owner_slug == "myorg"
        assert link.repo_slug == "myrepo"
        win.close()

    def test_multiple_candidates_shows_banner(self, db_conn, tmp_path):
        """With >=2 matching accounts, shows non-modal banner in ChangesTab."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "multi_account_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "multi_account_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))

        # Banner should BE shown
        assert not win.changes_tab.forge_link_banner.isHidden()
        assert "myorg/myrepo" in win.changes_tab.forge_link_label.text()

        # No link should be automatically created yet
        link = forge_accounts.get_link_for_remote(db_conn, repo_id, "origin")
        assert link is None
        win.close()

    def test_banner_dismiss_button_hides_and_persists(self, db_conn, tmp_path):
        """Clicking 'Dismiss' hides the banner and persists the decline marker."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "dismiss_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "dismiss_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))
        assert not win.changes_tab.forge_link_banner.isHidden()

        # Click Dismiss
        win.changes_tab.forge_link_dismiss_btn.click()
        assert win.changes_tab.forge_link_banner.isHidden()

        # Check persisted setting
        declined_raw = settings.get_setting(db_conn, "forge.link_declined")
        assert declined_raw is not None
        declined_list = json.loads(declined_raw)
        assert f"{repo_id}:origin" in declined_list
        win.close()

    def test_declined_pair_never_reappears(self, db_conn, tmp_path):
        """After dismissing, the banner never reappears for that (repo, remote)."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "never_reappear_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "never_reappear_repo")

        # Pre-seed decline marker
        settings.set_setting(db_conn, "forge.link_declined", json.dumps([f"{repo_id}:origin"]))

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))

        assert win.changes_tab.forge_link_banner.isHidden()
        win.close()

    def test_already_linked_skips_silently(self, db_conn, tmp_path):
        """A remote that already has a link is skipped silently."""
        acc1_id = _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "already_linked_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "already_linked_repo")

        forge_accounts.link_repo_to_account(db_conn, repo_id, acc1_id, "origin", "myorg", "myrepo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))

        assert win.changes_tab.forge_link_banner.isHidden()
        win.close()

    def test_non_https_remote_skipped(self, db_conn, tmp_path):
        """SSH remotes are skipped entirely (HTTPS-only matching rule)."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "ssh_repo"
        _create_git_repo(repo_dir, "git@github.com:myorg/myrepo.git")
        repo_id = repo_registry.add_repo(db_conn, str(repo_dir), "ssh_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))

        assert win.changes_tab.forge_link_banner.isHidden()
        assert forge_accounts.get_link_for_remote(db_conn, repo_id, "origin") is None
        win.close()

    def test_banner_link_button_opens_link_dialog(self, db_conn, tmp_path):
        """Clicking 'Link account…' opens the LinkRepoDialog."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "dialog_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_registry.add_repo(db_conn, str(repo_dir), "dialog_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))
        assert not win.changes_tab.forge_link_banner.isHidden()

        with patch("wrench.ui.dialogs.link_dialog.LinkRepoDialog.exec") as mock_exec:
            win.changes_tab.forge_link_btn.click()
            assert mock_exec.called
            assert win.changes_tab.forge_link_banner.isHidden()
        win.close()

    def test_decline_marker_persists_across_calls(self, db_conn, tmp_path):
        """Decline markers persist in app_settings across multiple invocations."""
        _add_dummy_account(db_conn, "Work GitHub", "alice_work")
        _add_dummy_account(db_conn, "Personal GitHub", "alice_personal")
        repo_dir = tmp_path / "persist_repo"
        _create_git_repo(repo_dir, "https://github.com/myorg/myrepo.git")
        repo_registry.add_repo(db_conn, str(repo_dir), "persist_repo")

        win = MainWindow(conn=db_conn)
        win._maybe_offer_forge_link(str(repo_dir))
        assert not win.changes_tab.forge_link_banner.isHidden()

        win.changes_tab.forge_link_dismiss_btn.click()
        assert win.changes_tab.forge_link_banner.isHidden()

        # Second call to _maybe_offer_forge_link on same repo
        win._maybe_offer_forge_link(str(repo_dir))
        assert win.changes_tab.forge_link_banner.isHidden()
        win.close()
