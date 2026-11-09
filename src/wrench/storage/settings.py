"""App-level and per-repo settings CRUD with backward-compatible delegation to SettingsRegistry."""

from __future__ import annotations

import json
import sqlite3

from .db import _db_lock
from .settings_registry import get_settings_registry


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    with _db_lock:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row:
            return row["value"] if isinstance(row, sqlite3.Row) else row[0]

    # Fallback to SettingsRegistry
    registry = get_settings_registry(conn)
    val = registry.get(key)
    if val is not None:
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (dict, list)):
            return json.dumps(val)
        return str(val)
    return None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    with _db_lock:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()

    # Mirror into SettingsRegistry if registered
    registry = get_settings_registry(conn)
    spec = registry.get_spec(key)
    if spec is not None:
        registry.set(key, value)


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    with _db_lock:
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        conn.commit()

    registry = get_settings_registry(conn)
    if registry.get_spec(key) is not None:
        registry.reset_key(key)
