"""Unit tests for recovery actions execution."""

from pathlib import Path

from wrench.core.recovery.actions import (
    QuarantineUntrackedAction,
    RebuildCorruptIndexAction,
    ReleaseStaleLockAction,
)


class TestActions:
    def test_release_stale_lock_action(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        lock_file = git_dir / "index.lock"
        lock_file.write_text("lock", encoding="utf-8")

        action = ReleaseStaleLockAction(lock_path=lock_file)
        res = action.execute(tmp_path)
        assert res.success is True
        assert not lock_file.exists()

    def test_quarantine_untracked_action(self, tmp_path: Path):
        untracked = tmp_path / "clashing_file.txt"
        untracked.write_text("important local data", encoding="utf-8")

        action = QuarantineUntrackedAction(conflicting_files=["clashing_file.txt"])
        res = action.execute(tmp_path)
        assert res.success is True
        assert not untracked.exists()

        quarantine_dir = tmp_path / ".git" / "wrench-quarantine"
        assert quarantine_dir.exists()
        backups = list(quarantine_dir.glob("backup_*/clashing_file.txt"))
        assert len(backups) == 1
        assert backups[0].read_text() == "important local data"

    def test_rebuild_corrupt_index_action(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        idx_file = git_dir / "index"
        idx_file.write_text("corrupted", encoding="utf-8")

        action = RebuildCorruptIndexAction()
        # In an uninitialized repo read-tree HEAD might fail or succeed, but index is deleted
        action.execute(tmp_path)
        assert not idx_file.exists()
