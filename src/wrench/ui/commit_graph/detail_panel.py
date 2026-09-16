"""FR-2.3: Commit Detail Panel with file list, stats, and embedded DiffWidget."""

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, FileStat, RepoHandle
from wrench.ui.diff_view.diff_widget import DiffWidget
from wrench.ui.theme import COMMIT_STAT_COLORS, get_badge_colors, is_dark_theme

logger = logging.getLogger(__name__)


class CommitDetailPanel(QWidget):
    """Bottom split panel showing metadata, modified files, and read-only diff for a commit."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_commit: Commit | None = None
        self._file_stats: list[FileStat] = []

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Header section (Metadata + Copy SHA)
        header_widget = QWidget(self)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(2)

        meta_top = QHBoxLayout()
        self.sha_label = QLabel("SHA: -", self)
        self.sha_label.setFont(QFont("Monospace", 9))
        self.sha_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta_top.addWidget(self.sha_label)

        self.copy_sha_btn = QPushButton("Copy SHA", self)
        self.copy_sha_btn.setFixedHeight(22)
        self.copy_sha_btn.clicked.connect(self._copy_sha)
        meta_top.addWidget(self.copy_sha_btn)

        meta_top.addStretch()

        self.author_date_label = QLabel("-", self)
        self.author_date_label.setStyleSheet("color: palette(placeholder-text);")
        meta_top.addWidget(self.author_date_label)

        header_layout.addLayout(meta_top)

        self.message_edit = QTextEdit(self)
        self.message_edit.setReadOnly(True)
        self.message_edit.setMaximumHeight(60)
        self.message_edit.setPlaceholderText("Commit message...")
        header_layout.addWidget(self.message_edit)

        main_layout.addWidget(header_widget)

        # Splitter: File list on left, DiffWidget on right
        self.splitter = QSplitter(Qt.Horizontal, self)

        # File list table
        self.files_table = QTableWidget(self)
        self.files_table.setColumnCount(3)
        self.files_table.setHorizontalHeaderLabels(["Status", "File", "+/-"])
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.files_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.files_table.setSelectionMode(QTableWidget.SingleSelection)
        self.files_table.itemSelectionChanged.connect(self._on_file_selected)
        self.splitter.addWidget(self.files_table)

        # DiffWidget
        self.diff_widget = DiffWidget(self)
        self.splitter.addWidget(self.diff_widget)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        main_layout.addWidget(self.splitter)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self.refresh_theme()

    def refresh_theme(self) -> None:
        """Refreshes diff widget, table item styling, and header labels on theme change."""
        self.diff_widget.refresh_theme()
        if hasattr(self, "author_date_label"):
            self.author_date_label.setStyleSheet("color: palette(placeholder-text);")
        if self._file_stats:
            self._populate_files_table()

    def _populate_files_table(self):
        is_dark = is_dark_theme(self)
        mode = "dark" if is_dark else "light"
        add_col = COMMIT_STAT_COLORS[mode]["add"]
        del_col = COMMIT_STAT_COLORS[mode]["del"]

        self.files_table.blockSignals(True)
        self.files_table.setRowCount(len(self._file_stats))
        for row, stat in enumerate(self._file_stats):
            code = stat.change_type.capitalize()[:1]
            status_item = QTableWidgetItem(code)
            status_item.setTextAlignment(Qt.AlignCenter)
            fg, _ = get_badge_colors(code, is_dark=is_dark)
            status_item.setForeground(QColor(fg))
            status_font = status_item.font()
            status_font.setBold(True)
            status_item.setFont(status_font)
            self.files_table.setItem(row, 0, status_item)

            file_item = QTableWidgetItem(stat.path)
            self.files_table.setItem(row, 1, file_item)

            stat_widget = QWidget(self.files_table)
            stat_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            stat_layout = QHBoxLayout(stat_widget)
            stat_layout.setContentsMargins(4, 1, 4, 1)
            stat_layout.setSpacing(6)
            stat_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            add_lbl = QLabel(f"+{stat.additions}", stat_widget)
            add_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            add_lbl.setStyleSheet(f"color: {add_col}; font-weight: bold; font-size: 11px;")
            stat_layout.addWidget(add_lbl)

            del_lbl = QLabel(f"-{stat.deletions}", stat_widget)
            del_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            del_lbl.setStyleSheet(f"color: {del_col}; font-weight: bold; font-size: 11px;")
            stat_layout.addWidget(del_lbl)

            self.files_table.setCellWidget(row, 2, stat_widget)
        self.files_table.blockSignals(False)

    def set_repo(self, repo: RepoHandle | None):
        self._repo = repo
        self.diff_widget.set_repo(repo)

    def set_commit(self, commit: Commit | None):
        self._current_commit = commit
        if not commit or not self._repo:
            self.sha_label.setText("SHA: -")
            self.author_date_label.setText("-")
            self.message_edit.clear()
            self.files_table.setRowCount(0)
            self.diff_widget.set_diff_model(
                engine.Diff(path="", is_binary=False, hunks=[]), title="No commit selected"
            )
            return

        self.sha_label.setText(f"SHA: {commit.sha[:8]} ({commit.sha})")
        self.author_date_label.setText(
            f"{commit.author_name} <{commit.author_email}> on {commit.author_date}"
        )
        self.message_edit.setPlainText(commit.message)

        # Load file stats
        try:
            self._file_stats = engine.get_commit_file_stats(self._repo, commit.sha)
        except Exception as e:
            logger.exception("Failed to load file stats for %s: %s", commit.sha, e)
            self._file_stats = []

        self._populate_files_table()

        if self._file_stats:
            self.files_table.selectRow(0)
            self._load_file_diff(self._file_stats[0].path)
        else:
            self.diff_widget.set_diff_model(
                engine.Diff(path="", is_binary=False, hunks=[]), title="No file changes"
            )

    def _copy_sha(self):
        if self._current_commit:
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(self._current_commit.sha)

    def _on_file_selected(self):
        selected_rows = self.files_table.selectionModel().selectedRows()
        if not selected_rows or not self._current_commit or not self._repo:
            return
        row = selected_rows[0].row()
        if 0 <= row < len(self._file_stats):
            path = self._file_stats[row].path
            self._load_file_diff(path)

    def _load_file_diff(self, path: str):
        if not self._repo or not self._current_commit:
            return
        try:
            diff = engine.get_commit_diff(self._repo, self._current_commit.sha, path=path)
            self.diff_widget.set_diff_model(diff, title=f"Commit Diff: {path}", read_only=True)
        except Exception as e:
            logger.exception("Failed to load commit diff for %s: %s", path, e)
