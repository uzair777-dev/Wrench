"""Unit tests for core/git_credential_helper.py (§5 Phase 3 Step 2)."""

import io
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from wrench.core import git_credential_helper
from wrench.credentials.backend import CredentialBackend, CredentialBackendUnavailableError
from wrench.storage.db import run_migrations


class StubCredentialBackend(CredentialBackend):
    def __init__(self):
        self.secrets = {}
        self.store_calls = []
        self.delete_calls = []

    def store_secret(self, key: str, secret: str, *, label: str) -> None:
        self.secrets[key] = secret
        self.store_calls.append((key, secret, label))

    def get_secret(self, key: str) -> str | None:
        return self.secrets.get(key)

    def delete_secret(self, key: str) -> None:
        self.secrets.pop(key, None)
        self.delete_calls.append(key)

    def unavailable_help_text(self) -> str:
        return "Stub unavailable"


@pytest.fixture
def fake_db(tmp_path):
    db_path = tmp_path / "wrench.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    conn.close()
    return db_path


def run_helper(argv, stdin_text, stub_backend, db_path):
    stdin = io.StringIO(stdin_text)
    stdout = io.StringIO()
    stderr = io.StringIO()

    with (
        patch("sys.argv", ["git-credential-wrench"] + argv),
        patch("sys.stdin", stdin),
        patch("sys.stdout", stdout),
        patch("sys.stderr", stderr),
        patch("wrench.credentials.get_backend", return_value=stub_backend),
        patch("wrench.core.paths.data_dir", return_value=db_path.parent),
    ):
        with pytest.raises(SystemExit) as exc_info:
            git_credential_helper.main()
        exit_code = exc_info.value.code

    return exit_code, stdout.getvalue(), stderr.getvalue()


class TestGitCredentialHelper:
    def test_invalid_argument_exits_one(self, fake_db):
        backend = StubCredentialBackend()
        code, stdout, stderr = run_helper(["unknown"], "", backend, fake_db)
        assert code == 1
        assert stdout == ""

    def test_non_http_protocol_silent_exit_zero(self, fake_db):
        backend = StubCredentialBackend()
        code, stdout, stderr = run_helper(
            ["get"], "protocol=ssh\nhost=github.com\n", backend, fake_db
        )
        assert code == 0
        assert stdout == ""

    def test_get_happy_path_single_account(self, fake_db):
        backend = StubCredentialBackend()
        backend.secrets["wrench:forge:1"] = "pat-token-123"

        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Personal', 'uzair', 'wrench:forge:1')""")
        conn.commit()
        conn.close()

        stdin = "protocol=https\nhost=github.com\n\n"
        code, stdout, stderr = run_helper(["get"], stdin, backend, fake_db)
        assert code == 0
        assert "username=uzair\n" in stdout
        assert "password=pat-token-123\n" in stdout

    def test_get_unknown_host_empty_exit_zero(self, fake_db):
        backend = StubCredentialBackend()
        stdin = "protocol=https\nhost=unknown-forge.org\n\n"
        code, stdout, stderr = run_helper(["get"], stdin, backend, fake_db)
        assert code == 0
        assert stdout == ""

    def test_get_ambiguous_accounts_no_path_empty_exit_zero(self, fake_db):
        backend = StubCredentialBackend()
        backend.secrets["wrench:forge:1"] = "token-1"
        backend.secrets["wrench:forge:2"] = "token-2"

        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Acc1', 'user1', 'wrench:forge:1')""")
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Acc2', 'user2', 'wrench:forge:2')""")
        conn.commit()
        conn.close()

        stdin = "protocol=https\nhost=github.com\n\n"
        code, stdout, stderr = run_helper(["get"], stdin, backend, fake_db)
        assert code == 0
        assert stdout == ""

    def test_get_ambiguous_accounts_with_path_matching_link(self, fake_db):
        backend = StubCredentialBackend()
        backend.secrets["wrench:forge:1"] = "token-1"
        backend.secrets["wrench:forge:2"] = "token-2"

        conn = sqlite3.connect(str(fake_db))
        cur = conn.cursor()
        cur.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Acc1', 'user1', 'wrench:forge:1')""")
        cur.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Acc2', 'user2', 'wrench:forge:2')""")
        acc2_id = cur.lastrowid
        cur.execute("INSERT INTO repos (path, display_name) VALUES ('/tmp/r1', 'r1')")
        repo_id = cur.lastrowid
        cur.execute(
            """INSERT INTO repo_forge_links
               (repo_id, forge_account_id, remote_name, owner_slug, repo_slug)
               VALUES (?, ?, 'origin', 'team', 'project')""",
            (repo_id, acc2_id),
        )
        conn.commit()
        conn.close()

        # Input with .git
        stdin1 = "protocol=https\nhost=github.com\npath=team/project.git\n\n"
        code1, stdout1, _ = run_helper(["get"], stdin1, backend, fake_db)
        assert code1 == 0
        assert "username=user2\n" in stdout1
        assert "password=token-2\n" in stdout1

        # Input without .git
        stdin2 = "protocol=https\nhost=github.com\npath=/team/project\n\n"
        code2, stdout2, _ = run_helper(["get"], stdin2, backend, fake_db)
        assert code2 == 0
        assert "username=user2\n" in stdout2
        assert "password=token-2\n" in stdout2

    def test_store_updates_secret_and_backfills_username(self, fake_db):
        backend = StubCredentialBackend()
        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Personal', NULL, 'wrench:forge:1')""")
        conn.commit()
        conn.close()

        stdin = "protocol=https\nhost=github.com\nusername=newuser\npassword=token=with=equals\n\n"
        code, stdout, stderr = run_helper(["store"], stdin, backend, fake_db)
        assert code == 0
        assert stdout == ""
        assert len(backend.store_calls) == 1
        assert backend.store_calls[0][0] == "wrench:forge:1"
        assert backend.store_calls[0][1] == "token=with=equals"
        assert backend.store_calls[0][2] == "Wrench: Personal"

        # Check username backfill
        conn = sqlite3.connect(str(fake_db))
        row = conn.execute("SELECT username FROM forge_accounts WHERE id = 1").fetchone()
        conn.close()
        assert row[0] == "newuser"

    def test_store_no_matching_account_silent_exit_zero(self, fake_db):
        backend = StubCredentialBackend()
        stdin = "protocol=https\nhost=nonexistent.org\nusername=user\npassword=pass\n\n"
        code, stdout, stderr = run_helper(["store"], stdin, backend, fake_db)
        assert code == 0
        assert len(backend.store_calls) == 0

    def test_erase_deletes_secret(self, fake_db):
        backend = StubCredentialBackend()
        backend.secrets["wrench:forge:1"] = "secret"

        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Personal', 'user', 'wrench:forge:1')""")
        conn.commit()
        conn.close()

        stdin = "protocol=https\nhost=github.com\n\n"
        code, stdout, stderr = run_helper(["erase"], stdin, backend, fake_db)
        assert code == 0
        assert stdout == ""
        assert backend.delete_calls == ["wrench:forge:1"]

    def test_backend_exception_silent_to_git(self, fake_db):
        backend = MagicMock(spec=CredentialBackend)
        backend.get_secret.side_effect = CredentialBackendUnavailableError("D-Bus down")

        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Personal', 'user', 'wrench:forge:1')""")
        conn.commit()
        conn.close()

        stdin = "protocol=https\nhost=github.com\n\n"
        code, stdout, stderr = run_helper(["get"], stdin, backend, fake_db)
        assert code == 0
        assert stdout == ""
        assert "D-Bus down" in stderr

    def test_database_locked_retry_loop(self, fake_db):
        backend = StubCredentialBackend()
        backend.secrets["wrench:forge:1"] = "token"

        conn = sqlite3.connect(str(fake_db))
        conn.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'Personal', 'user', 'wrench:forge:1')""")
        conn.commit()
        conn.close()

        real_connect = sqlite3.connect
        call_count = 0

        def flaky_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return real_connect(*args, **kwargs)

        with (
            patch("sqlite3.connect", side_effect=flaky_connect),
            patch("time.sleep", return_value=None),
        ):
            stdin = "protocol=https\nhost=github.com\n\n"
            code, stdout, stderr = run_helper(["get"], stdin, backend, fake_db)
            assert code == 0
            assert "password=token\n" in stdout
            assert call_count == 3
