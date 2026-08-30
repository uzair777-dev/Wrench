"""FR-4.1: Snapshots panel widget (ui-planning.md §6.4).

Displays list of point-in-time snapshots with manual creation, restoration, and pruning.
"""

from __future__ import annotations

import logging
import sqlite3

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core import snapshots
from wrench.core.engine import RepoHandle
from wrench.core.exceptions import RepoBusyError
from wrench.storage.db import get_connection

logger = logging.getLogger(__name__)


class SnapshotsPanel(QWidget):
    """Visual panel for viewing and restoring snapshots."""

    def __init__(self, conn: sqlite3.Connection | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn if conn is not None else get_connection()
        self._repo: RepoHandle | None = None
        self._snapshots_list: list[snapshots.Snapshot] = []

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Header toolbar
        tb = QHBoxLayout()
        title_lbl = QLabel(self.tr("<b>Snapshots & Backups</b>"), self)
        tb.addWidget(title_lbl)
        tb.addStretch()

        self.take_btn = QPushButton(self.tr("+ Take Manual Snapshot…"), self)
        self.take_btn.clicked.connect(self._on_take_manual_snapshot)
        tb.addWidget(self.take_btn)

        self.restore_btn = QPushButton(self.tr("Restore Selected"), self)
        self.restore_btn.clicked.connect(self._on_restore_selected)
        tb.addWidget(self.restore_btn)

        self.prune_btn = QPushButton(self.tr("Prune Old"), self)
        self.prune_btn.clicked.connect(self._on_prune)
        tb.addWidget(self.prune_btn)

        layout.addLayout(tb)

        # Snapshots Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Timestamp"),
                self.tr("Trigger"),
                self.tr("Commit SHA"),
                self.tr("Label"),
                self.tr("Type"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.refresh()

    def refresh(self) -> None:
        if not self._repo:
            self.table.setRowCount(0)
            return

        try:
            self._snapshots_list = snapshots.list_snapshots(self._repo, conn=self._conn)
        except Exception as e:
            logger.debug("Failed to list snapshots: %s", e)
            self._snapshots_list = []

        self.table.blockSignals(True)
        self.table.setRowCount(len(self._snapshots_list))
        for row, s in enumerate(self._snapshots_list):
            time_str = s.created_at[:19].replace("T", " ")
            self.table.setItem(row, 0, QTableWidgetItem(time_str))
            self.table.setItem(row, 1, QTableWidgetItem(s.trigger_type))

            sha_item = QTableWidgetItem(str(s.id))
            sha_item.setFont(QFont("Monospace", 9))
            self.table.setItem(row, 2, sha_item)

            self.table.setItem(row, 3, QTableWidgetItem(s.label or ""))
            self.table.setItem(row, 4, QTableWidgetItem("Manual" if s.is_manual else "Auto"))

        self.table.blockSignals(False)

    def _on_take_manual_snapshot(self) -> None:
        if not self._repo:
            return
        label, ok = QInputDialog.getText(
            self,
            self.tr("Take Snapshot"),
            self.tr("Enter an optional description/label for this snapshot:"),
        )
        if not ok:
            return

        try:
            snapshots.take_snapshot(
                self._repo, "manual", label=label.strip() or None, conn=self._conn
            )
            self.refresh()
        except Exception as e:
            logger.exception("Failed to take manual snapshot: %s", e)
            QMessageBox.critical(
                self, self.tr("Snapshot Error"), f"Could not create snapshot:\n{e}"
            )

    def _on_restore_selected(self) -> None:
        if not self._repo:
            return
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            QMessageBox.information(
                self, self.tr("No Selection"), self.tr("Please select a snapshot to restore.")
            )
            return

        row = selected[0].row()
        if not (0 <= row < len(self._snapshots_list)):
            return

        target_snap = self._snapshots_list[row]
        reply = QMessageBox.warning(
            self,
            self.tr("Restore Snapshot"),
            self.tr(
                "Restoring this snapshot will reset your index and working tree "
                f"to the snapshot state from {target_snap.created_at}.\n\n"
                "Your branch history and HEAD will not be altered.\n\n"
                "Are you sure you want to proceed?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        try:
            snapshots.restore_snapshot(self._repo, target_snap.id, conn=self._conn)
            QMessageBox.information(
                self, self.tr("Restored"), self.tr("Snapshot restored successfully.")
            )
        except RepoBusyError as e:
            QMessageBox.critical(
                self,
                self.tr("Cannot Restore Snapshot"),
                self.tr(
                    f"The repository is currently in the middle of an operation ({e.state}). "
                    "Please complete or abort it first."
                ),
            )

        except Exception as e:
            logger.exception("Failed to restore snapshot: %s", e)
            QMessageBox.critical(
                self, self.tr("Restore Error"), f"Could not restore snapshot:\n{e}"
            )

    def _on_prune(self) -> None:
        if not self._repo:
            return
        try:
            pruned_count = snapshots.prune_snapshots(self._repo, conn=self._conn)
            self.refresh()
            QMessageBox.information(
                self,
                self.tr("Snapshots Pruned"),
                self.tr(f"Pruned {pruned_count} old snapshot(s) according to retention policy."),
            )
        except Exception as e:
            logger.exception("Failed to prune snapshots: %s", e)
            QMessageBox.critical(self, self.tr("Prune Error"), f"Could not prune snapshots:\n{e}")
