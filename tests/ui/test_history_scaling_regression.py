"""Regression tests for History view horizontal scaling, column elision, and detail panel flex."""

from unittest.mock import MagicMock

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics

from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.tabs.history_tab import HistoryTab


def test_detail_panel_expands_on_window_resize(qtbot):
    """HistoryTab content splitter allows CommitDetailPanel to expand on wide displays."""
    settings = MagicMock()
    settings.is_enabled.return_value = True
    settings.get_int.return_value = 1000

    tab = HistoryTab(parent=None, settings_registry=settings)
    qtbot.addWidget(tab)
    tab.resize(1000, 600)
    tab.show()

    initial_detail_w = tab.detail_panel.width()
    initial_sizes = tab.content_splitter.sizes()
    assert len(initial_sizes) == 3

    # Resize window from 1000px to 1600px (+600px)
    tab.resize(1600, 600)
    qtbot.wait(50)

    expanded_sizes = tab.content_splitter.sizes()
    expanded_detail_w = tab.detail_panel.width()

    # Detail panel must expand and not remain frozen at a narrow fixed size
    assert expanded_detail_w > initial_detail_w or expanded_sizes[2] > initial_sizes[2]
    assert expanded_sizes[2] >= 420


def test_branch_tag_column_does_not_truncate_standard_branch_name(qtbot):
    """CommitGraphWidget allocates at least 240px to Column 0 (Branch/Tag) to prevent truncation."""
    widget = CommitGraphWidget()
    qtbot.addWidget(widget)
    widget.set_three_column_mode(True)

    header = widget.horizontalHeader()
    col0_w = header.sectionSize(0)
    assert col0_w >= 240

    font = widget.font()
    font.setPointSize(max(8, font.pointSize() - 1))
    metrics = QFontMetrics(font)

    branch_name = "origin/feature-worktree"
    avail_w = col0_w - 28
    elided = metrics.elidedText(branch_name, Qt.TextElideMode.ElideRight, avail_w)
    assert "..." not in elided
    assert elided == branch_name


def test_date_column_does_not_truncate_iso_timestamps(qtbot):
    """CommitGraphWidget gives >=155px to Column 4 (Date) so timestamps render cleanly."""
    widget = CommitGraphWidget()
    qtbot.addWidget(widget)
    widget.set_three_column_mode(True)

    header = widget.horizontalHeader()
    col4_w = header.sectionSize(4)
    assert col4_w >= 155

    date_str = "2026-11-24 17:30:45"
    metrics = QFontMetrics(widget.font())
    avail_w = col4_w - 14  # text_rect margin
    elided = metrics.elidedText(date_str, Qt.TextElideMode.ElideRight, avail_w)
    assert "..." not in elided
    assert elided == date_str


def test_graph_tree_column_accommodates_multi_lane_graphs(qtbot):
    """CommitGraphWidget allocates at least 150px to Column 1 (Graph) for neon lane rails."""
    widget = CommitGraphWidget()
    qtbot.addWidget(widget)
    widget.set_three_column_mode(True)

    header = widget.horizontalHeader()
    col1_w = header.sectionSize(1)
    assert col1_w >= 150


def test_history_tab_restore_splitter_preserves_responsive_stretch(qtbot):
    """Restoring splitter state in HistoryTab preserves [0, 3, 2] stretch factor distribution."""
    settings = MagicMock()
    settings.is_enabled.return_value = True
    settings.get_int.return_value = 1000

    tab = HistoryTab(parent=None, settings_registry=settings)
    qtbot.addWidget(tab)
    tab.resize(1200, 600)
    tab.show()

    # Save state and restore it
    state_hex = tab.content_splitter.saveState().toHex().data().decode("utf-8")
    tab.restore_splitter_state(state_hex)

    assert tab.detail_panel.minimumWidth() >= 320
    sizes = tab.content_splitter.sizes()
    assert len(sizes) == 3
    assert sizes[2] >= 320
