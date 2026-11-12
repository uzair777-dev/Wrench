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

    def test_clear_missing(self, db_conn):
        rid = repo_registry.add_repo(db_conn, "/tmp/missing_repo")
        repo_registry.mark_missing(db_conn, rid)
        assert repo_registry.get_repo_by_id(db_conn, rid).is_missing is True

        repo_registry.clear_missing(db_conn, rid)
        assert repo_registry.get_repo_by_id(db_conn, rid).is_missing is False

    def test_clear_missing_by_path(self, db_conn):
        path = "/tmp/missing_path"
        repo_registry.add_repo(db_conn, path)
        repo_registry.mark_missing(db_conn, path)
        assert repo_registry.get_repo_by_path(db_conn, path).is_missing is True

        repo_registry.clear_missing(db_conn, path)
        assert repo_registry.get_repo_by_path(db_conn, path).is_missing is False


class TestSettings:
    def test_get_set_delete_setting(self, db_conn):
        assert settings.get_setting(db_conn, "theme") is None
        settings.set_setting(db_conn, "theme", "dark")
        assert settings.get_setting(db_conn, "theme") == "dark"
        settings.set_setting(db_conn, "theme", "light")
        assert settings.get_setting(db_conn, "theme") == "light"
        settings.delete_setting(db_conn, "theme")
        assert settings.get_setting(db_conn, "theme") is None

    def test_alias_sync_theme_auto_fetch_and_session_blob_isolation(self, db_conn):
        from wrench.storage.settings_registry import get_settings_registry

        settings.set_setting(db_conn, "theme", "light")
        reg = get_settings_registry(db_conn)
        assert reg.get_str("ui.theme_mode") == "light"

        reg.set("ui.theme_mode", "dark")
        assert settings.get_setting(db_conn, "theme") == "dark"
        stale = db_conn.execute("SELECT value FROM app_settings WHERE key = 'theme'").fetchone()
        assert stale is None

        reg.set("ui.theme_mode", "system")
        assert settings.get_setting(db_conn, "theme") == "auto"

        settings.set_setting(db_conn, "repo.auto_fetch_on_open", "false")
        assert reg.get_bool("remote.auto_fetch.enabled") is False
        reg.set("remote.auto_fetch.enabled", True)
        assert settings.get_setting(db_conn, "repo.auto_fetch_on_open") == "true"

        session_json = '{"version": 1, "active_repo_path": "/tmp/demo"}'
        settings.set_setting(db_conn, "ui.session_state", session_json)
        assert settings.get_setting(db_conn, "ui.session_state") == session_json
        assert reg.get_bool("ui.session_state") is True

        reg.set("ui.session_state", False)
        assert settings.get_setting(db_conn, "ui.session_state") == session_json
        assert reg.get_bool("ui.session_state") is False
