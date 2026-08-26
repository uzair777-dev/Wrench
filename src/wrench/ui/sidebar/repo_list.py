"""Repo sidebar widget."""

import sqlite3

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class RepoSidebar(QWidget):
    repo_selected = Signal(str)
    add_repo_requested = Signal()

    def __init__(self, conn: sqlite3.Connection, parent=None):
        super().__init__(parent)
        self._conn = conn

    def refresh(self):
        pass
