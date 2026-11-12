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
            try:
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
            finally:
                win.close()
                conn.close()

    def test_repo_switch_cleans_widgets_and_blocks_duplicate_repo_open(
        self, two_repos_fixture, qtbot
    ):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget

        from wrench.core import engine
        from wrench.storage import repo_registry
        from wrench.ui.commit_graph.detail_panel import CommitDetailPanel

        path_a, path_b, db_path = two_repos_fixture
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        repo_registry.add_repo(conn, path_a, "repo-a")
        repo_registry.add_repo(conn, path_b, "repo-b")

        with patch("wrench.watcher.inotify_watcher.RepoWatcher.start"):
            win = MainWindow(conn=conn)
            try:
                qtbot.addWidget(win)
                emitted_paths: list[str] = []
                win.changes_tab.repo_changed.connect(emitted_paths.append)

                with patch.object(engine, "open_repo", wraps=engine.open_repo) as spy_open:
                    win.changes_tab.load_repos(select_path=path_b, auto_open=True)

                assert emitted_paths == [path_b]
                assert spy_open.call_count == 1
                assert win._current_repo is win.changes_tab._repo

                # Populate a CommitDetailPanel with a cellWidget and ensure clear schedules deletion
                panel = CommitDetailPanel()
                panel.files_table.setRowCount(1)
                cell_w = QWidget(panel.files_table)
                panel.files_table.setCellWidget(0, 2, cell_w)
                destroyed = []
                cell_w.destroyed.connect(lambda: destroyed.append(True))

                panel._clear_files_table()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                assert panel.files_table.rowCount() == 0
                assert destroyed == [True]
                panel.close()
            finally:
                win.close()
                conn.close()

    def test_tab_close_disposes_forge_adapter_and_widget_even_when_hidden(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget

        container = TabContainer()
        changes_stub = QWidget()
        container.add_tab(
            changes_stub,
            "Changes",
            closable=False,
            is_pinned=True,
            tab_type="changes",
        )

        pr_tab = PRListTab("/tmp/fake_repo")
        dummy = DummyAdapter(MagicMock(instance_url="https://github.com", token="tok"))
        assert dummy._client.is_closed is False
        pr_tab._active_adapter = dummy
        pr_destroyed: list[bool] = []
        pr_tab.destroyed.connect(lambda: pr_destroyed.append(True))

        idx = container.add_tab(pr_tab, "PRs", closable=True, tab_type="pr_list")
        # Keep singleton Changes tab active so pr_tab stays hidden inside QStackedWidget
        container.set_current_index(0)

        container.remove_tab(idx)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

        assert dummy._client.is_closed is True
        assert pr_destroyed == [True]
        assert container.count() == 1
        container.close()

    def test_diff_widget_and_link_dialog_and_watcher_teardown(self, two_repos_fixture, qtbot):
        from PySide6.QtCore import QCoreApplication, QEvent

        from wrench.core import engine
        from wrench.ui.dialogs.link_dialog import LinkRepoDialog
        from wrench.ui.diff_view.diff_widget import DiffWidget

        path_a, path_b, db_path = two_repos_fixture
        repo_a = engine.open_repo(path_a, configure_credentials=False)
        repo_b = engine.open_repo(path_b, configure_credentials=False)

        diff_w = DiffWidget()
        diff_w.set_repo(repo_a)
        diff_w._current_path = "secret.txt"
        diff_w._diff = MagicMock()
        diff_w.editor.setPlainText("sensitive diff from repo A")
        diff_w.set_repo(repo_b)
        assert diff_w._current_path is None
        assert diff_w._diff is None
        assert diff_w.editor.toPlainText() == ""

        # Calling set_repo with the same repo instance also resets stale path/read_only state
        diff_w._current_path = "same_repo_stale.txt"
        diff_w._diff = MagicMock()
        diff_w._read_only = True
        diff_w.set_repo(repo_b)
        assert diff_w._current_path is None
        assert diff_w._diff is None
        assert diff_w._read_only is False
        diff_w.close()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        dlg = LinkRepoDialog(path_a, conn=conn)
        old_combos = list(dlg._combos.values())
        assert len(old_combos) >= 1
        combo_destroyed: list[bool] = []
        old_combos[0].destroyed.connect(lambda: combo_destroyed.append(True))
        dlg._populate_table()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert combo_destroyed == [True]
        dlg.close()

        with patch("wrench.watcher.inotify_watcher.RepoWatcher.start"):
            win = MainWindow(conn=conn)
            try:
                qtbot.addWidget(win)
                win._on_repo_changed(path_a)
                first_watcher = win._watcher
                assert first_watcher is not None
                watcher_destroyed: list[bool] = []
                first_watcher.destroyed.connect(lambda: watcher_destroyed.append(True))

                win._on_repo_changed(path_b)
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                assert watcher_destroyed == [True]
            finally:
                win.close()
                conn.close()

    def test_delayed_heap_trim_runs_after_event_loop_and_cancels_on_close(
        self, two_repos_fixture, qtbot
    ):
        path_a, path_b, db_path = two_repos_fixture
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        with patch("wrench.watcher.inotify_watcher.RepoWatcher.start"):
            win = MainWindow(conn=conn)
            try:
                qtbot.addWidget(win)
                with patch.object(
                    win,
                    "_reclaim_heap_after_switch",
                    wraps=win._reclaim_heap_after_switch,
                ) as reclaim_spy:
                    win._on_repo_changed(path_a)
                    assert reclaim_spy.call_count == 1
                    assert win._heap_trim_timer.isSingleShot() is True
                    assert win._heap_trim_timer.interval() == 150
                    assert win._heap_trim_timer.isActive() is True

                    qtbot.waitUntil(lambda: reclaim_spy.call_count >= 2, timeout=1500)
                    assert reclaim_spy.call_count == 2
                    assert win._heap_trim_timer.isActive() is False

                    # Closing before the delayed timer fires cancels it cleanly
                    win._on_repo_changed(path_b)
                    assert reclaim_spy.call_count == 3
                    assert win._heap_trim_timer.isActive() is True
                    win.close()
                    assert win._heap_trim_timer.isActive() is False
                    qtbot.wait(220)
                    assert reclaim_spy.call_count == 3
            finally:
                win.close()
                conn.close()

    def test_repo_switch_resets_selected_file_and_eliminates_duplicate_diff_calls(
        self, two_repos_fixture, qtbot
    ):
        from wrench.core import engine

        path_a, path_b, db_path = two_repos_fixture
        repo_b_git = pygit2.Repository(path_b)
        sig = pygit2.Signature("Dev", "dev@example.com")
        (Path(path_b) / ".gitattributes").write_text("*.py diff=custom\n", encoding="utf-8")
        (Path(path_b) / "a_first.py").write_text("x = 1\n", encoding="utf-8")
        (Path(path_b) / "z_selected.py").write_text("y = 1\n", encoding="utf-8")
        repo_b_git.index.add(".gitattributes")
        repo_b_git.index.add("a_first.py")
        repo_b_git.index.add("z_selected.py")
        repo_b_git.index.write()
        tree_oid = repo_b_git.index.write_tree()
        repo_b_git.create_commit(
            "HEAD",
            sig,
            sig,
            "Add diff-filtered files",
            tree_oid,
            [repo_b_git.head.target],
        )

        # Uncommitted file unique to Repo A
        (Path(path_a) / "only_in_a.py").write_text("print('a')\n", encoding="utf-8")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        with patch("wrench.watcher.inotify_watcher.RepoWatcher.start"):
            win = MainWindow(conn=conn)
            try:
                qtbot.addWidget(win)
                diff_calls: list[tuple[str, str]] = []
                orig_get_diff = engine.get_diff

                def spy_get_diff(repo, path, *args, **kwargs):
                    diff_calls.append((str(repo.path), str(path)))
                    return orig_get_diff(repo, path, *args, **kwargs)

                with patch.object(engine, "get_diff", side_effect=spy_get_diff):
                    win.changes_tab.load_repos(select_path=path_a, auto_open=True)
                    assert win.changes_tab._selected_file == "only_in_a.py"
                    assert win.changes_tab.diff_view._current_path == "only_in_a.py"

                    # Switch to clean Repo B (which has .gitattributes diff=custom)
                    diff_calls.clear()
                    win.changes_tab._open_repo_by_path(path_b)
                    assert win.changes_tab._selected_file is None
                    assert win.changes_tab.diff_view._current_path is None
                    assert (path_b, "only_in_a.py") not in diff_calls

                    # Poison persisted state with stale cross-repo filename and switch directly
                    win._repos_state[path_b] = {
                        "summary": "",
                        "description": "",
                        "is_amend": False,
                        "checked_files": [],
                        "selected_file": "only_in_a.py",
                    }
                    diff_calls.clear()
                    win._on_repo_changed(path_b)
                    assert (path_b, "only_in_a.py") not in diff_calls

                    # Modify 2 tracked files in Repo B, select z_selected.py, switch away & back
                    (Path(path_b) / "a_first.py").write_text("x = 2\n", encoding="utf-8")
                    (Path(path_b) / "z_selected.py").write_text("y = 2\n", encoding="utf-8")
                    win.changes_tab.refresh()
                    win.changes_tab._show_file_diff("z_selected.py")
                    assert win.changes_tab._selected_file == "z_selected.py"

                    win.changes_tab._open_repo_by_path(path_a)
                    diff_calls.clear()
                    win.changes_tab._open_repo_by_path(path_b)
                    z_calls = [c for c in diff_calls if c == (path_b, "z_selected.py")]
                    assert len(z_calls) == 1
            finally:
                win.close()
                conn.close()
