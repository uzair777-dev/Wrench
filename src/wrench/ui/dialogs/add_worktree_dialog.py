"""Dialog for creating a new linked git worktree (VP-3, FR-1.13, FR-1.17)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core.exceptions import WorktreeAlreadyCheckedOutError, WrenchGitError
from wrench.core.models import WorktreeInfo
from wrench.ui.widgets.cli_preview_bar import CliCommandPreviewBar

logger = logging.getLogger(__name__)


class AddWorktreeDialog(QDialog):
    """Modal dialog allowing users to add a new linked worktree from an existing or new branch."""

    def __init__(
        self,
        engine: Any,
        settings: Any,
        repo_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Linked Worktree")
        self.resize(560, 340)

        self._engine = engine
        self._settings = settings
        self._repo_path = repo_path
        self._created_worktree: WorktreeInfo | None = None

        self._init_ui()
        self._load_branches()
        self._update_target_path()
        self._update_cli_preview()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header with title and settings jump button
        header_layout = QHBoxLayout()
        title_label = QLabel("Add New Git Worktree")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 1)
        title_label.setFont(title_font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.btn_settings = QToolButton()
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("Configure Worktrees in Settings...")
        self.btn_settings.clicked.connect(self._on_settings_jump)
        header_layout.addWidget(self.btn_settings)
        layout.addLayout(header_layout)

        # Branch row
        branch_layout = QVBoxLayout()
        branch_label = QLabel("Branch:")
        branch_label.setStyleSheet("font-weight: 500;")
        branch_layout.addWidget(branch_label)

        branch_select_row = QHBoxLayout()
        self.combo_branch = QComboBox()
        self.combo_branch.setEditable(True)
        self.combo_branch.currentTextChanged.connect(self._on_branch_changed)
        branch_select_row.addWidget(self.combo_branch, 1)

        self.chk_new_branch = QCheckBox("Create new branch")
        self.chk_new_branch.toggled.connect(self._on_new_branch_toggled)
        branch_select_row.addWidget(self.chk_new_branch)
        branch_layout.addLayout(branch_select_row)
        layout.addLayout(branch_layout)

        # Target Directory row
        dir_layout = QVBoxLayout()
        dir_label = QLabel("Destination Directory:")
        dir_label.setStyleSheet("font-weight: 500;")
        dir_layout.addWidget(dir_label)

        dir_input_row = QHBoxLayout()
        self.edit_path = QLineEdit()
        self.edit_path.textChanged.connect(self._on_path_changed)
        dir_input_row.addWidget(self.edit_path, 1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.clicked.connect(self._on_browse)
        dir_input_row.addWidget(self.btn_browse)
        dir_layout.addLayout(dir_input_row)

        self.lbl_path_hint = QLabel()
        self.lbl_path_hint.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        dir_layout.addWidget(self.lbl_path_hint)
        layout.addLayout(dir_layout)

        # CLI Command Preview Bar
        self.preview_bar = CliCommandPreviewBar(self, settings_registry=self._settings)
        self.cli_preview = self.preview_bar
        self._update_path_preview = self._update_target_path
        layout.addWidget(self.preview_bar)

        layout.addStretch()

        # Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_add = QPushButton("Add Worktree")
        self.btn_add.setDefault(True)
        self.btn_add.setStyleSheet("font-weight: bold;")
        self.btn_add.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self.btn_add)

        layout.addLayout(btn_layout)

    def _load_branches(self) -> None:
        """Load repository branches into the selector dropdown."""
        try:
            branches = self._engine.list_branches(repo=self._repo_path)
            branch_names = [b.name for b in branches if getattr(b, "name", None)]
        except Exception as e:
            logger.debug("Failed listing branches: %s", e)
            branch_names = []

        self.combo_branch.clear()
        if branch_names:
            self.combo_branch.addItems(branch_names)
        else:
            self.combo_branch.addItem("main")
            self.chk_new_branch.setChecked(True)

    @Slot(str)
    def _on_branch_changed(self, text: str) -> None:
        self._update_target_path()
        self._update_cli_preview()

    @Slot(bool)
    def _on_new_branch_toggled(self, checked: bool) -> None:
        self._update_target_path()
        self._update_cli_preview()

    @Slot(str)
    def _on_path_changed(self, text: str) -> None:
        self._update_cli_preview()

    def _update_target_path(self) -> None:
        branch = self.combo_branch.currentText().strip() or "worktree"
        try:
            tmpl = (
                self._settings.get_str("worktrees.path_template", self._repo_path)
                if self._settings
                else "../{repo_name}-{branch_slug}"
            )
            if hasattr(self._engine, "format_worktree_path"):
                try:
                    resolved = self._engine.format_worktree_path(
                        branch, template=tmpl, repo=self._repo_path
                    )
                except TypeError:
                    resolved = self._engine.format_worktree_path(self._repo_path, branch, tmpl)
            else:
                from wrench.core import worktrees

                resolved = worktrees.format_worktree_path(self._repo_path, branch, tmpl)
            self.edit_path.setText(str(resolved))
            self.lbl_path_hint.setText(f"Template: {tmpl}")
        except Exception as e:
            logger.debug("Failed formatting worktree path: %s", e)

    def _update_cli_preview(self) -> None:
        branch = self.combo_branch.currentText().strip() or "main"
        target_path = self.edit_path.text().strip() or "..."
        is_new = self.chk_new_branch.isChecked()

        cmd = ["git", "-C", self._repo_path, "worktree", "add"]
        if is_new:
            cmd.extend(["-b", branch, target_path])
        else:
            cmd.extend([target_path, branch])

        self.preview_bar.set_command(cmd)

    def _on_browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Destination Directory for Worktree",
            str(Path(self._repo_path).parent),
        )
        if chosen:
            self.edit_path.setText(chosen)

    def _on_settings_jump(self) -> None:
        p = self.window()
        opener = getattr(p, "open_settings_at_category", None)
        if callable(opener):
            opener("Worktrees & Submodules", highlight_key="worktrees.path_template")

    def _on_add_clicked(self) -> None:
        branch = self.combo_branch.currentText().strip()
        target_path = self.edit_path.text().strip()
        is_new = self.chk_new_branch.isChecked()

        if not branch:
            QMessageBox.warning(self, "Invalid Branch", "Please specify a branch name.")
            return

        if not target_path:
            QMessageBox.warning(self, "Invalid Path", "Please specify a destination path.")
            return

        try:
            self.btn_add.setEnabled(False)
            if hasattr(self._engine, "add_worktree"):
                try:
                    wt = self._engine.add_worktree(
                        target_path=target_path,
                        branch=branch,
                        create_branch=is_new,
                        repo=self._repo_path,
                    )
                except TypeError:
                    wt = self._engine.add_worktree(
                        self._repo_path,
                        target_path=target_path,
                        branch=branch,
                        create_branch=is_new,
                    )
            else:
                from wrench.core import worktrees

                wt = worktrees.add_worktree(
                    self._repo_path,
                    target_path,
                    branch=branch,
                    create_branch=is_new,
                )
            self._created_worktree = wt
            self.accept()
        except WorktreeAlreadyCheckedOutError as e:
            QMessageBox.warning(
                self,
                "Branch Already Checked Out",
                f"Branch '{e.branch}' is already checked out at:\n{e.existing_path}\n\n"
                "Git does not permit checking out the same branch in multiple worktrees.",
            )
        except WrenchGitError as e:
            QMessageBox.critical(self, "Error Adding Worktree", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Unexpected Error", f"Failed adding worktree: {e}")
        finally:
            self.btn_add.setEnabled(True)

    @property
    def created_worktree(self) -> WorktreeInfo | None:
        return self._created_worktree
