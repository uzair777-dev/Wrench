"""FR-10.x: Rolling snapshot capture, restore, and prune."""

from dataclasses import dataclass

from .engine import RepoHandle


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


def take_snapshot(
    repo: RepoHandle,
    trigger_type: str,
    *,
    label: str | None = None,
    conn=None,
    repo_id: int | None = None,
) -> Snapshot | None:
    raise NotImplementedError


def list_snapshots(repo: RepoHandle) -> list[Snapshot]:
    raise NotImplementedError


def restore_snapshot(repo: RepoHandle, snapshot_id: int) -> None:
    raise NotImplementedError


def prune_snapshots(repo: RepoHandle) -> None:
    raise NotImplementedError


def get_snapshot_settings(repo: RepoHandle) -> SnapshotSettings:
    raise NotImplementedError


def update_snapshot_settings(repo: RepoHandle, settings: SnapshotSettings) -> None:
    raise NotImplementedError
