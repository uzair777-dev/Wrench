"""Unit tests for merge operations (FR-3.1, Phase 2)."""

import pytest

from wrench.core import engine
from wrench.core.exceptions import DirtyTreeError


class TestMerge:
    def test_merge_up_to_date(self, simple_repo):
        # Merge current branch into itself or ancestor -> up to date
        status = engine.get_status(simple_repo)
        res = engine.merge(simple_repo, status.current_branch)
        assert res.status == "up_to_date"

    def test_merge_dirty_tree_raises_dirty_tree_error(self, simple_repo):
        # Create uncommitted modification
        (simple_repo.path / "hello.txt").write_text("uncommitted dirty content\n")
        with pytest.raises(DirtyTreeError):
            engine.merge(simple_repo, "HEAD")

    def test_merge_conflict_returns_conflict_result(self, conflict_repo):
        res = engine.merge(conflict_repo, "feature")
        assert res.status == "conflict"
        assert "shared.txt" in res.conflicted_files

        status = engine.get_status(conflict_repo)
        assert status.has_conflicts is True
        assert status.merge_in_progress is True

    def test_merge_abort_restores_clean_state(self, conflict_repo):
        res = engine.merge(conflict_repo, "feature")
        assert res.status == "conflict"

        engine.merge_abort(conflict_repo)
        status = engine.get_status(conflict_repo)
        assert status.has_conflicts is False
        assert status.merge_in_progress is False
