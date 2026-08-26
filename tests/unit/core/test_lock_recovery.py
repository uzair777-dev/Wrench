"""Unit tests for core/lock_recovery.py — detect and clear stale .git/index.lock."""

import os
import time

import pytest

from wrench.core import lock_recovery
from wrench.core.exceptions import StaleLockDetectedError


class TestLockRecovery:
    def test_no_lock_does_nothing(self, simple_repo):
        lock_recovery.check_lock(simple_repo.path)

    def test_stale_lock_detected_and_removed(self, simple_repo):
        lock_file = simple_repo.path / ".git" / "index.lock"
        lock_file.touch()

        # Backdate lock file mtime by 10 seconds
        stale_time = time.time() - 10
        os.utime(lock_file, (stale_time, stale_time))

        with pytest.raises(StaleLockDetectedError) as exc_info:
            lock_recovery.check_lock(simple_repo.path)

        assert str(lock_file) in str(exc_info.value)
        assert lock_file.exists()

        # Remove lock
        lock_recovery.remove_lock(simple_repo.path)
        assert not lock_file.exists()
