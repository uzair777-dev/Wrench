"""Unit tests for 3-Way MergeDialog (Phase 2)."""

import pytest
from PySide6.QtWidgets import QApplication

from wrench.core import engine
from wrench.ui.merge_tool.merge_dialog import MergeDialog


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


class TestMergeDialog:
    def test_merge_dialog_loads_conflict_versions(self, conflict_repo):
        # Trigger merge conflict
        res = engine.merge(conflict_repo, "feature")
        assert res.status == "conflict"
        assert "shared.txt" in res.conflicted_files

        dialog = MergeDialog(conflict_repo, "shared.txt", mode="merge")
        assert "base content" in dialog.base_content
        assert "main branch modification" in dialog.ours_content
        assert "feature branch modification" in dialog.theirs_content

        # Test accept ours
        dialog._accept_ours()
        assert dialog.result_edit.toPlainText() == dialog.ours_content

        # Test accept theirs
        dialog._accept_theirs()
        assert dialog.result_edit.toPlainText() == dialog.theirs_content

        # Test accept both
        dialog._accept_both()
        assert "main branch modification" in dialog.result_edit.toPlainText()
        assert "feature branch modification" in dialog.result_edit.toPlainText()

    def test_save_and_mark_resolved_stages_file(self, conflict_repo):
        engine.merge(conflict_repo, "feature")
        dialog = MergeDialog(conflict_repo, "shared.txt", mode="merge")
        dialog.result_edit.setPlainText("clean resolved content without markers\n")
        dialog._save_and_mark_resolved()

        # Check file in worktree
        assert (
            conflict_repo.path / "shared.txt"
        ).read_text() == "clean resolved content without markers\n"

        # Check status: conflict cleared for this file, staged
        status = engine.get_status(conflict_repo)
        assert any(c.path == "shared.txt" for c in status.staged)
