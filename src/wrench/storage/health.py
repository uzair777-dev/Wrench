"""Database integrity health checks, repair, and snapshot garbage collection."""

from __future__ import annotations

import logging
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .db import run_migrations

logger = logging.getLogger(__name__)


def check_database_health(conn: sqlite3.Connection) -> dict[str, Any]:
    """Execute SQLite integrity and foreign key checks.

    Returns dictionary containing status and diagnostic messages.
    """
    try:
        integrity_rows = conn.execute("PRAGMA integrity_check").fetchall()
        integrity_ok = len(integrity_rows) == 1 and integrity_rows[0][0] == "ok"

        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        fk_ok = len(fk_rows) == 0

        status = "ok" if (integrity_ok and fk_ok) else "corrupt"
        return {
            "status": status,
            "integrity_ok": integrity_ok,
            "integrity_messages": [r[0] for r in integrity_rows],
            "fk_ok": fk_ok,
            "fk_violations": [dict(r) for r in fk_rows],
        }
    except Exception as e:
        logger.error("Database health check error: %s", e)
        return {
            "status": "corrupt",
            "integrity_ok": False,
            "error": str(e),
        }


def repair_database(db_path: Path | str) -> sqlite3.Connection:
    """Backup corrupted database and generate fresh schema."""
    p = Path(db_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    corrupt_backup = p.with_suffix(f".corrupt-{timestamp}")

    if p.exists():
        try:
            shutil.move(str(p), str(corrupt_backup))
            logger.warning("Backed up corrupted database to: %s", corrupt_backup)
        except Exception as e:
            logger.error("Failed to backup corrupt db %s: %s", p, e)

    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    run_migrations(conn)
    return conn


def garbage_collect_snapshots(repo_path: Path | str, conn: sqlite3.Connection) -> int:
    """Prune orphaned or dangling snapshot references from Git repository and database.

    Returns:
        Number of dangling references removed.
    """
    p = Path(repo_path)
    git_dir = p / ".git" if (p / ".git").is_dir() else p
    if not git_dir.exists():
        return 0

    try:
        import pygit2

        pygit_repo = pygit2.Repository(str(git_dir))
    except Exception:
        return 0

    pruned = 0
    snapshot_refs = [
        ref_name
        for ref_name in pygit_repo.references
        if ref_name.startswith("refs/wrench/snapshots/")
    ]

    for ref_name in snapshot_refs:
        try:
            ref = pygit_repo.references[ref_name]
            target_oid = ref.target
            # Check if target commit exists
            if target_oid not in pygit_repo:
                del pygit_repo.references[ref_name]
                pruned += 1
        except Exception as e:
            logger.debug("Error checking snapshot ref %s: %s", ref_name, e)

    return pruned
