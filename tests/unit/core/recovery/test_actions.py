"""Unit tests for recovery actions execution."""

from pathlib import Path

from wrench.core.recovery.actions import (
    QuarantineUntrackedAction,
    RebuildCorruptIndexAction,
    ReleaseStaleLockAction,
    RunPreCommitFixAction,
    StageHookModificationsAndRetryAction,
    find_project_binary,
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

    def test_find_project_binary(self, tmp_path: Path):
        fake_bin_dir = tmp_path / ".venv" / "bin"
        fake_bin_dir.mkdir(parents=True)
        fake_black = fake_bin_dir / "black"
        fake_black.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_black.chmod(0o755)

        found = find_project_binary(tmp_path, "black")
        assert found == fake_black

    def test_stage_hook_modifications_and_retry_action(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("updated by formatter\n")
        action = StageHookModificationsAndRetryAction()
        res = action.execute(
            simple_repo.path,
            context={"message": "feat: test recovery commit"},
        )
        assert res.success is True
        assert "commit completed successfully" in res.message or "re-staged" in res.message

    def test_run_pre_commit_fix_action(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("updated by fix\n")
        action = RunPreCommitFixAction()
        res = action.execute(simple_repo.path)
        assert res.success is True
        assert "Ready to commit" in res.message
