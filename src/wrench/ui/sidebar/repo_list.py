"""Repo sidebar widget."""

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wrench.storage import repo_registry


class RepoSidebar(QWidget):
    repo_selected = Signal(str)  # emits repo path
    add_repo_requested = Signal()

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header_layout = QHBoxLayout()
        self.add_btn = QPushButton("+ Add Repository")
        self.add_btn.clicked.connect(self.add_repo_requested.emit)
        header_layout.addWidget(self.add_btn)
        layout.addLayout(header_layout)

        self.list_widget = QListWidget(self)
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list_widget)

        self._repo_paths: list[str] = []
        self.refresh()

    def refresh(self):
        self.list_widget.clear()
        self._repo_paths.clear()

        records = repo_registry.list_repos(self._conn)
        for rec in records:
            display = rec.display_name
            if rec.is_missing:
                display += " [missing]"
            item = QListWidgetItem(display)
            if rec.is_missing:
                item.setToolTip(f"Missing path: {rec.path}")
            self.list_widget.addItem(item)
            self._repo_paths.append(rec.path)

    def _on_row_changed(self, row: int):
        if 0 <= row < len(self._repo_paths):
            self.repo_selected.emit(self._repo_paths[row])
