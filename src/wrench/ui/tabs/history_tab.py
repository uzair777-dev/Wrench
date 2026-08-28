"""History Tab Component — Skeleton (ui-planning.md §4, Phase 1.5).

Provides:
- Search & filter bar (message, author, path, date range)
- Placeholder container for Phase 2 CommitGraphWidget
- Detail panel slot (hidden until Phase 2)
- Zero commits empty state (unborn branch)
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle

logger = logging.getLogger(__name__)


class HistoryTab(QWidget):
    """Skeleton History tab for Phase 1.5 (scaffolding graph and detail panel slots)."""

    commit_hovered = Signal(str)  # sha
    commit_clicked = Signal(str)  # sha

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._on_search_debounced)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # -------------------------------------------------------------
        # 1. Search & Filter Bar (§4.6)
        # -------------------------------------------------------------
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(6)

        # Search box
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(self.tr("🔍 Search commits…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_text_changed)
        filter_bar.addWidget(self.search_input, 2)

        # Author filter
        self.author_combo = QComboBox(self)
        self.author_combo.addItem(self.tr("Author: All"))
        self.author_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(self.author_combo, 1)

        # Path filter
        self.path_input = QLineEdit(self)
        self.path_input.setPlaceholderText(self.tr("Path / File…"))
        self.path_input.setClearButtonEnabled(True)
        self.path_input.textChanged.connect(self._on_search_text_changed)
        filter_bar.addWidget(self.path_input, 1)

        # Clear filters button
        self.clear_btn = QToolButton(self)
        self.clear_btn.setText("× " + self.tr("Clear"))
        self.clear_btn.clicked.connect(self.clear_filters)
        filter_bar.addWidget(self.clear_btn)

        main_layout.addLayout(filter_bar)

        # Separator line
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line)

        # -------------------------------------------------------------
        # 2. Main Content Splitter (Graph Area + Detail Panel Slot)
        # -------------------------------------------------------------
        self.content_splitter = QSplitter(Qt.Horizontal, self)
        main_layout.addWidget(self.content_splitter, 1)

        # Graph Container
        self.graph_container = QWidget(self)
        self.graph_layout = QVBoxLayout(self.graph_container)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)

        # Placeholder widget (to be replaced by CommitGraphWidget in Phase 2)
        self.graph_placeholder = QWidget(self.graph_container)
        placeholder_layout = QVBoxLayout(self.graph_placeholder)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        placeholder_layout.setSpacing(8)

        self.placeholder_title = QLabel(self.tr("Commit Graph"), self.graph_placeholder)
        self.placeholder_title.setStyleSheet("font-size: 16px; font-weight: bold; color: gray;")
        self.placeholder_title.setAlignment(Qt.AlignCenter)
        placeholder_layout.addWidget(self.placeholder_title)

        self.placeholder_sub = QLabel(
            self.tr(
                "The visual branch graph and merge visualizations will appear here in Phase 2."
            ),
            self.graph_placeholder,
        )
        self.placeholder_sub.setStyleSheet("font-size: 12px; color: #888888;")
        self.placeholder_sub.setAlignment(Qt.AlignCenter)
        placeholder_layout.addWidget(self.placeholder_sub)

        self.graph_layout.addWidget(self.graph_placeholder)
        self.content_splitter.addWidget(self.graph_container)

        # Empty state (no commits / unborn branch)
        self.empty_state_widget = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_state_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel(self.tr("No history yet"), self.empty_state_widget)
        self.empty_title.setStyleSheet("font-size: 16px; font-weight: bold; color: gray;")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_sub = QLabel(
            self.tr("Make your first commit to see the branch graph here."),
            self.empty_state_widget,
        )
        self.empty_sub.setStyleSheet("font-size: 12px; color: #888888;")
        self.empty_sub.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_sub)

        self.empty_state_widget.setVisible(False)
        self.graph_layout.addWidget(self.empty_state_widget)

        # Detail panel slot (hidden in Phase 1.5, wired in Phase 2)
        self.detail_panel_slot = QWidget(self)
        self.detail_panel_slot.setVisible(False)
        self.content_splitter.addWidget(self.detail_panel_slot)

        self.content_splitter.setStretchFactor(0, 7)
        self.content_splitter.setStretchFactor(1, 3)

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.refresh()

    def refresh(self) -> None:
        """Refreshes the history view state."""
        if not self._repo:
            self._show_no_repo_state()
            return

        try:
            status = engine.get_status(self._repo)
            is_unborn = not bool(status.head_sha)

            if is_unborn:
                self.graph_placeholder.setVisible(False)
                self.empty_state_widget.setVisible(True)
            else:
                self.empty_state_widget.setVisible(False)
                self.graph_placeholder.setVisible(True)

            self._populate_authors()
        except Exception as e:
            logger.error("Failed to refresh history tab: %s", e)

    def _show_no_repo_state(self) -> None:
        self.graph_placeholder.setVisible(False)
        self.empty_state_widget.setVisible(True)
        self.empty_title.setText(self.tr("No repository open"))
        self.empty_sub.setText(self.tr("Open or clone a repository to view history."))

    def _populate_authors(self) -> None:
        if not self._repo:
            return
        self.author_combo.blockSignals(True)
        current_selection = self.author_combo.currentText()
        self.author_combo.clear()
        self.author_combo.addItem(self.tr("Author: All"))

        try:
            commits = engine.get_log(self._repo, limit=100)
            authors = sorted({c.author for c in commits if c.author})
            for a in authors:
                self.author_combo.addItem(a)
        except Exception as e:
            logger.debug("Could not fetch authors for log filter: %s", e)

        # Restore selection
        idx = self.author_combo.findText(current_selection)
        if idx >= 0:
            self.author_combo.setCurrentIndex(idx)
        else:
            self.author_combo.setCurrentIndex(0)

        self.author_combo.blockSignals(False)

    def _on_search_text_changed(self) -> None:
        self._debounce_timer.start()

    def _on_filter_changed(self) -> None:
        self._debounce_timer.start()

    def _on_search_debounced(self) -> None:
        # Debounced trigger for Phase 2 search/filter integration
        logger.debug(
            "Filter query: search='%s', author='%s', path='%s'",
            self.search_input.text(),
            self.author_combo.currentText(),
            self.path_input.text(),
        )

    def clear_filters(self) -> None:
        self.search_input.clear()
        self.path_input.clear()
        if self.author_combo.count() > 0:
            self.author_combo.setCurrentIndex(0)
