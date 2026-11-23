"""Storage operations for named workspace sessions (VP-3, FR-1.15)."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from wrench.core.models import WorkspaceSession

logger = logging.getLogger(__name__)


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure optional tabs_json column exists."""
    try:
        conn.execute("ALTER TABLE workspace_sessions ADD COLUMN tabs_json TEXT DEFAULT '[]'")
    except sqlite3.OperationalError:
        pass


def save_session(
    conn: sqlite3.Connection,
    session_name: str,
    repo_paths: list[str] | tuple[str, ...],
    active_index: int = 0,
    tabs: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> None:
    """Save or update a named workspace session."""
    _ensure_schema(conn)
    paths_json = json.dumps(list(repo_paths))
    tabs_data_json = json.dumps(list(tabs))
    with conn:
        conn.execute(
            """
            INSERT INTO workspace_sessions (session_name, repo_paths_json, active_index, tabs_json, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(session_name) DO UPDATE SET
                repo_paths_json = excluded.repo_paths_json,
                active_index = excluded.active_index,
                tabs_json = excluded.tabs_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (session_name.strip(), paths_json, max(0, int(active_index)), tabs_data_json),
        )


def load_session(conn: sqlite3.Connection, session_name: str) -> WorkspaceSession | None:
    """Load a named workspace session by name."""
    _ensure_schema(conn)
    cursor = conn.execute(
        "SELECT session_name, repo_paths_json, active_index, tabs_json FROM workspace_sessions WHERE session_name = ?",
        (session_name.strip(),),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    try:
        paths = tuple(json.loads(row[1]))
    except Exception as e:
        logger.warning("Failed parsing session repo paths JSON: %s", e)
        paths = ()
    tabs: tuple[dict[str, Any], ...] = ()
    if len(row) > 3 and row[3]:
        try:
            tabs = tuple(json.loads(row[3]))
        except Exception as e:
            logger.warning("Failed parsing session tabs JSON: %s", e)
            tabs = ()
    return WorkspaceSession(
        session_name=row[0],
        repo_paths=paths,
        active_index=row[2],
        tabs=tabs,
    )


def list_sessions(conn: sqlite3.Connection) -> list[str]:
    """Return all saved session names ordered by update time descending."""
    cursor = conn.execute("SELECT session_name FROM workspace_sessions ORDER BY updated_at DESC")
    return [r[0] for r in cursor.fetchall()]


def delete_session(conn: sqlite3.Connection, session_name: str) -> bool:
    """Delete a named workspace session."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM workspace_sessions WHERE session_name = ?",
            (session_name.strip(),),
        )
        return cursor.rowcount > 0
