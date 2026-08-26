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


def list_accounts(conn: sqlite3.Connection) -> list[ForgeAccountRecord]:
    raise NotImplementedError


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
