"""Unit tests for storage/forge_accounts.py."""

import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from wrench.storage import forge_accounts
from wrench.storage.db import run_migrations


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestForgeAccountsStorage:
    def test_list_accounts_empty(self, db_conn):
        accounts = forge_accounts.list_accounts(db_conn)
        assert accounts == []

    def test_add_and_list_accounts(self, db_conn):
        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub Personal",
                username="alice",
                token="ghp_secrettoken123",
                tls_ca_bundle_path=None,
                tls_insecure=False,
            )

        assert acc_id > 0
        mock_backend.store_secret.assert_called_once_with(
            f"wrench:forge:{acc_id}", "ghp_secrettoken123", label="Wrench: GitHub Personal"
        )

        records = forge_accounts.list_accounts(db_conn)
        assert len(records) == 1
        assert records[0].id == acc_id
        assert records[0].provider == "github"
        assert records[0].label == "GitHub Personal"
        assert records[0].username == "alice"
        assert records[0].tls_insecure is False
        assert not hasattr(records[0], "secret_service_key")

    def test_add_account_rollback_on_keyring_failure(self, db_conn):
        mock_backend = MagicMock()
        mock_backend.store_secret.side_effect = RuntimeError("Keyring locked")

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            with pytest.raises(RuntimeError, match="Keyring locked"):
                forge_accounts.add_account(
                    db_conn,
                    provider="gitlab",
                    instance_url="https://gitlab.com",
                    label="GitLab Work",
                    username="bob",
                    token="glpat_token",
                )

        # Database row must be completely rolled back
        assert forge_accounts.list_accounts(db_conn) == []

    def test_get_account_full(self, db_conn):
        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="forgejo",
                instance_url="https://forgejo.example.com",
                label="Work Forgejo",
                username="carol",
                token="token456",
                tls_ca_bundle_path="/etc/ssl/ca.pem",
                tls_insecure=False,
            )

        full = forge_accounts.get_account_full(db_conn, acc_id)
        assert full is not None
        assert full.id == acc_id
        assert full.provider == "forgejo"
        assert full.instance_url == "https://forgejo.example.com"
        assert full.secret_service_key == f"wrench:forge:{acc_id}"
        assert full.tls_ca_bundle_path == "/etc/ssl/ca.pem"
        assert full.tls_insecure is False

        assert forge_accounts.get_account_full(db_conn, 9999) is None

    def test_update_account(self, db_conn):
        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="Old Label",
                username="old_user",
                token="token",
            )

        forge_accounts.update_account(
            db_conn,
            acc_id,
            label="New Label",
            username="new_user",
            tls_ca_bundle_path=None,
            tls_insecure=True,
        )

        full = forge_accounts.get_account_full(db_conn, acc_id)
        assert full is not None
        assert full.label == "New Label"
        assert full.username == "new_user"
        assert full.tls_insecure is True

    def test_remove_account_deletes_row_and_cascades(self, db_conn):
        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_id = forge_accounts.add_account(
                db_conn,
                provider="github",
                instance_url="https://github.com",
                label="GitHub",
                username="alice",
                token="token",
            )

        # Link a repo
        db_conn.execute("INSERT INTO repos (path, display_name) VALUES ('/repo', 'repo')")
        repo_id = db_conn.execute("SELECT id FROM repos WHERE path = '/repo'").fetchone()[0]

        forge_accounts.link_repo_to_account(db_conn, repo_id, acc_id, "origin", "alice", "repo")
        assert forge_accounts.get_link_for_remote(db_conn, repo_id, "origin") is not None

        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            forge_accounts.remove_account(db_conn, acc_id)

        # Account removed
        assert forge_accounts.get_account_full(db_conn, acc_id) is None
        # Secret deleted
        mock_backend.delete_secret.assert_called_once_with(f"wrench:forge:{acc_id}")
        # Cascade deleted link row
        assert forge_accounts.get_link_for_remote(db_conn, repo_id, "origin") is None

    def test_repo_links_and_candidate_filtering(self, db_conn):
        mock_backend = MagicMock()
        with patch("wrench.credentials.get_backend", return_value=mock_backend):
            acc_gh = forge_accounts.add_account(
                db_conn, "github", "https://github.com", "GH", "alice", "token1"
            )
            acc_gl = forge_accounts.add_account(
                db_conn, "gitlab", "https://gitlab.com", "GL", "alice", "token2"
            )

        db_conn.execute("INSERT INTO repos (path, display_name) VALUES ('/my/project', 'project')")
        repo_id = db_conn.execute("SELECT id FROM repos WHERE path = '/my/project'").fetchone()[0]

        # Link origin to GitHub, and gitlab remote to GitLab
        forge_accounts.link_repo_to_account(db_conn, repo_id, acc_gh, "origin", "myorg", "project")
        forge_accounts.link_repo_to_account(db_conn, repo_id, acc_gl, "gitlab", "myorg", "project")

        # Test list_links_for_repo
        links = forge_accounts.list_links_for_repo(db_conn, repo_id)
        assert len(links) == 2
        # 'origin' ordered first
        assert links[0].remote_name == "origin"
        assert links[0].forge_account_id == acc_gh
        assert links[1].remote_name == "gitlab"
        assert links[1].forge_account_id == acc_gl

        # Test candidate_account_ids filtering in find_link_by_path
        link_gh = forge_accounts.find_link_by_path(
            db_conn, "myorg", "project", candidate_account_ids=[acc_gh]
        )
        assert link_gh is not None
        assert link_gh.forge_account_id == acc_gh

        link_gl = forge_accounts.find_link_by_path(
            db_conn, "myorg", "project", candidate_account_ids=[acc_gl]
        )
        assert link_gl is not None
        assert link_gl.forge_account_id == acc_gl

        # Non-matching candidate
        link_none = forge_accounts.find_link_by_path(
            db_conn, "myorg", "project", candidate_account_ids=[9999]
        )
        assert link_none is None

    def test_schema_migration_v1_to_v2(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # Create minimal v1 schema manually
        conn.executescript("""
            PRAGMA user_version = 1;
            CREATE TABLE forge_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                instance_url TEXT NOT NULL,
                label TEXT NOT NULL,
                username TEXT,
                secret_service_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        run_migrations(conn)

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2

        # Verify new columns exist by inserting with them
        conn.execute("""INSERT INTO forge_accounts (
                provider, instance_url, label, username,
                tls_ca_bundle_path, tls_insecure, secret_service_key
            ) VALUES ('github', 'https://github.com', 'Label', 'user', '/path.pem', 1, 'key')""")
        row = conn.execute("SELECT tls_ca_bundle_path, tls_insecure FROM forge_accounts").fetchone()
        assert row["tls_ca_bundle_path"] == "/path.pem"
        assert row["tls_insecure"] == 1
        conn.close()
