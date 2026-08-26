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
    if display_name is None:
        display_name = Path(path).name

    with _db_lock:
        cursor = conn.execute(
            "INSERT INTO repos (path, display_name) VALUES (?, ?)",
            (path, display_name),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def list_repos(conn: sqlite3.Connection) -> list[RepoRecord]:
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM repos ORDER BY last_opened_at DESC NULLS LAST"
        ).fetchall()
        return [_row_to_record(row) for row in rows]


def get_repo_by_path(conn: sqlite3.Connection, path: str) -> RepoRecord | None:
    with _db_lock:
        row = conn.execute("SELECT * FROM repos WHERE path = ?", (path,)).fetchone()
        return _row_to_record(row) if row else None


def get_repo_by_id(conn: sqlite3.Connection, repo_id: int) -> RepoRecord | None:
    with _db_lock:
        row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
        return _row_to_record(row) if row else None


def remove_repo(conn: sqlite3.Connection, repo_id: int) -> None:
    with _db_lock:
        conn.execute("DELETE FROM repos WHERE id = ?", (repo_id,))
        conn.commit()


def update_last_opened(conn: sqlite3.Connection, repo_id: int) -> None:
    with _db_lock:
        conn.execute(
            "UPDATE repos SET last_opened_at = ? WHERE id = ?",
            (datetime.now().isoformat(), repo_id),
        )
        conn.commit()


def update_last_branch(conn: sqlite3.Connection, repo_id: int, branch: str) -> None:
    with _db_lock:
        conn.execute(
            "UPDATE repos SET last_branch = ? WHERE id = ?",
            (branch, repo_id),
        )
        conn.commit()


def mark_missing(conn: sqlite3.Connection, repo_id: int) -> None:
    with _db_lock:
        conn.execute("UPDATE repos SET is_missing = 1 WHERE id = ?", (repo_id,))
        conn.commit()


def relocate_repo(conn: sqlite3.Connection, repo_id: int, new_path: str) -> None:
    with _db_lock:
        conn.execute(
            "UPDATE repos SET path = ?, is_missing = 0 WHERE id = ?",
            (new_path, repo_id),
        )
        conn.commit()
