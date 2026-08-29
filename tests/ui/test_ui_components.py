"""UI component tests for TabContainer, ChangesTab, HistoryTab,
BranchSwitcherWidget, and MainWindow.
"""

import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from wrench.storage import repo_registry
from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow
from wrench.ui.tabs.changes_tab import ChangesTab
from wrench.ui.tabs.history_tab import HistoryTab
from wrench.ui.tabs.tab_bar import TabContainer
from wrench.ui.widgets.branch_switcher import BranchSwitcherWidget


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    yield conn
    conn.close()


class TestTabContainer:
    def test_pinned_and_closable_tabs(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)

        w1 = QWidget()
        w2 = QWidget()
        container.add_tab(w1, "Changes", tab_type="changes", closable=False)
        container.add_tab(w2, "History", tab_type="history", closable=True)

        assert container.count() == 2
        assert container.current_index() == 1  # Last added tab becomes active

        # Pinned tab (index 0) cannot be removed
        container.remove_tab(0)
        assert container.count() == 2

        # Closable tab (index 1) can be removed
        container.remove_tab(1)
        assert container.count() == 1
        assert container.current_index() == 0

    def test_pin_and_unpin_tab(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)
        w1 = QWidget()
        w2 = QWidget()

        container.add_tab(w1, "Tab 1", closable=True)
        container.add_tab(w2, "Tab 2", closable=True)

        # Pin Tab 2
        container.pin_tab(1)
        meta = container.tab_metadata(1)
        assert meta.is_pinned is True
        assert meta.closable is False

        # Attempt to close pinned tab fails
        container.remove_tab(1)
        assert container.count() == 2

        # Unpin Tab 2
        container.unpin_tab(1)
        meta = container.tab_metadata(1)
        assert meta.is_pinned is False
        assert meta.closable is True

        # Now closing succeeds
        container.remove_tab(1)
        assert container.count() == 1

    def test_close_other_and_right_tabs(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)
        w1 = QWidget()
        w2 = QWidget()
        w3 = QWidget()
        w4 = QWidget()

        container.add_tab(w1, "Tab 1", closable=True)
        container.add_tab(w2, "Tab 2", closable=True)
        container.add_tab(w3, "Tab 3", closable=True)
        container.add_tab(w4, "Tab 4", closable=True)

        # Close tabs to the right of index 1 (closes Tab 3, Tab 4)
        container.close_tabs_to_right(1)
        assert container.count() == 2

        # Add two more tabs
        w5 = QWidget()
        w6 = QWidget()
        container.add_tab(w5, "Tab 5", closable=True)
        container.add_tab(w6, "Tab 6", closable=True)
        assert container.count() == 4

        # Close others keeping index 2
        container.close_other_tabs(2)
        assert container.count() == 1
        assert container.tab_metadata(0).label == "Tab 5"

    def test_deduplication_rule(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)

        w1 = QWidget()
        w2 = QWidget()
        w3 = QWidget()

        idx1 = container.add_tab(
            w1, "PR #42", tab_type="pr_detail", repo_path="/repo/a", entity_id="42"
        )
        assert container.count() == 1

        # Adding same entity_id for same repo focuses existing tab
        idx2 = container.add_tab(
            w2, "PR #42 (dup)", tab_type="pr_detail", repo_path="/repo/a", entity_id="42"
        )
        assert container.count() == 1
        assert idx2 == idx1

        # Adding different entity_id opens a new tab
        idx3 = container.add_tab(
            w3, "PR #43", tab_type="pr_detail", repo_path="/repo/a", entity_id="43"
        )
        assert container.count() == 2
        assert idx3 == 1

    def test_orientation_toggle(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)
        assert container.orientation() == Qt.Vertical

        container.set_orientation(Qt.Horizontal)
        assert container.orientation() == Qt.Horizontal


class TestBranchSwitcherWidget:
    def test_branch_display(self, simple_repo, qapp):
        widget = BranchSwitcherWidget()
        widget.set_repo(simple_repo)

        assert "main" in widget.btn.text() or "master" in widget.btn.text()
        assert widget.btn.isEnabled()


class TestChangesTab:
    def test_changes_tab_repo_dropdown(self, simple_repo, tmp_path, db_conn, qapp):
        from wrench.core import engine

        repo2_path = tmp_path / "repo2"
        engine.init_repo(repo2_path)

        repo_registry.add_repo(db_conn, str(simple_repo.path), "Simple")
        repo_registry.add_repo(db_conn, str(repo2_path), "Repo2")

        tab = ChangesTab(db_conn)
        tab.load_repos()

        assert tab.repo_combo.count() == 2

    def test_commit_button_enabling(self, simple_repo, db_conn, qapp):
        tab = ChangesTab(db_conn)
        tab.set_repo(simple_repo)

        # Initially no changes, commit button disabled
        assert not tab.commit_btn.isEnabled()

        # Add an uncommitted file
        (simple_repo.path / "file.txt").write_text("content")
        tab.refresh()

        # Message is empty, should still be disabled
        assert not tab.commit_btn.isEnabled()

        # Type message
        tab.commit_msg_input.setText("Initial work")
        assert tab.commit_btn.isEnabled()


class TestHistoryTab:
    def test_history_tab_renders_and_handles_repo(self, simple_repo, qapp):
        tab = HistoryTab()
        tab.set_repo(simple_repo)

        assert tab.search_input is not None
        assert tab.graph_placeholder is not None
        assert not tab.empty_state_widget.isVisible()


class TestMainWindow:
    def test_main_window_initialization(self, db_conn, simple_repo, qapp):
        repo_registry.add_repo(db_conn, str(simple_repo.path), "Simple")
        window = MainWindow(conn=db_conn)
        window.show()

        assert window.tab_container is not None
        assert window.changes_tab is not None
        assert window.history_tab is not None
        assert window.tab_container.count() >= 2
        assert window.menuBar() is not None
        assert window.statusBar() is not None

    def test_session_state_persistence_and_restore(self, db_conn, simple_repo, monkeypatch, qapp):
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

        repo_path = str(simple_repo.path)
        repo_registry.add_repo(db_conn, repo_path, "Simple")

        window1 = MainWindow(conn=db_conn)
        window1.show()

        # Modify orientation
        window1.tab_container.set_orientation(Qt.Horizontal)

        # Pin history tab (index 1) and unpin changes tab (index 0)
        window1.tab_container.unpin_tab(0)
        window1.tab_container.pin_tab(1)

        # Set active tab to History
        window1.tab_container.set_current_index(1)

        # Set draft commit message in ChangesTab
        window1.changes_tab.commit_msg_input.setText("Persisted draft summary")
        window1.changes_tab.commit_desc_input.setPlainText("Persisted draft description")

        # Trigger save
        window1._save_session_state()
        window1.close()

        # Create new MainWindow simulating app restart
        window2 = MainWindow(conn=db_conn)
        window2.show()

        # Verify orientation
        assert window2.tab_container.orientation() == Qt.Horizontal

        # Verify tab count and pin states
        assert window2.tab_container.count() == 2
        changes_meta = window2.tab_container.tab_metadata(0)
        history_meta = window2.tab_container.tab_metadata(1)
        assert changes_meta.is_pinned is False
        assert changes_meta.closable is True
        assert history_meta.is_pinned is True
        assert history_meta.closable is False

        # Verify active tab index
        assert window2.tab_container.current_index() == 1

        # Verify draft commit text restored for the repo
        assert window2.changes_tab.commit_msg_input.text() == "Persisted draft summary"
        assert window2.changes_tab.commit_desc_input.toPlainText() == "Persisted draft description"
        window2.close()

    def test_auto_save_debounce_coalescing(self, db_conn, simple_repo, monkeypatch, qapp):
        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)

        repo_path = str(simple_repo.path)
        repo_registry.add_repo(db_conn, repo_path, "Simple")

        window = MainWindow(conn=db_conn)
        window.show()
        window._auto_save_timer.stop()

        assert not window._auto_save_timer.isActive()

        # Type text which triggers state_changed -> _schedule_auto_save
        window.changes_tab.commit_msg_input.setText("Fast typing 1")
        assert window._auto_save_timer.isActive()

        window.changes_tab.commit_msg_input.setText("Fast typing 2")
        assert window._auto_save_timer.isActive()

        window.close()

    def test_corrupt_session_state_fallback(self, db_conn, simple_repo, qapp):
        from wrench.storage import settings

        repo_registry.add_repo(db_conn, str(simple_repo.path), "Simple")
        settings.set_setting(db_conn, "ui.session_state", "{INVALID_JSON: [}")

        # Should not throw exception and should fallback gracefully
        window = MainWindow(conn=db_conn)
        window.show()

        assert window.tab_container.count() >= 2
        assert window.tab_container.orientation() == Qt.Vertical
        window.close()
