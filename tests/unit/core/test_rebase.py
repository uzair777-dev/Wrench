"""Unit tests for non-interactive rebase operations (FR-3.3, Phase 2)."""

import pytest

from wrench.core import engine
from wrench.core.exceptions import DirtyTreeError


class TestRebase:
    def test_rebase_clean_complete(self, multi_commit_repo):
        # Create a branch and rebase onto main
        engine.create_branch(multi_commit_repo, "feat_clean")
        engine.switch_branch(multi_commit_repo, "feat_clean")
        res = engine.rebase(multi_commit_repo, "main")
        assert res.status == "complete"

    def test_rebase_dirty_tree_raises_error(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("dirty\n")
        with pytest.raises(DirtyTreeError):
            engine.rebase(simple_repo, "HEAD")

    def test_rebase_conflict_and_abort(self, conflict_repo):
        # Switch to feature and rebase onto main
        engine.switch_branch(conflict_repo, "feature")
        res = engine.rebase(conflict_repo, "main")
        assert res.status == "conflict"
        assert "shared.txt" in res.conflicted_files

        status = engine.get_status(conflict_repo)
        assert status.rebase_in_progress is True

        engine.rebase_abort(conflict_repo)
        status_after = engine.get_status(conflict_repo)
        assert status_after.rebase_in_progress is False
