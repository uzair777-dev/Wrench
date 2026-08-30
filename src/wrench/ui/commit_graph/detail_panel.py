"""FR-2.3: Commit Detail Panel with file list, stats, and embedded DiffWidget."""

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
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
        self.author_date_label.setStyleSheet("color: gray;")
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

        self.files_table.blockSignals(True)
        self.files_table.setRowCount(len(self._file_stats))
        for row, stat in enumerate(self._file_stats):
            status_item = QTableWidgetItem(stat.change_type.capitalize()[:1])
            status_item.setTextAlignment(Qt.AlignCenter)
            self.files_table.setItem(row, 0, status_item)

            file_item = QTableWidgetItem(stat.path)
            self.files_table.setItem(row, 1, file_item)

            diff_stat_str = f"+{stat.additions} -{stat.deletions}"
            stat_item = QTableWidgetItem(diff_stat_str)
            stat_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.files_table.setItem(row, 2, stat_item)
        self.files_table.blockSignals(False)

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
