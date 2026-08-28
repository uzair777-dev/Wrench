"""Branch Indicator / Switcher Widget (ui-planning.md §3.2b, SRS FR-1.6).

Provides:
- Current branch display with icon (🌿 main ▾ or 🔗 HEAD detached at {short_sha})
- Searchable branch picker popup
- Safe switching with uncommitted changes (Stash & Switch / Switch Anyway / Cancel)
- Context menu: Create New Branch, Rename Branch, Delete Branch
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle

logger = logging.getLogger(__name__)


class BranchPickerPopup(QDialog):
    """Filterable popup dialog listing local and remote branches."""

    branch_selected = Signal(str)

    def __init__(
        self,
        repo: RepoHandle,
        current_branch: str | None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self._repo = repo
        self._current_branch = current_branch
        self.setAttribute(Qt.WA_DeleteOnClose)

        self.setFixedWidth(280)
        self.setFixedHeight(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Search bar
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText(self.tr("Filter branches…"))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_branches)
        layout.addWidget(self.search_input)

        # Branch list
        self.list_widget = QListWidget(self)
        self.list_widget.itemDoubleClicked.connect(self._on_item_activated)
        layout.addWidget(self.list_widget)

        self._populate_branches()
        self.search_input.setFocus()

    def _populate_branches(self) -> None:
        self.list_widget.clear()
        branches = engine.list_branches(self._repo)

        # Sort: current branch first, then alphabetical
        def branch_sort_key(b: str) -> tuple[int, str]:
            if b == self._current_branch:
                return (0, b)
            if not b.startswith("origin/") and not b.startswith("upstream/"):
                return (1, b)
            return (2, b)

        sorted_branches = sorted(branches, key=branch_sort_key)
        for b in sorted_branches:
            is_local = not b.startswith("origin/") and not b.startswith("upstream/")
            prefix = "🌿 " if is_local else "☁️ "
            suffix = " (current)" if b == self._current_branch else ""
            item = QListWidgetItem(f"{prefix}{b}{suffix}")
            item.setData(Qt.UserRole, b)
            if b == self._current_branch:
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            self.list_widget.addItem(item)

    def _filter_branches(self, text: str) -> None:
        query = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            raw_branch = item.data(Qt.UserRole) or ""
            item.setHidden(query not in raw_branch.lower())

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        branch = item.data(Qt.UserRole)
        if branch:
            self.branch_selected.emit(branch)
            self.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            item = self.list_widget.currentItem()
            if item:
                self._on_item_activated(item)
        elif event.key() == Qt.Key_Down:
            self.list_widget.setFocus()
            self.list_widget.setCurrentRow(0)
        else:
            super().keyPressEvent(event)


class BranchSwitcherWidget(QWidget):
    """Branch indicator / switcher button with safety prompts and branch actions."""

    branch_switched = Signal(str)
    branch_operation_completed = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_branch: str | None = None
        self._is_detached: bool = False
        self._detached_sha: str | None = None
        self._is_unborn: bool = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.btn = QPushButton(self)
        self.btn.setFlat(True)
        self.btn.setStyleSheet(
            "QPushButton { text-align: left; font-size: 12px; padding: 3px 6px; "
            "border: none; border-radius: 3px; } "
            "QPushButton:hover { background-color: rgba(128, 128, 128, 0.15); }"
        )
        self.btn.clicked.connect(self._show_picker)
        self.btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.btn)

        self._update_display()

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.refresh()

    def refresh(self) -> None:
        if not self._repo:
            self._current_branch = None
            self._is_detached = False
            self._detached_sha = None
            self._is_unborn = False
            self._update_display()
            return

        try:
            status = engine.get_status(self._repo)
            self._current_branch = status.branch_name
            self._is_detached = status.is_detached_head
            self._detached_sha = status.head_sha[:7] if status.head_sha else "unknown"
            self._is_unborn = not status.head_sha
        except Exception as e:
            logger.error("Failed to refresh branch status: %s", e)
            self._current_branch = None
            self._is_detached = False
            self._is_unborn = False

        self._update_display()

    def _update_display(self) -> None:
        if not self._repo:
            self.btn.setText(self.tr("No repository"))
            self.btn.setEnabled(False)
            self.btn.setAccessibleName(self.tr("No repository selected"))
            return

        self.btn.setEnabled(True)

        if self._is_detached:
            self.btn.setText(f"🔗 HEAD detached at {self._detached_sha} ▾")
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; font-size: 12px; color: #e5a623; "
                "font-weight: bold; padding: 3px 6px; border: none; } "
                "QPushButton:hover { background-color: rgba(229, 166, 35, 0.2); }"
            )
            self.btn.setAccessibleName(f"Detached HEAD at {self._detached_sha}")
        elif self._is_unborn:
            branch_label = self._current_branch or "main"
            self.btn.setText(f"🌿 {branch_label} (initial)")
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; font-size: 12px; color: gray; "
                "padding: 3px 6px; border: none; }"
            )
            self.btn.setAccessibleName(f"Unborn branch: {branch_label}")
        else:
            branch_label = self._current_branch or "detached"
            self.btn.setText(f"🌿 {branch_label} ▾")
            self.btn.setStyleSheet(
                "QPushButton { text-align: left; font-size: 12px; padding: 3px 6px; "
                "border: none; } "
                "QPushButton:hover { background-color: rgba(128, 128, 128, 0.15); }"
            )
            self.btn.setAccessibleName(f"Switch branch: {branch_label}")

    def _show_picker(self) -> None:
        if not self._repo or self._is_unborn:
            return

        popup = BranchPickerPopup(self._repo, self._current_branch, self)
        popup.branch_selected.connect(self._handle_branch_selection)
        pos = self.btn.mapToGlobal(QPoint(0, self.btn.height()))

        # Keep within screen geometry
        screen = self.screen()
        if screen:
            screen_geo = screen.availableGeometry()
            if pos.x() + popup.width() > screen_geo.right():
                pos.setX(max(screen_geo.left(), screen_geo.right() - popup.width()))
            if pos.y() + popup.height() > screen_geo.bottom():
                top_y = self.btn.mapToGlobal(QPoint(0, 0)).y()
                pos.setY(max(screen_geo.top(), top_y - popup.height()))

        popup.move(pos)
        popup.exec()

    def _handle_branch_selection(self, target_branch: str) -> None:
        if not self._repo:
            return

        # Strip origin/ or upstream/ prefix if remote branch checkout requested
        clean_target = target_branch
        if clean_target.startswith("origin/"):
            clean_target = clean_target[len("origin/") :]
        elif clean_target.startswith("upstream/"):
            clean_target = clean_target[len("upstream/") :]

        if clean_target == self._current_branch and not self._is_detached:
            return

        # Check for uncommitted changes
        status = engine.get_status(self._repo)
        has_uncommitted = bool(status.staged or status.unstaged or status.untracked)

        if has_uncommitted:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self.tr("Uncommitted Changes"))
            msg_box.setText(
                self.tr(
                    f"You have uncommitted changes in your working tree.\n"
                    f"How would you like to switch to '{clean_target}'?"
                )
            )
            stash_btn = msg_box.addButton(self.tr("Stash && Switch"), QMessageBox.AcceptRole)
            msg_box.addButton(self.tr("Switch Anyway"), QMessageBox.DestructiveRole)
            cancel_btn = msg_box.addButton(self.tr("Cancel"), QMessageBox.RejectRole)

            msg_box.exec()
            clicked = msg_box.clickedButton()

            if clicked == cancel_btn:
                return
            elif clicked == stash_btn:
                try:
                    engine.stash_create(self._repo, f"WIP before switch to {clean_target}")
                    engine.switch_branch(self._repo, clean_target)
                    try:
                        engine.stash_pop(self._repo, 0)
                    except Exception as pe:
                        QMessageBox.warning(
                            self,
                            self.tr("Stash Pop Conflict"),
                            self.tr(f"Switched branch, but re-applying stash had conflicts: {pe}"),
                        )
                except Exception as se:
                    QMessageBox.critical(
                        self,
                        self.tr("Stash & Switch Failed"),
                        self.tr(f"Could not stash and switch branch: {se}"),
                    )
                    return
            else:  # Switch Anyway
                try:
                    engine.switch_branch(self._repo, clean_target)
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        self.tr("Switch Branch Failed"),
                        self.tr(f"Could not switch to branch '{clean_target}': {e}"),
                    )
                    return
        else:
            try:
                engine.switch_branch(self._repo, clean_target)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Switch Branch Failed"),
                    self.tr(f"Could not switch to branch '{clean_target}': {e}"),
                )
                return

        self.refresh()
        self.branch_switched.emit(clean_target)

    def _show_context_menu(self, pos: QPoint) -> None:
        if not self._repo:
            return

        menu = QMenu(self)

        act_new = menu.addAction(self.tr("Create New Branch…"))
        act_new.triggered.connect(self._create_branch_dialog)

        if not self._is_detached and not self._is_unborn and self._current_branch:
            act_rename = menu.addAction(self.tr(f"Rename '{self._current_branch}'…"))
            act_rename.triggered.connect(self._rename_branch_dialog)

        act_delete = menu.addAction(self.tr("Delete Branch…"))
        act_delete.triggered.connect(self._delete_branch_dialog)

        menu.exec(self.btn.mapToGlobal(pos))

    def _create_branch_dialog(self) -> None:
        if not self._repo:
            return
        name, ok = QInputDialog.getText(
            self,
            self.tr("Create Branch"),
            self.tr("New branch name:"),
        )
        if ok and name.strip():
            clean_name = name.strip()
            try:
                engine.create_branch(self._repo, clean_name)
                engine.switch_branch(self._repo, clean_name)
                self.refresh()
                self.branch_switched.emit(clean_name)
                self.branch_operation_completed.emit()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Create Branch Failed"),
                    self.tr(f"Could not create branch '{clean_name}': {e}"),
                )

    def _rename_branch_dialog(self) -> None:
        if not self._repo or not self._current_branch:
            return
        new_name, ok = QInputDialog.getText(
            self,
            self.tr("Rename Branch"),
            self.tr("New name for branch:"),
            text=self._current_branch,
        )
        if ok and new_name.strip() and new_name.strip() != self._current_branch:
            clean_name = new_name.strip()
            try:
                engine.rename_branch(self._repo, self._current_branch, clean_name)
                self.refresh()
                self.branch_switched.emit(clean_name)
                self.branch_operation_completed.emit()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Rename Branch Failed"),
                    self.tr(f"Could not rename branch: {e}"),
                )

    def _delete_branch_dialog(self) -> None:
        if not self._repo:
            return
        branches = [b for b in engine.list_branches(self._repo) if b != self._current_branch]
        if not branches:
            QMessageBox.information(
                self,
                self.tr("Delete Branch"),
                self.tr("No other local branches available to delete."),
            )
            return

        branch, ok = QInputDialog.getItem(
            self,
            self.tr("Delete Branch"),
            self.tr("Select branch to delete:"),
            branches,
            0,
            False,
        )
        if ok and branch:
            reply = QMessageBox.question(
                self,
                self.tr("Confirm Deletion"),
                self.tr(f"Are you sure you want to delete branch '{branch}'?"),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                try:
                    engine.delete_branch(self._repo, branch)
                    self.branch_operation_completed.emit()
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        self.tr("Delete Branch Failed"),
                        self.tr(f"Could not delete branch '{branch}': {e}"),
                    )
