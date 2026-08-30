"""Unit tests for ChangesTab with Phase 2 merge/rebase conflict banner & MERGE_MSG."""

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from wrench.core import engine
from wrench.storage import repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.tabs.changes_tab import ChangesTab


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestChangesTabConflicts:
    def test_conflict_banner_visible_on_merge_conflict(self, conflict_repo, db_conn):
        repo_registry.add_repo(db_conn, str(conflict_repo.path))
        tab = ChangesTab(db_conn)
        tab.show()
        tab._open_repo_by_path(str(conflict_repo.path))

        # Initially clean, banner hidden
        assert tab.conflict_banner.isHidden() is True

        # Trigger merge conflict
        res = engine.merge(conflict_repo, "feature")
        assert res.status == "conflict"

        tab.refresh()
        assert tab.conflict_banner.isHidden() is False
        assert "Merge conflict" in tab.conflict_label.text()
        assert tab.conflict_btn.isVisible() is True

    def test_merge_msg_prefill(self, conflict_repo, db_conn):
        repo_registry.add_repo(db_conn, str(conflict_repo.path))
        tab = ChangesTab(db_conn)
        tab.show()
        tab._open_repo_by_path(str(conflict_repo.path))

        engine.merge(conflict_repo, "feature")

        # Create MERGE_MSG in .git
        merge_msg_path = conflict_repo.path / ".git" / "MERGE_MSG"
        merge_msg_path.write_text("Merge branch 'feature'\n\nConflicts:\n\tshared.txt\n")

        tab.refresh()
        assert tab.commit_msg_input.text() == "Merge branch 'feature'"
        assert "Conflicts:" in tab.commit_desc_input.toPlainText()


class TestChangesTabSelectAll:
    def test_select_all_checkbox_tri_state_and_clicking(self, simple_repo, db_conn):
        from PySide6.QtCore import Qt

        from wrench.ui.tabs.changes_tab import FileListItemWidget

        repo_registry.add_repo(db_conn, str(simple_repo.path))
        tab = ChangesTab(db_conn)
        tab.show()
        tab._open_repo_by_path(str(simple_repo.path))

        # Add 3 uncommitted files
        (simple_repo.path / "file1.txt").write_text("1")
        (simple_repo.path / "file2.txt").write_text("2")
        (simple_repo.path / "file3.txt").write_text("3")

        tab.refresh()
        assert tab.files_list.count() == 3
        # By default all are checked
        assert tab.select_all_cb.checkState() == Qt.Checked

        # Uncheck 1 item
        w0 = tab.files_list.itemWidget(tab.files_list.item(0))
        assert isinstance(w0, FileListItemWidget)
        w0.checkbox.setChecked(False)

        # Tri-state should be PartiallyChecked
        assert tab.select_all_cb.checkState() == Qt.PartiallyChecked

        # Clicking select_all_cb while PartiallyChecked should check all
        tab.select_all_cb.click()
        assert tab.select_all_cb.checkState() == Qt.Checked
        for i in range(3):
            wi = tab.files_list.itemWidget(tab.files_list.item(i))
            assert wi.is_checked() is True

        # Clicking select_all_cb while Checked should uncheck all
        tab.select_all_cb.click()
        assert tab.select_all_cb.checkState() == Qt.Unchecked
        for i in range(3):
            wi = tab.files_list.itemWidget(tab.files_list.item(i))
            assert wi.is_checked() is False

        # Clicking select_all_cb while Unchecked should check all
        tab.select_all_cb.click()
        assert tab.select_all_cb.checkState() == Qt.Checked
        for i in range(3):
            wi = tab.files_list.itemWidget(tab.files_list.item(i))
            assert wi.is_checked() is True
