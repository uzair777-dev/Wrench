"""FR-5.6/5.8: CRUD for forge_accounts and repo_forge_links."""

import sqlite3
from dataclasses import dataclass


@dataclass
class ForgeAccountRecord:
    id: int
    provider: str
    instance_url: str
    label: str
    username: str | None
    created_at: str


@dataclass
class RepoForgeLink:
    repo_id: int
    forge_account_id: int
    remote_name: str
    owner_slug: str
    repo_slug: str


def list_accounts(
    conn: sqlite3.Connection, provider: str | None = None
) -> list[ForgeAccountRecord]:
    """List configured forge accounts, optionally filtered by provider."""
    cur = conn.cursor()
    if provider:
        cur.execute(
            """SELECT id, provider, instance_url, label, username, created_at
               FROM forge_accounts
               WHERE provider = ?
               ORDER BY id ASC""",
            (provider,),
        )
    else:
        cur.execute("""SELECT id, provider, instance_url, label, username, created_at
               FROM forge_accounts
               ORDER BY id ASC""")

    records = []
    for row in cur.fetchall():
        records.append(
            ForgeAccountRecord(
                id=row[0],
                provider=row[1],
                instance_url=row[2],
                label=row[3],
                username=row[4],
                created_at=row[5],
            )
        )
    return records


def get_account_secret_key(conn: sqlite3.Connection, account_id: int) -> str | None:
    """Targeted lookup of an account's secret_service_key by account id."""
    cur = conn.cursor()
    cur.execute("SELECT secret_service_key FROM forge_accounts WHERE id = ?", (account_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    return None


def find_link_by_path(
    conn: sqlite3.Connection, owner_slug: str, repo_slug: str
) -> RepoForgeLink | None:
    """Find a repo_forge_link row matching owner_slug and repo_slug."""
    cur = conn.cursor()
    cur.execute(
        """SELECT repo_id, forge_account_id, remote_name, owner_slug, repo_slug
           FROM repo_forge_links
           WHERE owner_slug = ? AND repo_slug = ?""",
        (owner_slug, repo_slug),
    )
    row = cur.fetchone()
    if row:
        return RepoForgeLink(
            repo_id=row[0],
            forge_account_id=row[1],
            remote_name=row[2],
            owner_slug=row[3],
            repo_slug=row[4],
        )
    return None


def update_username(conn: sqlite3.Connection, account_id: int, username: str) -> None:
    """Backfill or update username for an existing account row."""
    with conn:
        conn.execute(
            "UPDATE forge_accounts SET username = ? WHERE id = ?",
            (username, account_id),
        )


def add_account(
    conn: sqlite3.Connection,
    provider: str,
    instance_url: str,
    label: str,
    secret_service_key: str,
    username: str | None = None,
) -> int:
    raise NotImplementedError


def remove_account(conn: sqlite3.Connection, account_id: int) -> None:
    raise NotImplementedError
