"""Unit tests for engine remotes management and façade remote operations."""

import sqlite3

import pytest

from wrench.core import engine, write_ops
from wrench.core.exceptions import (
    GitCommandError,
    RemoteExistsError,
    RemoteNotFoundError,
)
from wrench.storage import settings


@pytest.fixture
def bare_repo_fixture(tmp_path):
    bare_dir = tmp_path / "remote.git"
    write_ops.run_git(tmp_path, ["init", "--bare", str(bare_dir)])
    write_ops.run_git(bare_dir, ["symbolic-ref", "HEAD", "refs/heads/main"])

    clone1_dir = tmp_path / "clone1"
    write_ops.run_git(tmp_path, ["clone", str(bare_dir), str(clone1_dir)])
    write_ops.run_git(clone1_dir, ["config", "user.name", "Test User"])
    write_ops.run_git(clone1_dir, ["config", "user.email", "test@example.com"])

    (clone1_dir / "README.md").write_text("initial content\n")
    write_ops.run_git(clone1_dir, ["add", "README.md"])
    write_ops.run_git(clone1_dir, ["commit", "-m", "Initial commit"])
    write_ops.run_git(clone1_dir, ["branch", "-M", "main"])
    write_ops.run_git(clone1_dir, ["push", "-u", "origin", "main"])

    return bare_dir, clone1_dir


class TestEngineRemoteOperations:
    def test_engine_push_pull_fetch_facade(self, bare_repo_fixture, tmp_path):
        bare_dir, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        # Commit new file
        (clone1_dir / "engine_test.txt").write_text("engine test\n")
        write_ops.run_git(clone1_dir, ["add", "engine_test.txt"])
        write_ops.run_git(clone1_dir, ["commit", "-m", "Engine commit"])

        # Engine push
        engine.push(repo, "origin", "main")
        rev_bare = write_ops.run_git(bare_dir, ["rev-parse", "main"]).stdout.strip()
        rev_local = write_ops.run_git(clone1_dir, ["rev-parse", "HEAD"]).stdout.strip()
        assert rev_bare == rev_local

        # Engine fetch
        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
        conn.commit()

        engine.fetch(repo, "origin", db_conn=conn)
        assert settings.get_setting(conn, "remote_last_fetch.origin") is not None

        # Engine pull
        engine.pull(repo, "origin", "main")


class TestEngineRemotesManagement:
    def test_list_remotes_initial(self, bare_repo_fixture, tmp_path):
        bare_dir, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
        settings.set_setting(conn, "remote_last_fetch.origin", "2026-09-14T10:00:00Z")
        settings.set_setting(conn, "remote_reachable.origin", "1")
        conn.commit()

        remotes = engine.list_remotes(repo, db_conn=conn)
        assert len(remotes) == 1
        r = remotes[0]
        assert r.name == "origin"
        assert str(bare_dir) in r.url
        assert r.last_fetch_at == "2026-09-14T10:00:00Z"
        assert r.is_reachable is True

    def test_add_remote_validation(self, bare_repo_fixture):
        _, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        # Invalid names
        for bad_name in ["", "-upstream", "up stream", "up$tream"]:
            with pytest.raises(GitCommandError) as exc_info:
                engine.add_remote(repo, bad_name, "https://github.com/org/repo.git")
            assert "invalid remote name" in str(exc_info.value).lower()

        # Invalid URLs
        for bad_url in ["not-a-url", "ftp://foo.bar", "file:///invalid"]:
            with pytest.raises(GitCommandError) as exc_info:
                engine.add_remote(repo, "upstream", bad_url)
            assert "invalid remote url" in str(exc_info.value).lower()

        # Duplicate remote name
        with pytest.raises(RemoteExistsError):
            engine.add_remote(repo, "origin", "https://github.com/org/repo.git")

    def test_add_remote_success_and_config(self, bare_repo_fixture, tmp_path):
        _, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        db_file = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
        conn.commit()

        engine.add_remote(
            repo,
            "upstream",
            "https://github.com/upstream/repo.git",
            db_conn=conn,
        )

        remotes = [r.name for r in engine.list_remotes(repo, db_conn=conn)]
        assert "upstream" in remotes

        # Verify credential helper configuration was applied
        h = write_ops.run_git(clone1_dir, ["config", "--local", "credential.helper"]).stdout.strip()
        p = write_ops.run_git(
            clone1_dir, ["config", "--local", "credential.useHttpPath"]
        ).stdout.strip()
        assert h == "wrench"
        assert p == "true"

    def test_remove_remote(self, bare_repo_fixture):
        _, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        with pytest.raises(RemoteNotFoundError):
            engine.remove_remote(repo, "nonexistent")

        engine.remove_remote(repo, "origin")
        remotes = [r.name for r in engine.list_remotes(repo)]
        assert "origin" not in remotes

    def test_set_remote_url(self, bare_repo_fixture):
        _, clone1_dir = bare_repo_fixture
        repo = engine.open_repo(clone1_dir)

        with pytest.raises(RemoteNotFoundError):
            engine.set_remote_url(repo, "nonexistent", "https://github.com/org/repo.git")

        with pytest.raises(GitCommandError):
            engine.set_remote_url(repo, "origin", "invalid-url")

        new_url = "https://github.com/new/url.git"
        engine.set_remote_url(repo, "origin", new_url)

        remotes = engine.list_remotes(repo)
        assert len(remotes) == 1
        assert remotes[0].url == new_url
