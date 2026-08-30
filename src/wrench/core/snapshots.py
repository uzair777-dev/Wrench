"""FR-10.x: Rolling snapshot capture, restore, and prune.

Captures working directory + index state as git dangling commit objects
referenced by refs/wrench/snapshots/{id} without modifying the active working tree.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from wrench.storage import repo_registry as storage_repo_registry
from wrench.storage import snapshots as storage_snapshots

from .engine import RepoHandle
from .write_ops import run_git


@dataclass
class Snapshot:
    id: int
    created_at: str
    trigger_type: str  # 'commit' | 'timer' | 'pre_risky_op' | 'manual'
    is_manual: bool
    label: str | None
    ref_name: str


@dataclass
class SnapshotSettings:
    trigger_on_commit: bool
    trigger_on_timer: bool
    timer_interval_minutes: int
    trigger_before_risky_op: bool
    max_count: int
    max_age_days: int | None
    untracked_capture_mode: str  # 'none' | 'capped' | 'unlimited'
    untracked_per_file_cap_mb: int
    untracked_total_cap_mb: int


def _resolve_repo_id(
    repo: RepoHandle,
    conn: sqlite3.Connection | None,
    repo_id: int | None,
) -> int | None:
    if repo_id is not None:
        return repo_id
    if conn is not None:
        try:
            row = conn.execute("SELECT id FROM repos WHERE path = ?", (str(repo.path),)).fetchone()
            if row:
                return row["id"]
            return storage_repo_registry.add_repo(conn, str(repo.path))
        except Exception:
            pass
    return None


def take_snapshot(
    repo: RepoHandle,
    trigger_type: str,
    *,
    label: str | None = None,
    conn: sqlite3.Connection | None = None,
    repo_id: int | None = None,
) -> Snapshot | None:
    """Capture a snapshot.

    Uses `git stash create` to capture working tree without touching it.
    """
    r = repo.pygit2_repo
    if r.head_is_unborn:
        return None

    # Capture commit object
    stash_result = run_git(repo.path, ["stash", "create"], check=False)
    commit_oid = stash_result.stdout.strip()
    if not commit_oid:
        # Working tree was completely clean, use HEAD
        commit_oid = str(r.head.target)

    is_manual = trigger_type == "manual"
    now_iso = datetime.now(timezone.utc).isoformat()
    resolved_repo_id = _resolve_repo_id(repo, conn, repo_id)

    if conn is not None and resolved_repo_id is not None:
        snap_id = storage_snapshots.insert_snapshot(
            conn,
            repo_id=resolved_repo_id,
            ref_name="refs/wrench/snapshots/temp",
            trigger_type=trigger_type,
            is_manual=is_manual,
            label=label,
        )
        ref_name = f"refs/wrench/snapshots/{snap_id}"
        # Update with real ref_name
        conn.execute("UPDATE snapshots SET ref_name = ? WHERE id = ?", (ref_name, snap_id))
        conn.commit()
    else:
        snap_id = int(datetime.now().timestamp() * 1000)
        ref_name = f"refs/wrench/snapshots/{snap_id}"

    # Create git reference to prevent garbage collection
    run_git(repo.path, ["update-ref", ref_name, commit_oid])

    return Snapshot(
        id=snap_id,
        created_at=now_iso,
        trigger_type=trigger_type,
        is_manual=is_manual,
        label=label,
        ref_name=ref_name,
    )


def list_snapshots(
    repo: RepoHandle,
    *,
    conn: sqlite3.Connection | None = None,
    repo_id: int | None = None,
) -> list[Snapshot]:
    """List snapshots for the given repository."""
    resolved_repo_id = _resolve_repo_id(repo, conn, repo_id)
    if conn is None or resolved_repo_id is None:
        return []

    records = storage_snapshots.list_snapshots(conn, resolved_repo_id)
    return [
        Snapshot(
            id=r.id,
            created_at=r.created_at,
            trigger_type=r.trigger_type,
            is_manual=r.is_manual,
            label=r.label,
            ref_name=r.ref_name,
        )
        for r in records
    ]


def restore_snapshot(
    repo: RepoHandle,
    snapshot_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Restore a snapshot by resetting index and working tree without moving HEAD."""
    from . import exceptions, read_ops

    status = read_ops.get_status(repo)
    if getattr(status, "merge_in_progress", False):
        raise exceptions.RepoBusyError("snapshot restore", "merge")
    if getattr(status, "rebase_in_progress", False):
        raise exceptions.RepoBusyError("snapshot restore", "rebase")

    ref_name = f"refs/wrench/snapshots/{snapshot_id}"
    run_git(repo.path, ["read-tree", "--reset", "-u", ref_name])
    repo.pygit2_repo.index.read()


def prune_snapshots(
    repo: RepoHandle,
    *,
    conn: sqlite3.Connection | None = None,
    repo_id: int | None = None,
) -> int:
    """Prune oldest non-manual snapshots when count exceeds max_count. Returns count pruned."""
    resolved_repo_id = _resolve_repo_id(repo, conn, repo_id)
    if conn is None or resolved_repo_id is None:
        return 0

    settings = get_snapshot_settings(repo, conn=conn, repo_id=resolved_repo_id)
    all_snaps = storage_snapshots.list_snapshots(conn, resolved_repo_id)

    # Filter non-manual snapshots for pruning
    auto_snaps = [s for s in all_snaps if not s.is_manual]
    pruned_count = 0
    if len(auto_snaps) > settings.max_count:
        to_prune = auto_snaps[settings.max_count :]
        for s in to_prune:
            # Delete git ref
            run_git(repo.path, ["update-ref", "-d", s.ref_name], check=False)
            storage_snapshots.delete_snapshot(conn, s.id)
            pruned_count += 1
    return pruned_count


def get_snapshot_settings(
    repo: RepoHandle,
    *,
    conn: sqlite3.Connection | None = None,
    repo_id: int | None = None,
) -> SnapshotSettings:
    resolved_repo_id = _resolve_repo_id(repo, conn, repo_id)
    if conn is None or resolved_repo_id is None:
        return SnapshotSettings(
            trigger_on_commit=True,
            trigger_on_timer=True,
            timer_interval_minutes=10,
            trigger_before_risky_op=True,
            max_count=25,
            max_age_days=None,
            untracked_capture_mode="capped",
            untracked_per_file_cap_mb=50,
            untracked_total_cap_mb=500,
        )

    rec = storage_snapshots.ensure_snapshot_settings(conn, resolved_repo_id)
    return SnapshotSettings(
        trigger_on_commit=rec.trigger_on_commit,
        trigger_on_timer=rec.trigger_on_timer,
        timer_interval_minutes=rec.timer_interval_minutes,
        trigger_before_risky_op=rec.trigger_before_risky_op,
        max_count=rec.max_count,
        max_age_days=rec.max_age_days,
        untracked_capture_mode=rec.untracked_capture_mode,
        untracked_per_file_cap_mb=rec.untracked_per_file_cap_mb,
        untracked_total_cap_mb=rec.untracked_total_cap_mb,
    )


def update_snapshot_settings(
    repo: RepoHandle,
    settings: SnapshotSettings,
    *,
    conn: sqlite3.Connection | None = None,
    repo_id: int | None = None,
) -> None:
    resolved_repo_id = _resolve_repo_id(repo, conn, repo_id)
    if conn is None or resolved_repo_id is None:
        return

    conn.execute(
        """UPDATE snapshot_settings
           SET trigger_on_commit = ?, trigger_on_timer = ?, timer_interval_minutes = ?,
               trigger_before_risky_op = ?, max_count = ?, max_age_days = ?,
               untracked_capture_mode = ?, untracked_per_file_cap_mb = ?, untracked_total_cap_mb = ?
           WHERE repo_id = ?""",
        (
            int(settings.trigger_on_commit),
            int(settings.trigger_on_timer),
            settings.timer_interval_minutes,
            int(settings.trigger_before_risky_op),
            settings.max_count,
            settings.max_age_days,
            settings.untracked_capture_mode,
            settings.untracked_per_file_cap_mb,
            settings.untracked_total_cap_mb,
            resolved_repo_id,
        ),
    )
    conn.commit()
