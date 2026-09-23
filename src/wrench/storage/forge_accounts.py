"""FR-5.6/5.8: CRUD for forge_accounts and repo_forge_links."""

import logging
import sqlite3
import threading
from dataclasses import dataclass
from uuid import uuid4

from wrench import credentials
from wrench.forge.models import ForgeAccount

logger = logging.getLogger(__name__)
_storage_lock = threading.Lock()


@dataclass
class ForgeAccountRecord:
    """Public representation of a configured account (excluding secret_service_key)."""

    id: int
    provider: str
    instance_url: str
    label: str
    username: str | None
    created_at: str
    tls_ca_bundle_path: str | None = None
    tls_insecure: bool = False


@dataclass
class RepoForgeLink:
    repo_id: int
    forge_account_id: int
    remote_name: str
    owner_slug: str
    repo_slug: str


def add_account(
    conn: sqlite3.Connection,
    provider: str,
    instance_url: str,
    label: str,
    username: str | None,
    token: str,
    *,
    tls_ca_bundle_path: str | None = None,
    tls_insecure: bool = False,
) -> int:
    """Two-step account insertion with rollback protection on Secret Service failure."""
    with _storage_lock:
        pending_key = f"wrench:forge:pending:{uuid4().hex}"
        cur = conn.cursor()
        with conn:
            cur.execute(
                """INSERT INTO forge_accounts (
                    provider, instance_url, label, username,
                    tls_ca_bundle_path, tls_insecure, secret_service_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    provider,
                    instance_url,
                    label,
                    username,
                    tls_ca_bundle_path,
                    1 if tls_insecure else 0,
                    pending_key,
                ),
            )
            account_id = cur.lastrowid
            final_key = f"wrench:forge:{account_id}"
            cur.execute(
                "UPDATE forge_accounts SET secret_service_key = ? WHERE id = ?",
                (final_key, account_id),
            )

        try:
            backend = credentials.get_backend()
            backend.store_secret(final_key, token, label=f"Wrench: {label}")
        except Exception:
            logger.exception(
                "Secret storage failed for account %d; rolling back database row", account_id
            )
            with conn:
                cur.execute("DELETE FROM forge_accounts WHERE id = ?", (account_id,))
            raise

        return account_id


def list_accounts(
    conn: sqlite3.Connection, provider: str | None = None
) -> list[ForgeAccountRecord]:
    """List configured forge accounts, optionally filtered by provider."""
    cur = conn.cursor()
    query = """SELECT id, provider, instance_url, label, username,
                      created_at, tls_ca_bundle_path, tls_insecure
               FROM forge_accounts"""
    params = ()
    if provider:
        query += " WHERE provider = ?"
        params = (provider,)
    query += " ORDER BY id ASC"

    cur.execute(query, params)
    return [
        ForgeAccountRecord(
            id=row[0],
            provider=row[1],
            instance_url=row[2],
            label=row[3],
            username=row[4],
            created_at=row[5],
            tls_ca_bundle_path=row[6],
            tls_insecure=bool(row[7]),
        )
        for row in cur.fetchall()
    ]


def get_account_secret_key(conn: sqlite3.Connection, account_id: int) -> str | None:
    """Targeted lookup of an account's secret_service_key by account id."""
    cur = conn.cursor()
    cur.execute("SELECT secret_service_key FROM forge_accounts WHERE id = ?", (account_id,))
    row = cur.fetchone()
    if row:
        return row[0]
    return None


def get_account_full(conn: sqlite3.Connection, account_id: int) -> ForgeAccount | None:
    """Retrieve full ForgeAccount (including secret key and TLS policy) for adapter construction."""
    cur = conn.cursor()
    cur.execute(
        """SELECT id, provider, instance_url, label, username,
                  secret_service_key, tls_ca_bundle_path, tls_insecure
           FROM forge_accounts WHERE id = ?""",
        (account_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return ForgeAccount(
        id=row[0],
        provider=row[1],
        instance_url=row[2],
        label=row[3],
        username=row[4],
        secret_service_key=row[5],
        tls_ca_bundle_path=row[6],
        tls_insecure=bool(row[7]),
    )


def update_account(
    conn: sqlite3.Connection,
    account_id: int,
    *,
    label: str,
    username: str | None = None,
    tls_ca_bundle_path: str | None = None,
    tls_insecure: bool = False,
) -> None:
    """Update editable metadata and TLS settings for an existing account."""
    with _storage_lock:
        with conn:
            conn.execute(
                """UPDATE forge_accounts
                   SET label = ?, username = ?, tls_ca_bundle_path = ?, tls_insecure = ?
                   WHERE id = ?""",
                (label, username, tls_ca_bundle_path, 1 if tls_insecure else 0, account_id),
            )


def update_username(conn: sqlite3.Connection, account_id: int, username: str) -> None:
    """Backfill or update username for an existing account row."""
    with _storage_lock:
        with conn:
            conn.execute(
                "UPDATE forge_accounts SET username = ? WHERE id = ?",
                (username, account_id),
            )


def remove_account(conn: sqlite3.Connection, account_id: int) -> None:
    """Remove account row (cascades to links) and delete secret from keyring."""
    with _storage_lock:
        cur = conn.cursor()
        cur.execute("SELECT secret_service_key FROM forge_accounts WHERE id = ?", (account_id,))
        row = cur.fetchone()
        secret_key = row[0] if row else None

        with conn:
            cur.execute("DELETE FROM forge_accounts WHERE id = ?", (account_id,))

        if secret_key:
            try:
                credentials.get_backend().delete_secret(secret_key)
            except Exception:
                logger.warning(
                    "Failed to delete secret %s from backend; continuing", secret_key, exc_info=True
                )


def link_repo_to_account(
    conn: sqlite3.Connection,
    repo_id: int,
    forge_account_id: int,
    remote_name: str,
    owner_slug: str,
    repo_slug: str,
) -> None:
    """Upsert repository link to forge account on (repo_id, remote_name)."""
    with _storage_lock:
        with conn:
            conn.execute(
                """INSERT INTO repo_forge_links (
                    repo_id, forge_account_id, remote_name, owner_slug, repo_slug
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(repo_id, remote_name) DO UPDATE SET
                    forge_account_id = excluded.forge_account_id,
                    owner_slug = excluded.owner_slug,
                    repo_slug = excluded.repo_slug""",
                (repo_id, forge_account_id, remote_name, owner_slug, repo_slug),
            )


def unlink_repo_account(conn: sqlite3.Connection, repo_id: int, remote_name: str) -> None:
    """Remove repository forge link for a specific remote."""
    with _storage_lock:
        with conn:
            conn.execute(
                "DELETE FROM repo_forge_links WHERE repo_id = ? AND remote_name = ?",
                (repo_id, remote_name),
            )


def get_link_for_remote(
    conn: sqlite3.Connection, repo_id: int, remote_name: str
) -> RepoForgeLink | None:
    cur = conn.cursor()
    cur.execute(
        """SELECT repo_id, forge_account_id, remote_name, owner_slug, repo_slug
           FROM repo_forge_links
           WHERE repo_id = ? AND remote_name = ?""",
        (repo_id, remote_name),
    )
    row = cur.fetchone()
    if not row:
        return None
    return RepoForgeLink(
        repo_id=row[0],
        forge_account_id=row[1],
        remote_name=row[2],
        owner_slug=row[3],
        repo_slug=row[4],
    )


def list_links_for_repo(conn: sqlite3.Connection, repo_id: int) -> list[RepoForgeLink]:
    """Retrieve all forge links for a repository across all configured remotes."""
    cur = conn.cursor()
    cur.execute(
        """SELECT repo_id, forge_account_id, remote_name, owner_slug, repo_slug
           FROM repo_forge_links
           WHERE repo_id = ?
           ORDER BY (remote_name = 'origin') DESC, remote_name ASC""",
        (repo_id,),
    )
    return [
        RepoForgeLink(
            repo_id=row[0],
            forge_account_id=row[1],
            remote_name=row[2],
            owner_slug=row[3],
            repo_slug=row[4],
        )
        for row in cur.fetchall()
    ]


def find_link_by_path(
    conn: sqlite3.Connection,
    owner_slug: str,
    repo_slug: str,
    candidate_account_ids: list[int] | None = None,
) -> RepoForgeLink | None:
    """Find a repo_forge_link row matching owner_slug and repo_slug.

    If candidate_account_ids is provided, restricts matches to those account IDs
    to prevent cross-website collisions when the same repo path exists on multiple websites.
    """
    cur = conn.cursor()
    query = """SELECT repo_id, forge_account_id, remote_name, owner_slug, repo_slug
               FROM repo_forge_links
               WHERE owner_slug = ? AND repo_slug = ?"""
    params: list[object] = [owner_slug, repo_slug]
    if candidate_account_ids:
        placeholders = ",".join("?" for _ in candidate_account_ids)
        query += f" AND forge_account_id IN ({placeholders})"
        params.extend(candidate_account_ids)

    cur.execute(query, params)
    row = cur.fetchone()
    if not row:
        return None
    return RepoForgeLink(
        repo_id=row[0],
        forge_account_id=row[1],
        remote_name=row[2],
        owner_slug=row[3],
        repo_slug=row[4],
    )


def get_remote_slug(
    conn: sqlite3.Connection, repo_id: int, remote_name: str
) -> tuple[str, str] | None:
    link = get_link_for_remote(conn, repo_id, remote_name)
    if link:
        return (link.owner_slug, link.repo_slug)
    return None
