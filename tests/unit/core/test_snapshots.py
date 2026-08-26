"""Unit tests for snapshots (core/snapshots.py and storage/snapshots.py)."""

import sqlite3

import pytest

from wrench.core import snapshots
from wrench.storage import repo_registry
from wrench.storage.db import run_migrations


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def registered_repo(simple_repo, db_conn):
    repo_id = repo_registry.add_repo(db_conn, str(simple_repo.path))
    return simple_repo, repo_id


class TestSnapshots:
    def test_take_snapshot_clean_repo(self, registered_repo, db_conn):
        repo, repo_id = registered_repo
        snap = snapshots.take_snapshot(
            repo,
            "commit",
            conn=db_conn,
            repo_id=repo_id,
        )
        assert snap is not None
        assert snap.trigger_type == "commit"
        assert snap.is_manual is False

        # Verify ref exists in pygit2
        ref = repo.pygit2_repo.lookup_reference(snap.ref_name)
        assert ref is not None

    def test_take_snapshot_with_dirty_worktree(self, registered_repo, db_conn):
        repo, repo_id = registered_repo
        (repo.path / "hello.txt").write_text("modified for snapshot\n")
        snap = snapshots.take_snapshot(
            repo,
            "manual",
            label="My manual backup",
            conn=db_conn,
            repo_id=repo_id,
        )
        assert snap is not None
        assert snap.is_manual is True
        assert snap.label == "My manual backup"

        # Verify restoring snapshot
        (repo.path / "hello.txt").write_text("overwritten work\n")
        snapshots.restore_snapshot(repo, snap.id, conn=db_conn)
        assert (repo.path / "hello.txt").read_text() == "modified for snapshot\n"

    def test_prune_snapshots_respects_max_count(self, registered_repo, db_conn):
        repo, repo_id = registered_repo
        for i in range(5):
            (repo.path / "hello.txt").write_text(f"change {i}\n")
            snapshots.take_snapshot(
                repo,
                "timer",
                conn=db_conn,
                repo_id=repo_id,
            )

        # Set max_count to 2
        settings = snapshots.get_snapshot_settings(repo, conn=db_conn, repo_id=repo_id)
        settings.max_count = 2
        snapshots.update_snapshot_settings(repo, settings, conn=db_conn, repo_id=repo_id)

        snapshots.prune_snapshots(repo, conn=db_conn, repo_id=repo_id)
        snaps = snapshots.list_snapshots(repo, conn=db_conn, repo_id=repo_id)
        assert len(snaps) == 2
