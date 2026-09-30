import json
import sqlite3
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QWidget

from wrench.storage import settings
from wrench.storage.db import run_migrations
from wrench.ui.main_window import MainWindow
from wrench.ui.tabs.tab_bar import TabContainer


class TestLazyTabConstruction:
    """Verifies that factory-based tabs are only materialised on activation."""

    def test_factory_tab_creates_placeholder(self, qapp):
        """add_tab with a callable creates a QFrame placeholder, not the real widget."""
        container = TabContainer(orientation=Qt.Vertical)
        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return QLabel("Real Widget")

        idx = container.add_tab(factory, "Lazy", tab_type="test_lazy", activate=False)

        meta = container.tab_metadata(idx)
        assert meta is not None
        assert meta.is_loaded is False
        assert isinstance(meta.widget, QFrame)
        assert meta.widget.accessibleName() == "not loaded"
        assert call_count == 0, "Factory must NOT be called before activation"

    def test_factory_called_on_activation(self, qapp):
        """set_current_index triggers ensure_loaded and invokes the factory exactly once."""
        container = TabContainer(orientation=Qt.Vertical)
        # Add a non-lazy tab first so we can switch away
        container.add_tab(QWidget(), "Eager", tab_type="eager")

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            w = QLabel("Real Content")
            w.setObjectName("real_content")
            return w

        idx = container.add_tab(factory, "Lazy", tab_type="test_lazy2", activate=False)
        assert call_count == 0

        # Activate the lazy tab
        container.set_current_index(idx)
        assert call_count == 1
        meta = container.tab_metadata(idx)
        assert meta.is_loaded is True
        assert meta.factory is None
        assert meta.widget.objectName() == "real_content"

    def test_double_activation_does_not_call_factory_again(self, qapp):
        """Switching to an already-loaded lazy tab must not invoke the factory a second time."""
        container = TabContainer(orientation=Qt.Vertical)
        container.add_tab(QWidget(), "Filler", tab_type="filler")

        call_count = 0

        def factory():
            nonlocal call_count
            call_count += 1
            return QLabel("Once")

        idx = container.add_tab(factory, "Lazy", tab_type="test_lazy3", activate=False)
        container.set_current_index(idx)
        assert call_count == 1

        # Switch away and back
        container.set_current_index(0)
        container.set_current_index(idx)
        assert call_count == 1, "Factory must be called exactly once"

    def test_ensure_loaded_returns_widget(self, qapp):
        """ensure_loaded returns the materialised widget."""
        container = TabContainer(orientation=Qt.Vertical)
        target_label = QLabel("Target")

        idx = container.add_tab(lambda: target_label, "Lazy", tab_type="el", activate=False)
        result = container.ensure_loaded(idx)
        assert result is target_label

    def test_eager_tab_not_affected(self, qapp):
        """add_tab with a QWidget directly still works as before."""
        container = TabContainer(orientation=Qt.Vertical)
        w = QWidget()
        idx = container.add_tab(w, "Eager", tab_type="eager_test")

        meta = container.tab_metadata(idx)
        assert meta.is_loaded is True
        assert meta.factory is None
        assert meta.widget is w

    def test_deduplication_works_with_lazy_tabs(self, qapp):
        """find_tab / deduplication operates on metadata without forcing load."""
        container = TabContainer(orientation=Qt.Vertical)

        idx1 = container.add_tab(
            lambda: QLabel("PR List"),
            "PRs",
            tab_type="pr_list",
            repo_path="/repo",
            activate=False,
        )
        # Attempt to add duplicate — should return existing index
        idx2 = container.add_tab(
            lambda: QLabel("PR List 2"),
            "PRs",
            tab_type="pr_list",
            repo_path="/repo",
            activate=False,
        )
        assert idx1 == idx2
        assert container.count() == 1

        meta = container.tab_metadata(idx1)
        assert meta.is_loaded is False, "Deduplication must not force-load the tab"

    def test_pinning_works_with_lazy_tabs(self, qapp):
        """Pinning/unpinning operates on metadata without forcing load."""
        container = TabContainer(orientation=Qt.Vertical)
        idx = container.add_tab(
            lambda: QLabel("Pinnable"), "Pin", tab_type="pin_test", activate=False
        )
        container.pin_tab(idx)
        meta = container.tab_metadata(idx)
        assert meta.is_pinned is True
        assert meta.is_loaded is False, "Pinning must not force-load the tab"


class TestLoadingOverlay:
    """Verifies that the loading overlay methods exist and work."""

    def test_show_and_hide_loading(self, qapp):
        container = TabContainer(orientation=Qt.Vertical)
        container.show()
        container.add_tab(QWidget(), "Tab", tab_type="test")

        # Should not raise
        container.show_loading("test-repo")
        assert not container._loading_overlay.isHidden()
        assert container._loading_overlay.isVisible()

        container.hide_loading()
        assert container._loading_overlay.isHidden()
        assert not container._loading_overlay.isVisible()


class TestSessionRestoreLazyTabs:
    """Verifies that MainWindow session restore defers construction of forge tabs."""

    def test_session_restore_restores_forge_tabs_as_lazy(self, qapp):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        run_migrations(conn)

        session_data = {
            "tabs": {
                "active_index": 0,
                "items": [
                    {"tab_type": "changes", "label": "Changes"},
                    {
                        "tab_type": "pr_list",
                        "label": "Pull Requests",
                        "repo_path": "/fake/repo",
                    },
                    {
                        "tab_type": "issues_list",
                        "label": "Issues",
                        "repo_path": "/fake/repo",
                    },
                ],
            }
        }
        settings.set_setting(conn, "ui.session_state", json.dumps(session_data))

        with patch("wrench.storage.db.get_connection", return_value=conn):
            mw = MainWindow(conn=conn)

            # Tab 0 (changes) should be loaded because active_index=0
            meta0 = mw.tab_container.tab_metadata(0)
            assert meta0.is_loaded is True

            # Tab 1 (pr_list) should NOT be loaded
            meta1 = mw.tab_container.tab_metadata(1)
            assert meta1.is_loaded is False
            assert meta1.factory is not None

            # Tab 2 (issues_list) should NOT be loaded
            meta2 = mw.tab_container.tab_metadata(2)
            assert meta2.is_loaded is False
            assert meta2.factory is not None

            # Activating tab 1 should materialise it
            mw.tab_container.set_current_index(1)
            meta1_after = mw.tab_container.tab_metadata(1)
            assert meta1_after.is_loaded is True
            assert meta1_after.factory is None

        conn.close()
