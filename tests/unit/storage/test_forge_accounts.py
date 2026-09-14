"""Unit tests for storage/forge_accounts.py."""

import sqlite3

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

    def test_list_accounts_and_filter_by_provider(self, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES (?, ?, ?, ?, ?)""",
            ("github", "https://github.com", "GitHub Personal", "uzair", "wrench:forge:1"),
        )
        cur.execute(
            """INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES (?, ?, ?, ?, ?)""",
            ("gitlab", "https://gitlab.com", "GitLab Work", "uzair-work", "wrench:forge:2"),
        )
        db_conn.commit()

        all_accounts = forge_accounts.list_accounts(db_conn)
        assert len(all_accounts) == 2

        gh_accounts = forge_accounts.list_accounts(db_conn, provider="github")
        assert len(gh_accounts) == 1
        assert gh_accounts[0].provider == "github"
        assert gh_accounts[0].label == "GitHub Personal"
        assert gh_accounts[0].username == "uzair"
        # Verify secret_service_key is not an attribute on ForgeAccountRecord
        assert not hasattr(gh_accounts[0], "secret_service_key")

    def test_get_account_secret_key(self, db_conn):
        cur = db_conn.cursor()
        cur.execute(
            """INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES (?, ?, ?, ?, ?)""",
            ("github", "https://github.com", "GitHub Personal", "uzair", "wrench:forge:42"),
        )
        account_id = cur.lastrowid
        db_conn.commit()

        key = forge_accounts.get_account_secret_key(db_conn, account_id)
        assert key == "wrench:forge:42"

        missing_key = forge_accounts.get_account_secret_key(db_conn, 9999)
        assert missing_key is None

    def test_find_link_by_path(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("INSERT INTO repos (path, display_name) VALUES ('/path/to/repo', 'repo')")
        repo_id = cur.lastrowid

        cur.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'GitHub', 'uzair', 'wrench:forge:1')""")
        acc_id = cur.lastrowid

        cur.execute(
            """INSERT INTO repo_forge_links
               (repo_id, forge_account_id, remote_name, owner_slug, repo_slug)
               VALUES (?, ?, 'origin', 'uzair', 'wrench')""",
            (repo_id, acc_id),
        )
        db_conn.commit()

        link = forge_accounts.find_link_by_path(db_conn, "uzair", "wrench")
        assert link is not None
        assert link.repo_id == repo_id
        assert link.forge_account_id == acc_id
        assert link.owner_slug == "uzair"
        assert link.repo_slug == "wrench"

        not_found = forge_accounts.find_link_by_path(db_conn, "other", "wrench")
        assert not_found is None

    def test_update_username(self, db_conn):
        cur = db_conn.cursor()
        cur.execute("""INSERT INTO forge_accounts
               (provider, instance_url, label, username, secret_service_key)
               VALUES ('github', 'https://github.com', 'GitHub', NULL, 'wrench:forge:1')""")
        account_id = cur.lastrowid
        db_conn.commit()

        forge_accounts.update_username(db_conn, account_id, "new-user")
        row = db_conn.execute(
            "SELECT username FROM forge_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        assert row["username"] == "new-user"
