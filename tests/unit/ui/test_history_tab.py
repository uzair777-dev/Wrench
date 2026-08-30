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
