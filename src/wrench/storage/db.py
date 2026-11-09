"""Database connection management and migrations."""

import logging
import shutil
import sqlite3
import threading
from datetime import datetime
from importlib import resources

from wrench.core.paths import data_dir

logger = logging.getLogger(__name__)

_db_lock = threading.Lock()


def get_connection() -> sqlite3.Connection:
    """Open (or create) the Wrench database."""
    db_path = data_dir() / "wrench.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("SELECT 1")
    except sqlite3.DatabaseError:
        logger.error("Database file is corrupt: %s", db_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        corrupt_path = db_path.with_suffix(f".corrupt-{timestamp}")
        shutil.move(str(db_path), str(corrupt_path))
        logger.warning("Corrupt DB backed up to: %s", corrupt_path)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

    run_migrations(conn)
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations."""
    with _db_lock:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version == 0:
            schema_sql = resources.files("wrench.storage").joinpath("schema.sql").read_text()
            conn.executescript(schema_sql)
            conn.execute("PRAGMA user_version = 3")
            conn.commit()
            logger.info("Applied initial schema (version 3)")
            return

        if current_version == 1:
            conn.execute("ALTER TABLE forge_accounts ADD COLUMN tls_ca_bundle_path TEXT")
            conn.execute(
                "ALTER TABLE forge_accounts ADD COLUMN tls_insecure INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute("PRAGMA user_version = 2")
            conn.commit()
            logger.info("Applied schema migration to version 2 (TLS account policy)")
            current_version = 2

        if current_version == 2:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS global_settings (
                    key             TEXT PRIMARY KEY,
                    value_json      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repo_settings_overrides (
                    repo_path       TEXT NOT NULL,
                    key             TEXT NOT NULL,
                    value_json      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (repo_path, key)
                )
                """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings_undo_log (
                    change_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    repo_path       TEXT,
                    key             TEXT NOT NULL,
                    old_value_json  TEXT NOT NULL,
                    new_value_json  TEXT NOT NULL,
                    undone          INTEGER NOT NULL DEFAULT 0
                )
                """)
            conn.execute("PRAGMA user_version = 3")
            conn.commit()
            logger.info("Applied schema migration to version 3 (Universal settings registry)")
