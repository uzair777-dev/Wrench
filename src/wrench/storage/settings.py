"""App-level and per-repo settings CRUD with backward-compatible delegation to SettingsRegistry."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import _db_lock
from .settings_registry import (
    _LEGACY_KEY_ALIASES,
    _SESSION_BLOB_KEYS,
    get_settings_registry,
)


def _format_registry_val(key: str, val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    text = str(val)
    if key == "theme" and text.strip().lower() == "system":
        return "auto"
    return text


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    if key in _SESSION_BLOB_KEYS:
        with _db_lock:
            row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
            if row:
                return row["value"] if isinstance(row, sqlite3.Row) else row[0]
            return None

    canon_key = _LEGACY_KEY_ALIASES.get(key, key)
    registry = get_settings_registry(conn)
    if registry.has_explicit_setting(canon_key):
        return _format_registry_val(key, registry.get(canon_key))

    with _db_lock:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row is None and canon_key != key:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (canon_key,)
            ).fetchone()
        if row:
            raw = row["value"] if isinstance(row, sqlite3.Row) else row[0]
            if key == "theme" and str(raw).strip().lower() == "system":
                return "auto"
            return raw

    if key in _LEGACY_KEY_ALIASES or registry.get_spec(key) is None:
        return None
    return _format_registry_val(key, registry.get(canon_key))


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if key in _SESSION_BLOB_KEYS:
        with _db_lock:
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
        return

    canon_key = _LEGACY_KEY_ALIASES.get(key, key)
    registry = get_settings_registry(conn)
    if registry.get_spec(canon_key) is not None:
        registry.set(canon_key, value)
        return

    with _db_lock:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()


def delete_setting(conn: sqlite3.Connection, key: str) -> None:
    canon_key = _LEGACY_KEY_ALIASES.get(key, key)
    with _db_lock:
        if key not in _SESSION_BLOB_KEYS and canon_key != key:
            conn.execute(
                "DELETE FROM app_settings WHERE key IN (?, ?)",
                (key, canon_key),
            )
        else:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        conn.commit()

    if key in _SESSION_BLOB_KEYS:
        return

    registry = get_settings_registry(conn)
    if registry.get_spec(canon_key) is not None and registry.has_explicit_setting(canon_key):
        registry.reset_key(canon_key)
