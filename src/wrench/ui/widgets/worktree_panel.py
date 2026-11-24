"""Worktree management sidebar panel (VP-3, SRS FR-1.13, FR-1.17, ui-planning.md §6.17)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core.models import WorktreeInfo
from wrench.ui.dialogs.add_worktree_dialog import AddWorktreeDialog
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class WorktreeCardWidget(QFrame):
    """Rich visual card representing a single worktree entry with metadata and actions."""

    def __init__(
        self,
        wt: WorktreeInfo,
        on_open: Any,
        on_lock: Any = None,
        on_unlock: Any = None,
        on_remove: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.wt = wt
        self._on_open = on_open
        self._on_lock = on_lock
        self._on_unlock = on_unlock
        self._on_remove = on_remove

        self.setObjectName("worktree_card")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 6, 10, 6)
        main_layout.setSpacing(4)

        # Top line: Icon + Title + Branch/Main Badge + Status Tags + Action Buttons
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)

        # Icon
        icon_str = "🏠" if self.wt.is_main else "🌿"
        lbl_icon = QLabel(icon_str, self)
        lbl_icon.setStyleSheet("font-size: 15px;")
        top_layout.addWidget(lbl_icon)

        # Worktree Name
        name = Path(self.wt.path).name or self.wt.path
        lbl_name = QLabel(name, self)
        lbl_name.setStyleSheet("font-size: 13px; font-weight: bold;")
        top_layout.addWidget(lbl_name)

        # Main / Branch badge
        if self.wt.is_main:
            badge_main = QLabel("Main Worktree", self)
            badge_main.setStyleSheet(
                "background-color: rgba(59, 130, 246, 0.2); color: rgba(96, 165, 250, 1.0); "
                "border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px; "
                "padding: 1px 6px; font-size: 11px; font-weight: bold;"
            )
            top_layout.addWidget(badge_main)

        if self.wt.branch_name:
            badge_branch = QLabel(f"🌿 {self.wt.branch_name}", self)
            badge_branch.setStyleSheet(
                "background-color: rgba(16, 185, 129, 0.2); color: rgba(52, 211, 153, 1.0); "
                "border: 1px solid rgba(16, 185, 129, 0.4); border-radius: 4px; "
                "padding: 1px 6px; font-size: 11px; font-weight: bold;"
            )
            top_layout.addWidget(badge_branch)
        elif self.wt.is_detached:
            badge_detached = QLabel("detached", self)
            badge_detached.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.2); color: rgba(248, 113, 113, 1.0); "
                "border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; "
                "padding: 1px 6px; font-size: 11px; font-weight: bold;"
            )
            top_layout.addWidget(badge_detached)

        if self.wt.is_locked:
            reason = f": {self.wt.lock_reason}" if self.wt.lock_reason else ""
            badge_locked = QLabel(f"🔒 Locked{reason}", self)
            badge_locked.setStyleSheet(
                "background-color: rgba(245, 158, 11, 0.2); color: rgba(251, 191, 36, 1.0); "
                "border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 4px; "
                "padding: 1px 6px; font-size: 11px; font-weight: bold;"
            )
            top_layout.addWidget(badge_locked)
        elif self.wt.is_prunable:
            badge_prunable = QLabel("⚠ Prunable", self)
            badge_prunable.setStyleSheet(
                "background-color: rgba(239, 68, 68, 0.2); color: rgba(248, 113, 113, 1.0); "
                "border: 1px solid rgba(239, 68, 68, 0.4); border-radius: 4px; "
                "padding: 1px 6px; font-size: 11px; font-weight: bold;"
            )
            top_layout.addWidget(badge_prunable)

        top_layout.addStretch()

        # Action Buttons
        self.btn_open = QPushButton("Open in Tab", self)
        self.btn_open.setToolTip(f"Open workspace tab for '{name}'")
        self.btn_open.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; font-weight: bold; "
            "border-radius: 4px; background-color: rgba(59, 130, 246, 0.15); "
            "border: 1px solid rgba(59, 130, 246, 0.3); } "
            "QPushButton:hover { background-color: rgba(59, 130, 246, 0.3); }"
        )
        if callable(self._on_open):
            self.btn_open.clicked.connect(lambda: self._on_open(self.wt))
        top_layout.addWidget(self.btn_open)

        if not self.wt.is_main:
            if self.wt.is_locked:
                self.btn_unlock = QPushButton("Unlock", self)
                self.btn_unlock.setToolTip("Unlock this worktree")
                self.btn_unlock.setStyleSheet("font-size: 11px; padding: 3px 8px;")
                if callable(self._on_unlock):
                    self.btn_unlock.clicked.connect(lambda: self._on_unlock(self.wt))
                top_layout.addWidget(self.btn_unlock)
            else:
                self.btn_lock = QPushButton("Lock", self)
                self.btn_lock.setToolTip("Lock this worktree from deletion")
                self.btn_lock.setStyleSheet("font-size: 11px; padding: 3px 8px;")
                if callable(self._on_lock):
                    self.btn_lock.clicked.connect(lambda: self._on_lock(self.wt))
                top_layout.addWidget(self.btn_lock)

            self.btn_remove = QPushButton("Remove", self)
            self.btn_remove.setToolTip("Remove linked worktree")
            self.btn_remove.setStyleSheet(
                "QPushButton { font-size: 11px; padding: 3px 8px; "
                "color: rgba(248, 113, 113, 1.0); } "
                "QPushButton:hover { background-color: rgba(239, 68, 68, 0.2); }"
            )
            if callable(self._on_remove):
                self.btn_remove.clicked.connect(lambda: self._on_remove(self.wt))
            top_layout.addWidget(self.btn_remove)

        main_layout.addLayout(top_layout)

        # Bottom row: Path and HEAD
        head_preview = self.wt.head_oid[:8] if self.wt.head_oid else "none"
        lbl_sub = QLabel(f"Path: {self.wt.path}   •   HEAD: {head_preview}", self)
        lbl_sub.setStyleSheet("font-size: 12px; color: palette(placeholder-text);")
        main_layout.addWidget(lbl_sub)


class WorktreePanel(QWidget):
    """Collapsible sidebar and category tab panel listing git worktrees with lifecycle controls."""

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
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # Header bar
        self.header_bar = QFrame(self)
        self.header_bar.setObjectName("worktree_header_bar")
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.lbl_title = QLabel("🌿 Worktrees", self.header_bar)
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.lbl_title.setFont(font)
        title_row.addWidget(self.lbl_title)

        self.lbl_count = QLabel("0", self.header_bar)
        self.lbl_count.setStyleSheet(
            "background-color: rgba(59, 130, 246, 0.2); color: rgba(96, 165, 250, 1.0); "
            "border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 9px; "
            "padding: 1px 8px; font-size: 12px; font-weight: bold;"
        )
        title_row.addWidget(self.lbl_count)
        title_row.addStretch()
        title_col.addLayout(title_row)

        self.lbl_subtitle = QLabel(
            "Manage linked git working trees for concurrent branch development",
            self.header_bar,
        )
        self.lbl_subtitle.setStyleSheet("font-size: 12px; color: palette(placeholder-text);")
        title_col.addWidget(self.lbl_subtitle)

        header_layout.addLayout(title_col, stretch=1)

        self.btn_add = QPushButton("+ Add Worktree", self.header_bar)
        self.btn_add.setToolTip("Add Linked Worktree...")
        self.btn_add.setStyleSheet(
            "QPushButton { padding: 6px 14px; font-size: 12px; font-weight: bold; "
            "border-radius: 6px; background-color: rgba(59, 130, 246, 0.25); "
            "border: 1px solid rgba(59, 130, 246, 0.5); } "
            "QPushButton:hover { background-color: rgba(59, 130, 246, 0.4); }"
        )
        self.btn_add.clicked.connect(self._on_add_worktree_clicked)
        header_layout.addWidget(self.btn_add)

        self.btn_settings = QToolButton(self.header_bar)
        self.btn_settings.setText("⚙ Settings")
        self.btn_settings.setToolTip("Configure Worktrees in Settings...")
        self.btn_settings.setAutoRaise(True)
        self.btn_settings.clicked.connect(self._on_settings_clicked)
        header_layout.addWidget(self.btn_settings)

        layout.addWidget(self.header_bar)

        # Empty / helper banner
        self.empty_banner = QFrame(self)
        self.empty_banner.setObjectName("worktree_empty_banner")
        banner_layout = QHBoxLayout(self.empty_banner)
        banner_layout.setContentsMargins(12, 10, 12, 10)
        banner_layout.setSpacing(12)

        lbl_info = QLabel(
            "💡 <b>Tip:</b> Linked worktrees let you check out and develop on multiple branches "
            "simultaneously in separate directories without switching branches.",
            self.empty_banner,
        )
        lbl_info.setWordWrap(True)
        lbl_info.setStyleSheet("font-size: 12px;")
        banner_layout.addWidget(lbl_info, stretch=1)

        btn_banner_add = QPushButton("+ Create Linked Worktree", self.empty_banner)
        btn_banner_add.setStyleSheet("padding: 4px 10px; font-size: 11px;")
        btn_banner_add.clicked.connect(self._on_add_worktree_clicked)
        banner_layout.addWidget(btn_banner_add)

        self.empty_banner.setStyleSheet(
            "QFrame#worktree_empty_banner { "
            "background-color: rgba(255, 255, 255, 0.03); "
            "border: 1px solid rgba(255, 255, 255, 0.08); "
            "border-radius: 8px; }"
        )
        layout.addWidget(self.empty_banner)

        # Tree widget
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(0)
        self.tree.setRootIsDecorated(False)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.tree.setStyleSheet(
            "QTreeWidget { background-color: transparent; border: none; } "
            "QTreeWidget::item { padding: 2px; } "
            "QTreeWidget::item:selected { background-color: rgba(255, 255, 255, 0.08); "
            "border-radius: 6px; }"
        )
        layout.addWidget(self.tree, stretch=1)

    def set_repo_path(self, repo_path: str | None) -> None:
        """Update active repository path and refresh worktree list."""
        self._repo_path = repo_path
        if not repo_path:
            self._worktrees = []
            self.tree.clear()
            self.lbl_count.setText("0")
            self.empty_banner.setVisible(False)
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

        # Show empty/single-worktree hint when no linked worktrees exist
        linked_count = sum(1 for wt in self._worktrees if not wt.is_main)
        self.empty_banner.setVisible(linked_count == 0)

        for wt in self._worktrees:
            item = QTreeWidgetItem()
            wt_name = Path(wt.path).name or wt.path

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
            item.setSizeHint(0, QSize(0, 56))

            self.tree.addTopLevelItem(item)

            card = WorktreeCardWidget(
                wt=wt,
                on_open=lambda w: self.open_worktree_requested.emit(w.path),
                on_lock=self._on_lock_worktree,
                on_unlock=self._on_unlock_worktree,
                on_remove=self._on_remove_worktree,
                parent=self.tree,
            )
            self.tree.setItemWidget(item, 0, card)

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
