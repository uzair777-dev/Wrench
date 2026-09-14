"""Remotes Management Dialog (FR-4.4).

Provides a modal interface for listing, adding, editing, removing, and probing
git remotes for the active repository.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle
from wrench.core.exceptions import (
    GitCommandError,
    RemoteExistsError,
    RemoteNotFoundError,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AddRemoteDialog(QDialog):
    """Dialog for adding a new remote with name and URL."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Remote")
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("e.g. origin, upstream")
        form.addRow("Remote Name:", self.name_edit)

        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("e.g. https://github.com/user/repo.git or git@...")
        form.addRow("Remote URL:", self.url_edit)

        layout.addLayout(form)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()

        if not name:
            QMessageBox.warning(self, "Invalid Name", "Remote name cannot be empty.")
            return

        if not url:
            QMessageBox.warning(self, "Invalid URL", "Remote URL cannot be empty.")
            return

        try:
            engine._validate_remote_name(name)
            engine._validate_remote_url(url)
        except GitCommandError as exc:
            QMessageBox.warning(self, "Validation Error", exc.stderr or str(exc))
            return

        self.accept()

    @classmethod
    def get_remote_data(cls, parent: QWidget | None = None) -> tuple[str, str] | None:
        dlg = cls(parent)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg.name_edit.text().strip(), dlg.url_edit.text().strip()
        return None


class RemotesDialog(QDialog):
    """Modal dialog for managing repository remotes."""

    probe_finished = Signal()

    def __init__(
        self,
        repo: RepoHandle,
        parent: QWidget | None = None,
        *,
        db_conn: sqlite3.Connection | None = None,
        auto_probe: bool = False,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._db_conn = db_conn

        self.setWindowTitle("Manage Remotes")
        self.resize(680, 360)

        self.probe_finished.connect(self._on_probe_finished)
        self._init_ui()
        self._refresh_table()

        if auto_probe:
            remotes = engine.list_remotes(self._repo, db_conn=self._db_conn)
            if any(r.is_reachable is None for r in remotes):
                self._start_probe_async()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)

        header_lbl = QLabel("Configured remotes for this repository:", self)
        main_layout.addWidget(header_lbl)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        # Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Name", "URL", "Last Fetch", "Reachability"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemSelectionChanged.connect(self._update_button_states)
        content_layout.addWidget(self.table)

        # Action buttons
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(8)

        self.add_btn = QPushButton("Add...", self)
        self.add_btn.clicked.connect(self._on_add_remote)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Edit...", self)
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._on_edit_remote)
        btn_layout.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("Remove", self)
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._on_remove_remote)
        btn_layout.addWidget(self.remove_btn)

        self.refresh_btn = QPushButton("Refresh Status", self)
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        btn_layout.addWidget(self.refresh_btn)

        btn_layout.addStretch()

        self.close_btn = QPushButton("Close", self)
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)

        content_layout.addLayout(btn_layout)
        main_layout.addLayout(content_layout)

    def _refresh_table(self) -> None:
        """Populate the table with currently configured remotes."""
        self.table.setRowCount(0)
        remotes = engine.list_remotes(self._repo, db_conn=self._db_conn)

        for remote in remotes:
            row = self.table.rowCount()
            self.table.insertRow(row)

            # Name
            name_item = QTableWidgetItem(remote.name)
            self.table.setItem(row, 0, name_item)

            # URL
            url_item = QTableWidgetItem(remote.url)
            self.table.setItem(row, 1, url_item)

            # Last Fetch
            last_fetch_text = remote.last_fetch_at if remote.last_fetch_at else "Never"
            fetch_item = QTableWidgetItem(last_fetch_text)
            self.table.setItem(row, 2, fetch_item)

            # Reachability
            reach_item = QTableWidgetItem()
            if remote.is_reachable is True:
                reach_item.setText("● Reachable")
                reach_item.setForeground(QColor("#2da44e"))
            elif remote.is_reachable is False:
                reach_item.setText("● Unreachable")
                reach_item.setForeground(QColor("#cf222e"))
            else:
                reach_item.setText("● Unknown")
                reach_item.setForeground(QColor("#6e7781"))

            self.table.setItem(row, 3, reach_item)

        self._update_button_states()

    def _update_button_states(self) -> None:
        has_selection = bool(self.table.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _get_selected_remote_name(self) -> str | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.table.item(row, 0)
        return item.text() if item else None

    def _get_selected_remote_url(self) -> str | None:
        selected = self.table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self.table.item(row, 1)
        return item.text() if item else None

    def _on_add_remote(self) -> None:
        data = AddRemoteDialog.get_remote_data(self)
        if not data:
            return
        name, url = data
        try:
            engine.add_remote(self._repo, name, url, db_conn=self._db_conn)
        except RemoteExistsError:
            QMessageBox.warning(self, "Remote Exists", f"A remote named '{name}' already exists.")
            return
        except GitCommandError as exc:
            QMessageBox.warning(self, "Error Adding Remote", exc.stderr or str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "Error Adding Remote", str(exc))
            return

        self._refresh_table()

    def _on_edit_remote(self) -> None:
        name = self._get_selected_remote_name()
        current_url = self._get_selected_remote_url() or ""
        if not name:
            return

        new_url, ok = QInputDialog.getText(
            self,
            "Edit Remote URL",
            f"New URL for '{name}':",
            text=current_url,
        )
        if not ok or not new_url.strip():
            return

        new_url = new_url.strip()
        try:
            engine.set_remote_url(self._repo, name, new_url)
        except (RemoteNotFoundError, GitCommandError) as exc:
            msg = exc.stderr if isinstance(exc, GitCommandError) else str(exc)
            QMessageBox.warning(self, "Error Updating Remote", msg)
            return
        except Exception as exc:
            QMessageBox.warning(self, "Error Updating Remote", str(exc))
            return

        self._refresh_table()

    def _on_remove_remote(self) -> None:
        name = self._get_selected_remote_name()
        if not name:
            return

        ret = QMessageBox.question(
            self,
            "Remove Remote",
            f"Are you sure you want to remove remote '{name}'?\n\n"
            "This will remove tracking branches for this remote.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        try:
            engine.remove_remote(self._repo, name)
        except (RemoteNotFoundError, GitCommandError) as exc:
            msg = exc.stderr if isinstance(exc, GitCommandError) else str(exc)
            QMessageBox.warning(self, "Error Removing Remote", msg)
            return
        except Exception as exc:
            QMessageBox.warning(self, "Error Removing Remote", str(exc))
            return

        self._refresh_table()

    def _on_refresh_clicked(self) -> None:
        self._start_probe_async()

    def _start_probe_async(self) -> None:
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Probing...")
        engine.probe_remotes_async(
            self._repo,
            db_conn=self._db_conn,
            on_complete=self.probe_finished.emit,
        )

    def _on_probe_finished(self) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh Status")
        self._refresh_table()

    def _on_refresh_status(self, checked: bool = False, *, sync: bool = True) -> None:
        """Probe reachability for all configured remotes and update table."""
        if sync:
            remotes = engine.list_remotes(self._repo, db_conn=self._db_conn)
            for remote in remotes:
                engine._probe_reachability(self._repo.path, remote.name, db_conn=self._db_conn)
            self._refresh_table()
        else:
            self._start_probe_async()
