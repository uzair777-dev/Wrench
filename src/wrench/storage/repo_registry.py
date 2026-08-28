"""FR-1.2/1.3: CRUD for the repo registry (known repositories)."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .db import _db_lock


@dataclass
class RepoRecord:
    id: int
    path: str
    display_name: str
    last_branch: str | None
    last_opened_at: str | None
    is_missing: bool
    created_at: str


def _row_to_record(row: sqlite3.Row) -> RepoRecord:
    return RepoRecord(
        id=row["id"],
        path=row["path"],
        display_name=row["display_name"],
        last_branch=row["last_branch"],
        last_opened_at=row["last_opened_at"],
        is_missing=bool(row["is_missing"]),
        created_at=row["created_at"],
    )


def add_repo(
    conn: sqlite3.Connection,
    path: str,
    display_name: str | None = None,
) -> int:
    """Adds a repository or updates last_opened_at if already registered."""
    p_str = str(path)
    if display_name is None:
        display_name = Path(p_str).name

    now = datetime.now().isoformat()
    with _db_lock:
        cursor = conn.execute(
            "INSERT INTO repos (path, display_name, last_opened_at, is_missing) "
            "VALUES (?, ?, ?, 0) "
            "ON CONFLICT(path) DO UPDATE SET "
            "last_opened_at = excluded.last_opened_at, is_missing = 0",
            (p_str, display_name, now),
        )
        conn.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        row = conn.execute("SELECT id FROM repos WHERE path = ?", (p_str,)).fetchone()
        return row["id"] if row else 0


def list_repos(conn: sqlite3.Connection) -> list[RepoRecord]:
    """Lists all registered repositories, sorted by last_opened_at descending."""
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM repos ORDER BY last_opened_at DESC NULLS LAST"
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def get_repo_by_path(conn: sqlite3.Connection, path: str) -> RepoRecord | None:
    with _db_lock:
        row = conn.execute("SELECT * FROM repos WHERE path = ?", (str(path),)).fetchone()
        return _row_to_record(row) if row else None


def get_repo_by_id(conn: sqlite3.Connection, repo_id: int) -> RepoRecord | None:
    with _db_lock:
        row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
        return _row_to_record(row) if row else None


def remove_repo(conn: sqlite3.Connection, path_or_id: str | int) -> None:
    """Removes a repository by ID or path."""
    with _db_lock:
        if isinstance(path_or_id, int):
            conn.execute("DELETE FROM repos WHERE id = ?", (path_or_id,))
        else:
            conn.execute("DELETE FROM repos WHERE path = ?", (str(path_or_id),))
        conn.commit()


def touch_repo(conn: sqlite3.Connection, path_or_id: str | int) -> None:
    """Updates last_opened_at timestamp by ID or path."""
    now = datetime.now().isoformat()
    with _db_lock:
        if isinstance(path_or_id, int):
            conn.execute(
                "UPDATE repos SET last_opened_at = ? WHERE id = ?",
                (now, path_or_id),
            )
        else:
            conn.execute(
                "UPDATE repos SET last_opened_at = ? WHERE path = ?",
                (now, str(path_or_id)),
            )
        conn.commit()


def update_last_opened(conn: sqlite3.Connection, path_or_id: str | int) -> None:
    touch_repo(conn, path_or_id)


def update_last_branch(conn: sqlite3.Connection, path_or_id: str | int, branch: str) -> None:
    with _db_lock:
        if isinstance(path_or_id, int):
            conn.execute(
                "UPDATE repos SET last_branch = ? WHERE id = ?",
                (branch, path_or_id),
            )
        else:
            conn.execute(
                "UPDATE repos SET last_branch = ? WHERE path = ?",
                (branch, str(path_or_id)),
            )
        conn.commit()


def mark_missing(conn: sqlite3.Connection, path_or_id: str | int) -> None:
    with _db_lock:
        if isinstance(path_or_id, int):
            conn.execute("UPDATE repos SET is_missing = 1 WHERE id = ?", (path_or_id,))
        else:
            conn.execute("UPDATE repos SET is_missing = 1 WHERE path = ?", (str(path_or_id),))
        conn.commit()


def relocate_repo(conn: sqlite3.Connection, old_path_or_id: str | int, new_path: str) -> None:
    """Updates the filesystem path of a relocated repository."""
    with _db_lock:
        if isinstance(old_path_or_id, int):
            conn.execute(
                "UPDATE repos SET path = ?, is_missing = 0 WHERE id = ?",
                (str(new_path), old_path_or_id),
            )
        else:
            conn.execute(
                "UPDATE repos SET path = ?, is_missing = 0 WHERE path = ?",
                (str(new_path), str(old_path_or_id)),
            )
        conn.commit()
