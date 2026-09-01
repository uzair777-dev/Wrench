"""Unit tests for HistoryTab widget (Phase 2)."""

import pytest
from PySide6.QtWidgets import QApplication

from wrench.ui.tabs.history_tab import HistoryTab


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


class TestHistoryTab:
    def test_history_tab_empty_repo(self, empty_repo):
        tab = HistoryTab()
        tab.show()
        tab.set_repo(empty_repo)
        assert tab.empty_state_widget.isHidden() is False
        assert tab.graph_widget.isHidden() is True

    def test_history_tab_multi_commit_repo(self, multi_commit_repo):
        tab = HistoryTab()
        tab.show()
        tab.set_repo(multi_commit_repo)
        assert tab.empty_state_widget.isHidden() is True
        assert tab.graph_widget.isHidden() is False
        assert tab.graph_widget._model.rowCount() == 3

        # Detail panel populated with first commit
        assert tab.detail_panel._current_commit is not None
        assert tab.detail_panel._current_commit.message == "Third commit"

    def test_history_tab_filter_search(self, multi_commit_repo):
        tab = HistoryTab()
        tab.set_repo(multi_commit_repo)
        tab.search_input.setText("Second")
        tab._on_search_debounced()
        assert tab.graph_widget._model.rowCount() == 1
        assert tab.graph_widget._model._rows[0].commit.message == "Second commit"

    def test_graph_horizontal_scrolling_and_auto_scroll(self, multi_commit_repo):
        tab = HistoryTab()
        tab.set_repo(multi_commit_repo)
        graph = tab.graph_widget
        assert tab.graph_scrollbar is not None
        assert graph.graph_scrollbar == tab.graph_scrollbar
        assert tab.graph_scrollbar.parent() == graph

        # Set max scroll range artificially to simulate deep lane history
        graph._max_graph_scroll_x = 150
        graph.set_graph_scroll_x(40)
        assert graph._graph_scroll_x == 40
        assert tab.graph_scrollbar.value() == 40

        # Auto-scroll to outer lane 8 (node_x = 10 + 8 * 18 = 154)
        # col_width = 100, node_x = 154, screen_x = 154 - 40 = 114 > 68 (right threshold)
        # target_scroll = 154 - 50 = 104
        graph._auto_scroll_to_node(8)
        assert graph._graph_scroll_x == 104
        assert tab.graph_scrollbar.value() == 104

        # Auto-scroll back to lane 0 (node_x = 10, screen_x = 10 - 104 = -94 < 24 left threshold)
        # target_scroll = max(0, 10 - 32) = 0
        graph._auto_scroll_to_node(0)
        assert graph._graph_scroll_x == 0
        assert tab.graph_scrollbar.value() == 0

    def test_commit_table_model_tooltips(self, multi_commit_repo):
        from PySide6.QtCore import Qt

        from wrench.core.engine import Commit, RefLabel
        from wrench.ui.commit_graph.layout import GraphRow

        tab = HistoryTab()
        tab.set_repo(multi_commit_repo)
        model = tab.graph_widget._model

        # Check Column 1 message tooltip
        idx_msg = model.index(0, 1)
        tip_msg = model.data(idx_msg, Qt.ToolTipRole)
        assert "Third commit" in tip_msg

        # Check Column 2 author tooltip
        idx_author = model.index(0, 2)
        tip_author = model.data(idx_author, Qt.ToolTipRole)
        assert "@" in tip_author

        # Check Column 3 date tooltip
        idx_date = model.index(0, 3)
        tip_date = model.data(idx_date, Qt.ToolTipRole)
        assert tip_date.startswith("Committed:")

        # Check Column 4 SHA tooltip
        idx_sha = model.index(0, 4)
        tip_sha = model.data(idx_sha, Qt.ToolTipRole)
        assert tip_sha.startswith("Commit SHA:")

        # Test multi-line message with ref badges in tooltip
        multi_line_commit = Commit(
            sha="abcdef1234567890abcdef1234567890abcdef12",
            message="Feature summary\n\nDetailed commit description body.\nSecond paragraph.",
            author_name="Alice Dev",
            author_email="alice@example.com",
            author_date="2026-09-01T12:00:00Z",
            parent_shas=[],
        )

        row_with_badges = GraphRow(
            commit=multi_line_commit,
            lane_index=0,
            node_color="#e74c3c",
            active_lanes=[0],
            connectors=[],
            ref_labels=[RefLabel(name="main", kind="branch"), RefLabel(name="v1.0.0", kind="tag")],
        )
        model.set_rows([row_with_badges])

        tip_custom = model.data(model.index(0, 1), Qt.ToolTipRole)
        assert "[main]" in tip_custom
        assert "[v1.0.0]" in tip_custom
        assert "Detailed commit description body." in tip_custom

    def test_commit_table_model_user_role_and_delegate_render(self, multi_commit_repo):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtWidgets import QStyleOptionViewItem

        tab = HistoryTab()
        tab.set_repo(multi_commit_repo)
        model = tab.graph_widget._model

        # Verify Qt.UserRole returns the GraphRow object
        row_data = model.data(model.index(0, 0), Qt.UserRole)
        assert row_data is not None
        assert row_data.commit.message == "Third commit"

        # Verify delegates paint without errors
        img = QImage(300, 100, QImage.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        opt = QStyleOptionViewItem()
        opt.rect = tab.graph_widget.visualRect(model.index(0, 0))

        tab.graph_widget._graph_delegate.paint(painter, opt, model.index(0, 0))
        tab.graph_widget._ref_delegate.paint(painter, opt, model.index(0, 1))
        painter.end()

    def test_history_tab_column_and_splitter_state_persistence(self, multi_commit_repo):
        tab = HistoryTab()
        tab.set_repo(multi_commit_repo)
        tab.show()

        # Resize columns to non-default values
        header = tab.graph_widget.horizontalHeader()
        header.resizeSection(0, 180)
        header.resizeSection(1, 450)
        header.resizeSection(2, 200)

        # Save header and splitter state
        header_hex = tab.save_header_state()
        splitter_hex = tab.save_splitter_state()
        assert header_hex != ""
        assert splitter_hex != ""

        # Create a new HistoryTab instance and restore state
        tab2 = HistoryTab()
        tab2.set_repo(multi_commit_repo)
        tab2.show()
        tab2.restore_header_state(header_hex)
        tab2.restore_splitter_state(splitter_hex)

        header2 = tab2.graph_widget.horizontalHeader()
        assert header2.sectionSize(0) == 180
        assert header2.sectionSize(1) == 450
        assert header2.sectionSize(2) == 200
