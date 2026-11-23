"""Worktree management sidebar panel (VP-3, SRS FR-1.13, FR-1.17, ui-planning.md §6.17)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core.exceptions import WrenchGitError
from wrench.core.models import WorktreeInfo
from wrench.ui.dialogs.add_worktree_dialog import AddWorktreeDialog
from wrench.ui.theme import get_worktree_status_color, is_dark_theme
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class WorktreePanel(QWidget):
    """Collapsible sidebar panel listing git worktrees with lifecycle controls."""

    open_worktree_requested = Signal(str)  # (worktree_path)
    worktree_added = Signal(str)
    worktree_removed = Signal(str)

    def __init__(
        self,
        engine: Any,
        settings: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._settings = settings
        self._repo_path: str | None = None
        self._worktrees: list[WorktreeInfo] = []
        self._load_generation = 0

        self._init_ui()

        # Connect live setting changes for instant show/hide
        if self._settings and hasattr(self._settings, "setting_changed"):
            self._settings.setting_changed.connect(self._on_setting_changed)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header bar
        self.header_bar = QFrame(self)
        self.header_bar.setObjectName("worktree_header_bar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(6)

        self.lbl_title = QLabel("🌿 Worktrees", self.header_bar)
        font = QFont()
        font.setBold(True)
        self.lbl_title.setFont(font)
        header_layout.addWidget(self.lbl_title)

        self.lbl_count = QLabel("0", self.header_bar)
        self.lbl_count.setStyleSheet(
            "background-color: rgba(128, 128, 128, 0.2); border-radius: 8px; "
            "padding: 1px 6px; font-size: 11px; font-weight: bold;"
        )
        header_layout.addWidget(self.lbl_count)
        header_layout.addStretch()

        self.btn_add = QToolButton(self.header_bar)
        self.btn_add.setText("+")
        self.btn_add.setToolTip("Add Linked Worktree...")
        self.btn_add.setAutoRaise(True)
        self.btn_add.clicked.connect(self._on_add_worktree_clicked)
        header_layout.addWidget(self.btn_add)

        self.btn_settings = QToolButton(self.header_bar)
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("Configure Worktrees in Settings...")
        self.btn_settings.setAutoRaise(True)
        self.btn_settings.clicked.connect(self._on_settings_clicked)
        header_layout.addWidget(self.btn_settings)

        layout.addWidget(self.header_bar)

        # Tree widget
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(12)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.tree)

    def set_repo_path(self, repo_path: str | None) -> None:
        """Update active repository path and refresh worktree list."""
        self._repo_path = repo_path
        if not repo_path:
            self._worktrees = []
            self.tree.clear()
            self.lbl_count.setText("0")
            return
        self.refresh()

    def refresh(self) -> None:
        """Query worktrees asynchronously in background."""
        if not self._repo_path:
            return

        if self._settings and not self._settings.is_enabled("worktrees.enabled", self._repo_path):
            self.setVisible(False)
            return
        self.setVisible(True)

        self._load_generation += 1
        gen = self._load_generation
        repo_path = self._repo_path

        def _fetch() -> list[WorktreeInfo]:
            return self._engine.list_worktrees(repo=repo_path)

        def _on_done(wts: list[WorktreeInfo]) -> None:
            if gen != self._load_generation:
                return
            self._worktrees = wts
            self._rebuild_tree()

        def _on_error(exc: Exception) -> None:
            logger.debug("Failed refreshing worktrees: %s", exc)

        run_in_background(_fetch, on_finished=_on_done, on_failed=_on_error)

    def _rebuild_tree(self) -> None:
        """Reconstruct tree items from cached worktrees."""
        self.tree.clear()
        self.lbl_count.setText(str(len(self._worktrees)))

        for wt in self._worktrees:
            item = QTreeWidgetItem()
            wt_name = Path(wt.path).name

            label_parts = []
            if wt.is_main:
                label_parts.append(f"🏠 {wt_name} [Main]")
            else:
                label_parts.append(f"🌿 {wt_name}")

            if wt.branch_name:
                label_parts.append(f"({wt.branch_name})")
            elif wt.is_detached:
                label_parts.append("(detached)")

            if wt.is_locked:
                reason = f": {wt.lock_reason}" if wt.lock_reason else ""
                label_parts.append(f"[🔒 Locked{reason}]")
            elif wt.is_prunable:
                label_parts.append("[⚠ Prunable]")

            item.setText(0, " ".join(label_parts))
            item.setToolTip(0, f"Path: {wt.path}\nHEAD: {wt.head_oid or 'none'}")
            item.setData(0, Qt.ItemDataRole.UserRole, wt)

            is_dark = is_dark_theme(self)
            if wt.is_locked:
                item.setForeground(0, QColor(get_worktree_status_color("locked", is_dark)))
            elif wt.is_prunable:
                item.setForeground(0, QColor(get_worktree_status_color("prunable", is_dark)))

            self.tree.addTopLevelItem(item)

    def _on_add_worktree_clicked(self) -> None:
        if not self._repo_path:
            return
        dlg = AddWorktreeDialog(
            engine=self._engine,
            settings=self._settings,
            repo_path=self._repo_path,
            parent=self.window(),
        )
        if dlg.exec() and dlg.created_worktree:
            wt = dlg.created_worktree
            self.refresh()
            self.worktree_added.emit(wt.path)

    def _on_settings_clicked(self) -> None:
        p = self.window()
        opener = getattr(p, "open_settings_at_category", None)
        if callable(opener):
            opener("Worktrees & Submodules", highlight_key="worktrees.enabled")

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        wt: WorktreeInfo | None = item.data(0, Qt.ItemDataRole.UserRole)
        if wt and wt.path:
            self.open_worktree_requested.emit(wt.path)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self.tree.itemAt(pos)
        wt: WorktreeInfo | None = item.data(0, Qt.ItemDataRole.UserRole) if item else None

        menu = QMenu(self)

        act_add = QAction("Add Worktree...", self)
        act_add.triggered.connect(self._on_add_worktree_clicked)
        menu.addAction(act_add)

        act_prune = QAction("Prune Stale Worktrees", self)
        act_prune.triggered.connect(self._on_prune_worktrees)
        menu.addAction(act_prune)

        if wt:
            menu.addSeparator()

            act_open = QAction("Open in New Workspace Tab", self)
            act_open.triggered.connect(lambda: self.open_worktree_requested.emit(wt.path))
            menu.addAction(act_open)

            act_copy = QAction("Copy Worktree Path", self)
            act_copy.triggered.connect(lambda: QApplication.clipboard().setText(wt.path))
            menu.addAction(act_copy)

            if not wt.is_main:
                menu.addSeparator()
                if wt.is_locked:
                    act_unlock = QAction("Unlock Worktree", self)
                    act_unlock.triggered.connect(lambda: self._on_unlock_worktree(wt))
                    menu.addAction(act_unlock)
                else:
                    act_lock = QAction("Lock Worktree...", self)
                    act_lock.triggered.connect(lambda: self._on_lock_worktree(wt))
                    menu.addAction(act_lock)

                act_remove = QAction("Remove Worktree...", self)
                act_remove.triggered.connect(lambda: self._on_remove_worktree(wt))
                menu.addAction(act_remove)

        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _on_lock_worktree(self, wt: WorktreeInfo) -> None:
        reason, ok = QInputDialog.getText(
            self,
            "Lock Worktree",
            f"Reason for locking '{Path(wt.path).name}' (optional):",
        )
        if not ok:
            return
        try:
            self._engine.lock_worktree(wt.path, reason=reason, repo=self._repo_path)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error Locking Worktree", str(e))

    def _on_unlock_worktree(self, wt: WorktreeInfo) -> None:
        try:
            self._engine.unlock_worktree(wt.path, repo=self._repo_path)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error Unlocking Worktree", str(e))

    def _on_remove_worktree(self, wt: WorktreeInfo) -> None:
        extra_warn = "\nThis worktree is currently LOCKED." if wt.is_locked else ""
        res = QMessageBox.question(
            self,
            "Remove Worktree",
            f"Are you sure you want to remove linked worktree:\n{wt.path}?{extra_warn}\n\n"
            "This will delete the worktree folder and remove it from git.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res != QMessageBox.StandardButton.Yes:
            return
        try:
            self._engine.remove_worktree(wt.path, force=wt.is_locked, repo=self._repo_path)
            self.refresh()
            self.worktree_removed.emit(wt.path)
        except Exception as e:
            QMessageBox.critical(self, "Error Removing Worktree", str(e))

    def _on_prune_worktrees(self) -> None:
        try:
            self._engine.prune_worktrees(repo=self._repo_path)
            self.refresh()
        except Exception as e:
            QMessageBox.critical(self, "Error Pruning Worktrees", str(e))

    def _on_setting_changed(self, key: str, value: Any, repo_path: Any = None) -> None:
        if key == "worktrees.enabled":
            enabled = bool(value)
            self.setVisible(enabled)
            if enabled and self._repo_path:
                self.refresh()
