"""Unit tests for Process Guard and lock contention handling."""

import os
import time
from pathlib import Path

from wrench.core.recovery.process_guard import (
    STALE_THRESHOLD_SECONDS,
    acquire_repo_guard,
    inspect_locks,
    is_pid_alive,
    remove_lock,
)


class TestProcessGuard:
    def test_is_pid_alive(self):
        # Current process PID is alive
        assert is_pid_alive(os.getpid()) is True
        # Invalid / non-existent PIDs
        assert is_pid_alive(-1) is False
        assert is_pid_alive(0) is False
        assert is_pid_alive(9999999) is False

    def test_inspect_locks_empty_repo(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        locks = inspect_locks(tmp_path)
        assert len(locks) == 0

    def test_inspect_locks_finds_index_lock(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        lock_file = git_dir / "index.lock"
        lock_file.write_text("12345", encoding="utf-8")

        locks = inspect_locks(tmp_path)
        assert len(locks) == 1
        found_path, pid, cmd, age = locks[0]
        assert found_path == lock_file
        assert pid == 12345
        assert age >= 0

    def test_acquire_repo_guard_ready_when_no_locks(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        result = acquire_repo_guard(tmp_path, timeout=0.1)
        assert result.status == "ready"

    def test_acquire_repo_guard_stale_lock_with_dead_pid(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        lock_file = git_dir / "index.lock"
        lock_file.write_text("9999999", encoding="utf-8")  # Dead PID

        # Set mtime to old
        old_time = time.time() - (STALE_THRESHOLD_SECONDS + 10)
        os.utime(lock_file, (old_time, old_time))

        result = acquire_repo_guard(tmp_path, timeout=0.1)
        assert result.status == "stale_lock"
        assert result.lock_path == lock_file

    def test_acquire_repo_guard_busy_with_live_pid(self, tmp_path: Path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir(parents=True)
        lock_file = git_dir / "index.lock"
        lock_file.write_text(str(os.getpid()), encoding="utf-8")  # Active PID

        result = acquire_repo_guard(tmp_path, timeout=0.1, poll_interval=0.05)
        assert result.status == "busy"
        assert result.pid == os.getpid()

    def test_remove_lock(self, tmp_path: Path):
        lock = tmp_path / "test.lock"
        lock.write_text("lock", encoding="utf-8")
        assert lock.exists()

        assert remove_lock(lock) is True
        assert not lock.exists()
