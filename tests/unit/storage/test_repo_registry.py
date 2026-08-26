"""Unit tests for storage/repo_registry.py and storage/settings.py."""

import sqlite3

import pytest

from wrench.storage import repo_registry, settings
from wrench.storage.db import run_migrations


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestRepoRegistry:
    def test_add_and_list(self, db_conn):
        repo_registry.add_repo(db_conn, "/home/user/project")
        repos = repo_registry.list_repos(db_conn)
        assert len(repos) == 1
        assert repos[0].path == "/home/user/project"
        assert repos[0].display_name == "project"

    def test_remove_repo(self, db_conn):
        rid = repo_registry.add_repo(db_conn, "/tmp/repo")
        repo_registry.remove_repo(db_conn, rid)
        assert repo_registry.list_repos(db_conn) == []

    def test_mark_missing(self, db_conn):
        rid = repo_registry.add_repo(db_conn, "/tmp/gone")
        repo_registry.mark_missing(db_conn, rid)
        repos = repo_registry.list_repos(db_conn)
        assert repos[0].is_missing is True

    def test_relocate_preserves_id(self, db_conn):
        rid = repo_registry.add_repo(db_conn, "/old/path")
        repo_registry.mark_missing(db_conn, rid)
        repo_registry.relocate_repo(db_conn, rid, "/new/path")
        repo = repo_registry.get_repo_by_path(db_conn, "/new/path")
        assert repo is not None
        assert repo.id == rid
        assert repo.is_missing is False

    def test_update_last_opened(self, db_conn):
        rid = repo_registry.add_repo(db_conn, "/tmp/repo")
        repo_registry.update_last_opened(db_conn, rid)
        repo = repo_registry.get_repo_by_path(db_conn, "/tmp/repo")
        assert repo.last_opened_at is not None


class TestSettings:
    def test_get_set_delete_setting(self, db_conn):
        assert settings.get_setting(db_conn, "theme") is None
        settings.set_setting(db_conn, "theme", "dark")
        assert settings.get_setting(db_conn, "theme") == "dark"
        settings.set_setting(db_conn, "theme", "light")
        assert settings.get_setting(db_conn, "theme") == "light"
        settings.delete_setting(db_conn, "theme")
        assert settings.get_setting(db_conn, "theme") is None
