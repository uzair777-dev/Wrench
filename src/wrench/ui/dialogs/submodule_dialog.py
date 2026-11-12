"""Submodule management dialog for Wrench."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
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

logger = logging.getLogger(__name__)


class SubmoduleDialog(QDialog):
    """Dialog for listing, initializing, updating, and adding Git submodules."""

    submodules_changed = Signal()

    def __init__(self, repo: RepoHandle, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo = repo
        self.setWindowTitle(self.tr("Submodules"))
        self.setMinimumSize(700, 480)

        self._init_ui()
        self.refresh()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header bar with summary & Update All button
        header_layout = QHBoxLayout()
        self.title_label = QLabel(self.tr("Configured Submodules"))
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13pt;")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        self.update_all_btn = QPushButton(self.tr("Update All (Recursive)"))
        self.update_all_btn.setAccessibleName("Update all submodules recursively")
        self.update_all_btn.clicked.connect(self._on_update_all)
        header_layout.addWidget(self.update_all_btn)

        layout.addLayout(header_layout)

        # Submodules table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                self.tr("Path"),
                self.tr("URL"),
                self.tr("Commit"),
                self.tr("Status"),
                self.tr("Actions"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.table)

        # Add Submodule section
        add_group = QGroupBox(self.tr("Add Submodule"))
        form_layout = QFormLayout(add_group)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://github.com/example/repo.git")
        self.url_input.setAccessibleName("Submodule repository URL")
        form_layout.addRow(self.tr("Repository URL:"), self.url_input)

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("vendor/example")
        self.path_input.setAccessibleName("Submodule local path")
        form_layout.addRow(self.tr("Local Path:"), self.path_input)

        add_btn_layout = QHBoxLayout()
        add_btn_layout.addStretch()
        self.add_btn = QPushButton(self.tr("Add Submodule"))
        self.add_btn.setAccessibleName("Confirm add submodule")
        self.add_btn.clicked.connect(self._on_add_submodule)
        add_btn_layout.addWidget(self.add_btn)
        form_layout.addRow(add_btn_layout)

        layout.addWidget(add_group)

        # Footer close button
        footer_layout = QHBoxLayout()
        footer_layout.addStretch()
        self.close_btn = QPushButton(self.tr("Close"))
        self.close_btn.clicked.connect(self.accept)
        footer_layout.addWidget(self.close_btn)
        layout.addLayout(footer_layout)

    def refresh(self) -> None:
        """Reload submodule list from engine."""
        for old_row in range(self.table.rowCount()):
            for old_col in range(self.table.columnCount()):
                old_widget = self.table.cellWidget(old_row, old_col)
                if old_widget is not None:
                    self.table.removeCellWidget(old_row, old_col)
                    old_widget.setParent(None)
                    old_widget.deleteLater()
        self.table.clearContents()
        self.table.setRowCount(0)
        try:
            submodules = engine.list_submodules(self.repo)
        except Exception as e:
            logger.debug("[submodule-dialog] Error listing submodules: %s", e)
            submodules = []

        for row, sm in enumerate(submodules):
            self.table.insertRow(row)

            # Path
            path_item = QTableWidgetItem(sm.path)
            self.table.setItem(row, 0, path_item)

            # URL
            url_item = QTableWidgetItem(sm.url)
            self.table.setItem(row, 1, url_item)

            # Status check
            stat = engine.submodule_status(self.repo, sm.path)
            commit_text = stat.current_commit[:7] if stat.current_commit else "-"
            commit_item = QTableWidgetItem(commit_text)
            self.table.setItem(row, 2, commit_item)

            if not sm.initialized:
                status_text = self.tr("Uninitialized")
                status_item = QTableWidgetItem(f"📦 {status_text}")
                status_item.setForeground(Qt.GlobalColor.gray)
            elif stat.is_dirty:
                status_text = self.tr("Dirty")
                status_item = QTableWidgetItem(f"⚠️ {status_text}")
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            else:
                status_text = self.tr("Clean")
                status_item = QTableWidgetItem(f"✓ {status_text}")
                status_item.setForeground(Qt.GlobalColor.darkGreen)

            self.table.setItem(row, 3, status_item)

            # Row Action Buttons
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            action_layout.setSpacing(6)

            init_btn = QPushButton(self.tr("Init"))
            init_btn.setAccessibleName(f"Initialize submodule {sm.path}")
            init_btn.setEnabled(not sm.initialized)
            init_btn.clicked.connect(lambda _, p=sm.path: self._on_init_submodule(p))
            action_layout.addWidget(init_btn)

            update_btn = QPushButton(self.tr("Update"))
            update_btn.setAccessibleName(f"Update submodule {sm.path}")
            update_btn.clicked.connect(lambda _, p=sm.path: self._on_update_submodule(p))
            action_layout.addWidget(update_btn)

            self.table.setCellWidget(row, 4, action_widget)

    @Slot()
    def _on_update_all(self) -> None:
        try:
            engine.update_submodules(self.repo, recursive=True)
            self.refresh()
            self.submodules_changed.emit()
        except Exception as e:
            logger.debug("[submodule-dialog] Update all failed: %s", e)
            QMessageBox.critical(self, self.tr("Update Failed"), str(e))

    @Slot(str)
    def _on_init_submodule(self, path: str) -> None:
        try:
            engine.init_submodule(self.repo, path=path)
            self.refresh()
            self.submodules_changed.emit()
        except Exception as e:
            logger.debug("[submodule-dialog] Init failed for %s: %s", path, e)
            QMessageBox.critical(self, self.tr("Initialization Failed"), str(e))

    @Slot(str)
    def _on_update_submodule(self, path: str) -> None:
        try:
            engine.update_submodules(self.repo, path=path)
            self.refresh()
            self.submodules_changed.emit()
        except Exception as e:
            logger.debug("[submodule-dialog] Update failed for %s: %s", path, e)
            QMessageBox.critical(self, self.tr("Update Failed"), str(e))

    @Slot()
    def _on_add_submodule(self) -> None:
        url = self.url_input.text().strip()
        path = self.path_input.text().strip()

        if not url or not path:
            QMessageBox.warning(
                self,
                self.tr("Missing Fields"),
                self.tr("Please provide both a repository URL and a local path."),
            )
            return

        try:
            engine.add_submodule(self.repo, url=url, path=path)
            self.url_input.clear()
            self.path_input.clear()
            self.refresh()
            self.submodules_changed.emit()
        except Exception as e:
            logger.debug("[submodule-dialog] Add submodule failed: %s", e)
            QMessageBox.critical(self, self.tr("Add Submodule Failed"), str(e))
