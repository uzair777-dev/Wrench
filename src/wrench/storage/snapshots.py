"""FR-10.x: CRUD for snapshot and snapshot_settings tables."""

import sqlite3
from dataclasses import dataclass

from .db import _db_lock


@dataclass
class SnapshotRecord:
    id: int
    repo_id: int
    ref_name: str
    trigger_type: str  # 'commit' | 'timer' | 'pre_risky_op' | 'manual'
    is_manual: bool
    label: str | None
    created_at: str
    untracked_archive_path: str | None


@dataclass
class SnapshotSettingsRecord:
    repo_id: int
    trigger_on_commit: bool
    trigger_on_timer: bool
    timer_interval_minutes: int
    trigger_before_risky_op: bool
    max_count: int
    max_age_days: int | None
    untracked_capture_mode: str
    untracked_per_file_cap_mb: int
    untracked_total_cap_mb: int


def insert_snapshot(
    conn: sqlite3.Connection,
    *,
    repo_id: int,
    ref_name: str,
    trigger_type: str,
    is_manual: bool = False,
    label: str | None = None,
    untracked_archive_path: str | None = None,
) -> int:
    with _db_lock:
        cursor = conn.execute(
            """INSERT INTO snapshots
               (repo_id, ref_name, trigger_type, is_manual, label, untracked_archive_path)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (repo_id, ref_name, trigger_type, int(is_manual), label, untracked_archive_path),
        )
        conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]


def list_snapshots(conn: sqlite3.Connection, repo_id: int) -> list[SnapshotRecord]:
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM snapshots WHERE repo_id = ? ORDER BY created_at DESC",
            (repo_id,),
        ).fetchall()
        return [
            SnapshotRecord(
                id=r["id"],
                repo_id=r["repo_id"],
                ref_name=r["ref_name"],
                trigger_type=r["trigger_type"],
                is_manual=bool(r["is_manual"]),
                label=r["label"],
                created_at=r["created_at"],
                untracked_archive_path=r["untracked_archive_path"],
            )
            for r in rows
        ]


def delete_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> None:
    with _db_lock:
        conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        conn.commit()


def get_snapshot_settings(conn: sqlite3.Connection, repo_id: int) -> SnapshotSettingsRecord | None:
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM snapshot_settings WHERE repo_id = ?", (repo_id,)
        ).fetchone()
        if row is None:
            return None
        return SnapshotSettingsRecord(
            repo_id=row["repo_id"],
            trigger_on_commit=bool(row["trigger_on_commit"]),
            trigger_on_timer=bool(row["trigger_on_timer"]),
            timer_interval_minutes=row["timer_interval_minutes"],
            trigger_before_risky_op=bool(row["trigger_before_risky_op"]),
            max_count=row["max_count"],
            max_age_days=row["max_age_days"],
            untracked_capture_mode=row["untracked_capture_mode"],
            untracked_per_file_cap_mb=row["untracked_per_file_cap_mb"],
            untracked_total_cap_mb=row["untracked_total_cap_mb"],
        )


def ensure_snapshot_settings(conn: sqlite3.Connection, repo_id: int) -> SnapshotSettingsRecord:
    settings = get_snapshot_settings(conn, repo_id)
    if settings:
        return settings

    with _db_lock:
        conn.execute(
            "INSERT OR IGNORE INTO snapshot_settings (repo_id) VALUES (?)",
            (repo_id,),
        )
        conn.commit()

    return get_snapshot_settings(conn, repo_id)  # type: ignore[return-value]
