"""App-level and per-repo settings CRUD."""

import sqlite3

from .db import _db_lock


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    with _db_lock:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with _db_lock:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    with _db_lock:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        conn.commit()
