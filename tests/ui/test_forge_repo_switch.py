"""UI regression tests for repository switching in PRListTab, IssueListTab, and MainWindow."""

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pygit2
import pytest
from PySide6.QtWidgets import QApplication

from tests.ui.test_forge_tabs import DummyAdapter
from wrench.storage import forge_accounts, repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow
from wrench.ui.tabs.issue_list_tab import IssueListTab
from wrench.ui.tabs.pr_list_tab import PRListTab
from wrench.ui.tabs.tab_bar import TabContainer


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn(tmp_path: Path):
    db_file = tmp_path / "test_repo_switch.db"
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


@pytest.fixture
def two_repos_fixture(tmp_path: Path, db_conn):
    # Repo A (linked to GitHub)
    repo_a = tmp_path / "repo_a"
    repo_a.mkdir()
    pygit2_repo_a = pygit2.init_repository(str(repo_a))
    sig = pygit2.Signature("Dev", "dev@example.com")
    tree_a = pygit2_repo_a.TreeBuilder().write()
    pygit2_repo_a.create_commit("HEAD", sig, sig, "Initial A", tree_a, [])
    pygit2_repo_a.remotes.create("origin", "https://github.com/alice/repo_a.git")

    repo_a_id = repo_registry.add_repo(db_conn, str(repo_a), "repo_a")

    mock_backend = MagicMock()
    mock_backend.get_secret.return_value = "token_abc"
    with patch("wrench.credentials.get_backend", return_value=mock_backend):
        acc_id = forge_accounts.add_account(
            db_conn,
            provider="github",
            instance_url="https://github.com",
            label="Work GitHub",
            username="alice",
            token="ghp_token",
        )
        forge_accounts.link_repo_to_account(
            db_conn,
            repo_id=repo_a_id,
            forge_account_id=acc_id,
            remote_name="origin",
            owner_slug="alice",
            repo_slug="repo_a",
        )

    # Repo B (unlinked)
    repo_b = tmp_path / "repo_b"
    repo_b.mkdir()
    pygit2_repo_b = pygit2.init_repository(str(repo_b))
    tree_b = pygit2_repo_b.TreeBuilder().write()
    pygit2_repo_b.create_commit("HEAD", sig, sig, "Initial B", tree_b, [])
    repo_registry.add_repo(db_conn, str(repo_b), "repo_b")

    return str(repo_a), str(repo_b), db_file_path(db_conn)


class TestForgeRepoSwitch:
    def test_pr_list_tab_repo_switching(self, two_repos_fixture, qtbot):
        path_a, path_b, db_path = two_repos_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background", side_effect=_sync_run_in_background
            ),
        ):
            tab = PRListTab(path_a)
            qtbot.addWidget(tab)
            tab.show()

            # Initially Repo A: PRs are displayed
            assert tab.table_view.isVisible()
            assert tab.empty_widget.isHidden()
            assert tab.table_model.rowCount() == 2
            assert tab.remote_combo.count() == 1

            # Switch to Repo B (unlinked)
            tab.set_active_repository(path_b)
            assert tab.repo_path == path_b
            assert tab.table_view.isHidden()
            assert tab.empty_widget.isVisible()
            assert "Not Linked" in tab.empty_title.text()
            assert tab.table_model.rowCount() == 0
            assert tab.remote_combo.count() == 0
            assert tab.refresh_btn.isEnabled() is False

            # Switch back to Repo A (linked)
            tab.set_active_repository(path_a)
            assert tab.repo_path == path_a
            assert tab.table_view.isVisible()
            assert tab.empty_widget.isHidden()
            assert tab.table_model.rowCount() == 2
            assert tab.remote_combo.count() == 1

    def test_issue_list_tab_repo_switching(self, two_repos_fixture, qtbot):
        path_a, path_b, db_path = two_repos_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.issue_list_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
        ):
            tab = IssueListTab(path_a)
            qtbot.addWidget(tab)
            tab.show()

            # Initially Repo A: Issues are displayed
            assert tab.table_view.isVisible()
            assert tab.empty_widget.isHidden()
            assert tab.table_model.rowCount() == 2
            assert tab.remote_combo.count() == 1

            # Switch to Repo B (unlinked)
            tab.set_active_repository(path_b)
            assert tab.repo_path == path_b
            assert tab.table_view.isHidden()
            assert tab.empty_widget.isVisible()
            assert "Not Linked" in tab.empty_title.text()
            assert tab.table_model.rowCount() == 0
            assert tab.remote_combo.count() == 0
            assert tab.refresh_btn.isEnabled() is False

            # Switch back to Repo A (linked)
            tab.set_active_repository(path_a)
            assert tab.repo_path == path_a
            assert tab.table_view.isVisible()
            assert tab.empty_widget.isHidden()
            assert tab.table_model.rowCount() == 2
            assert tab.remote_combo.count() == 1

    def test_tab_container_metadata_update_and_lookup(self, two_repos_fixture, qtbot):
        path_a, path_b, db_path = two_repos_fixture
        container = TabContainer()
        qtbot.addWidget(container)

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background", side_effect=_sync_run_in_background
            ),
        ):
            pr_tab = PRListTab(path_a)
            idx = container.add_tab(
                widget=pr_tab,
                label="Pull Requests",
                tab_type="pr_list",
                repo_path=path_a,
            )

            # Initially tab found by path_a
            assert container.find_tab("pr_list", path_a) == idx
            assert container.find_tab("pr_list", path_b) is None

            # Update metadata to path_b
            container.update_tab_repo_path(idx, path_b)
            pr_tab.set_active_repository(path_b)

            # Now found by path_b
            assert container.find_tab("pr_list", path_b) == idx
            assert container.find_tab("pr_list", path_a) is None

    def test_main_window_repo_switch_updates_open_tabs(self, two_repos_fixture, qtbot):
        path_a, path_b, db_path = two_repos_fixture

        with (
            patch("wrench.storage.db.get_connection", side_effect=lambda: sqlite3.connect(db_path)),
            patch("wrench.forge.registry.get_adapter_class", return_value=DummyAdapter),
            patch(
                "wrench.ui.tabs.pr_list_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
            patch(
                "wrench.ui.tabs.issue_list_tab.run_in_background",
                side_effect=_sync_run_in_background,
            ),
            patch("wrench.watcher.inotify_watcher.RepoWatcher.start"),
        ):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            win = MainWindow(conn=conn)
            qtbot.addWidget(win)
            win.show()

            # Open Repo A
            win._on_repo_changed(path_a)

            # Open PR list tab and Issues list tab
            win._on_add_category_tab("pr_list")
            win._on_add_category_tab("issues_list")

            pr_idx = win.tab_container.find_tab("pr_list", path_a)
            issues_idx = win.tab_container.find_tab("issues_list", path_a)
            assert pr_idx is not None
            assert issues_idx is not None

            pr_tab = win.tab_container.widget(pr_idx)
            issues_tab = win.tab_container.widget(issues_idx)

            assert pr_tab.repo_path == path_a
            assert pr_tab.table_model.rowCount() == 2
            assert issues_tab.repo_path == path_a
            assert issues_tab.table_model.rowCount() == 2

            # Now switch to Repo B in MainWindow
            win._on_repo_changed(path_b)

            # Check that both tabs were updated to path_b
            assert pr_tab.repo_path == path_b
            assert pr_tab.table_model.rowCount() == 0
            assert not pr_tab.empty_widget.isHidden()
            assert pr_tab.table_view.isHidden()

            assert issues_tab.repo_path == path_b
            assert issues_tab.table_model.rowCount() == 0
            assert not issues_tab.empty_widget.isHidden()
            assert issues_tab.table_view.isHidden()

            # Check that TabContainer metadata was updated to path_b
            assert win.tab_container.find_tab("pr_list", path_b) == pr_idx
            assert win.tab_container.find_tab("pr_list", path_a) is None
            assert win.tab_container.find_tab("issues_list", path_b) == issues_idx
            assert win.tab_container.find_tab("issues_list", path_a) is None

            win.close()
