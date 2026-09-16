"""History Tab Component (ui-planning.md §4, Phase 2).

Provides:
- Search & filter bar (message, author, path, date range, all branches toggle)
- Visual branch graph (CommitGraphWidget) with custom bezier connectors
- Accessible fallback list mode
- Commit detail panel (CommitDetailPanel) with file list, stats, and diff viewer
- Zero commits empty state (unborn branch)
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollBar,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, LogFilter, RepoHandle
from wrench.ui.commit_graph.detail_panel import CommitDetailPanel
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget

logger = logging.getLogger(__name__)


class HistoryTab(QWidget):
    """Full Phase 2 History tab with CommitGraphWidget, Search/Filter, and Detail Panel."""

    commit_hovered = Signal(str)  # sha
    commit_clicked = Signal(str)  # sha
    rebase_requested = Signal(str)
    merge_requested = Signal(str)
    create_branch_requested = Signal(str)
    create_tag_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(300)
        self._debounce_timer.timeout.connect(self._on_search_debounced)

        self._init_ui()

    @property
    def graph_scrollbar(self) -> QScrollBar:
        """Accesses the graph horizontal scrollbar from the graph widget."""
        return self.graph_widget.graph_scrollbar

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

        # All branches checkbox
        self.all_branches_cb = QCheckBox(self.tr("All branches"), self)
        self.all_branches_cb.setChecked(True)
        self.all_branches_cb.toggled.connect(self._on_all_branches_toggled)
        filter_bar.addWidget(self.all_branches_cb)

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
        # 2. Main Content Splitter (Vertical: Graph on top, Detail on bottom)
        # -------------------------------------------------------------
        self.content_splitter = QSplitter(Qt.Vertical, self)
        main_layout.addWidget(self.content_splitter, 1)

        # Graph Container
        self.graph_container = QWidget(self)
        self.graph_layout = QVBoxLayout(self.graph_container)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)

        # Commit Graph Widget
        self.graph_widget = CommitGraphWidget(self.graph_container)
        self.graph_placeholder = self.graph_widget  # Backwards-compatible alias
        self.graph_widget.commit_selected.connect(self._on_commit_selected)
        self.graph_widget.rebase_requested.connect(self.rebase_requested)
        self.graph_widget.merge_requested.connect(self.merge_requested)
        self.graph_widget.create_branch_requested.connect(self.create_branch_requested)
        self.graph_widget.create_tag_requested.connect(self.create_tag_requested)
        self.graph_layout.addWidget(self.graph_widget)

        # Empty state (no commits / unborn branch)
        self.empty_state_widget = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_state_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(8)

        self.empty_title = QLabel(self.tr("No history yet"), self.empty_state_widget)
        self.empty_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: palette(placeholder-text);"
        )
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_title)

        self.empty_sub = QLabel(
            self.tr("Make your first commit to see the branch graph here."),
            self.empty_state_widget,
        )
        self.empty_sub.setStyleSheet("font-size: 12px; color: palette(placeholder-text);")
        self.empty_sub.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_sub)

        self.empty_state_widget.setVisible(False)
        self.graph_layout.addWidget(self.empty_state_widget)

        self.content_splitter.addWidget(self.graph_container)

        # Detail panel
        self.detail_panel = CommitDetailPanel(self)
        self.content_splitter.addWidget(self.detail_panel)

        self.content_splitter.setStretchFactor(0, 3)
        self.content_splitter.setStretchFactor(1, 2)

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.detail_panel.set_repo(repo)
        self.refresh()

    def refresh(self) -> None:
        """Refreshes the history view state."""
        if not self._repo:
            self._show_no_repo_state()
            return

        try:
            is_unborn = self._repo.pygit2_repo.head_is_unborn
            if is_unborn:
                self.graph_widget.setVisible(False)
                self.empty_state_widget.setVisible(True)
                self.detail_panel.set_commit(None)
            else:
                self.empty_state_widget.setVisible(False)
                self.graph_widget.setVisible(True)
                self.graph_widget.set_repo(self._repo)

            self._populate_authors()
        except Exception as e:
            logger.error("Failed to refresh history tab: %s", e)

    def _show_no_repo_state(self) -> None:
        self.graph_widget.setVisible(False)
        self.empty_state_widget.setVisible(True)
        self.empty_title.setText(self.tr("No repository open"))
        self.empty_sub.setText(self.tr("Open or clone a repository to view history."))
        self.detail_panel.set_commit(None)

    def _populate_authors(self) -> None:
        if not self._repo:
            return
        self.author_combo.blockSignals(True)
        current_selection = self.author_combo.currentText()
        self.author_combo.clear()
        self.author_combo.addItem(self.tr("Author: All"))

        try:
            commits = self.graph_widget._all_commits
            if not commits:
                commits = engine.get_log(self._repo, limit=50, all_refs=True)
            authors = sorted({c.author_name for c in commits if c.author_name})
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

    def _on_all_branches_toggled(self, checked: bool) -> None:
        self.graph_widget.set_all_refs_mode(checked)

    def _on_commit_selected(self, commit: Commit | None) -> None:
        self.detail_panel.set_commit(commit)
        if commit:
            self.commit_clicked.emit(commit.sha)

    def _on_search_debounced(self) -> None:
        search_text = self.search_input.text().strip()
        author_text = self.author_combo.currentText()
        author = author_text if author_text != self.tr("Author: All") else ""
        path = self.path_input.text().strip()

        log_filter = LogFilter(
            message_substring=search_text or None,
            author=author or None,
            path=path or None,
        )
        self.graph_widget.apply_filter(log_filter)

    def clear_filters(self) -> None:
        self.search_input.clear()
        self.path_input.clear()
        if self.author_combo.count() > 0:
            self.author_combo.setCurrentIndex(0)
        self.all_branches_cb.setChecked(True)
        self.graph_widget.apply_filter(None)

    def save_header_state(self) -> str:
        """Exports commit graph column sizes and header state as hex string."""
        return self.graph_widget.horizontalHeader().saveState().toHex().data().decode("utf-8")

    def restore_header_state(self, hex_str: str) -> None:
        """Restores commit graph column sizes and header state from hex string."""
        if hex_str:
            try:
                byte_array = QByteArray.fromHex(hex_str.encode("utf-8"))
                self.graph_widget.horizontalHeader().restoreState(byte_array)
                self.graph_widget._update_scrollbar_range()
                self.graph_widget._update_graph_scrollbar_geom()
            except Exception as e:
                logger.warning("Could not restore history table header state: %s", e)

    def save_splitter_state(self) -> str:
        """Exports history content splitter position as hex string."""
        return self.content_splitter.saveState().toHex().data().decode("utf-8")

    def restore_splitter_state(self, hex_str: str) -> None:
        """Restores history content splitter position from hex string."""
        if hex_str:
            try:
                byte_array = QByteArray.fromHex(hex_str.encode("utf-8"))
                self.content_splitter.restoreState(byte_array)
            except Exception as e:
                logger.warning("Could not restore history splitter state: %s", e)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if getattr(self, "_refreshing_theme", False):
            return
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self._refreshing_theme = True
            try:
                self.refresh_theme()
            finally:
                self._refreshing_theme = False

    def refresh_theme(self) -> None:
        """Propagates theme change to detail panel, graph, and empty-state labels."""
        if hasattr(self, "detail_panel"):
            self.detail_panel.refresh_theme()
        if hasattr(self, "graph_widget"):
            self.graph_widget.viewport().update()
        if hasattr(self, "empty_title"):
            self.empty_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: palette(placeholder-text);"
            )
        if hasattr(self, "empty_sub"):
            self.empty_sub.setStyleSheet("font-size: 12px; color: palette(placeholder-text);")
