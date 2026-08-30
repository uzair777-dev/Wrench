"""Unit tests for Workspace Transaction and Debris Sweeper."""

from pathlib import Path

import pytest

from wrench.core.recovery.sweeper import sweep_debris
from wrench.core.recovery.transaction import workspace_transaction


class TestTransactionAndSweeper:
    def test_transaction_auto_sweeps_temp_dir_on_error(self, tmp_path: Path):
        temp_sub = tmp_path / "temp_clone_dir"

        with pytest.raises(RuntimeError):
            with workspace_transaction(tmp_path, name="failed_op") as tx:
                temp_sub.mkdir()
                (temp_sub / "partial_file.txt").write_text("data")
                tx.register_temp_dir(temp_sub)
                raise RuntimeError("Simulated failure during clone/fetch")

        # Temp directory must be swept cleanly
        assert not temp_sub.exists()

    def test_transaction_auto_sweeps_on_success(self, tmp_path: Path):
        temp_file = tmp_path / "test.patch"
        temp_file.write_text("patch content")

        with workspace_transaction(tmp_path, name="successful_op") as tx:
            tx.register_temp_path(temp_file)

        assert not temp_file.exists()

    def test_sweep_debris(self, tmp_path: Path):
        (tmp_path / "file1.rej").write_text("reject")
        (tmp_path / "file2.orig").write_text("original")
        (tmp_path / "file3.patch").write_text("patch")
        (tmp_path / "keep_me.txt").write_text("keep")

        removed = sweep_debris(tmp_path)
        assert len(removed) == 3
        assert (tmp_path / "keep_me.txt").exists()
        assert not (tmp_path / "file1.rej").exists()
        assert not (tmp_path / "file2.orig").exists()
        assert not (tmp_path / "file3.patch").exists()
