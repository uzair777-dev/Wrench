"""UI integration tests for sidebar, diff view, and main window."""

import sqlite3

import pytest

from wrench.storage import repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.diff_view.diff_widget import DiffView
from wrench.ui.main_window import MainWindow
from wrench.ui.sidebar.repo_list import RepoSidebar


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestRepoSidebar:
    def test_sidebar_displays_repos(self, db_conn, qapp):
        repo_registry.add_repo(db_conn, "/path/to/repo_a", "Repo A")
        repo_registry.add_repo(db_conn, "/path/to/repo_b", "Repo B")

        sidebar = RepoSidebar(db_conn)
        sidebar.refresh()

        assert sidebar.list_widget.count() == 2
        assert sidebar.list_widget.item(0).text() == "Repo A"
        assert sidebar.list_widget.item(1).text() == "Repo B"


class TestDiffView:
    def test_diff_view_shows_hunks(self, simple_repo, qapp):
        (simple_repo.path / "hello.txt").write_text("Hello, world!\nLine 2 added\n")
        diff_view = DiffView()
        diff_view.set_repo(simple_repo)
        diff_view.set_file("hello.txt", staged=False)

        assert diff_view.hunk_count() >= 1


class TestMainWindow:
    def test_main_window_initializes(self, db_conn, simple_repo, qapp):
        repo_registry.add_repo(db_conn, str(simple_repo.path), "Simple")
        window = MainWindow(conn=db_conn)
        window.show()

        assert window.sidebar is not None
        assert window.diff_view is not None
        assert window.commit_box is not None
