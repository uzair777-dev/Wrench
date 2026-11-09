"""Dialog for resolving user intent when committing partially-staged files."""

from __future__ import annotations

import os
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wrench.ui.theme import get_badge_colors, is_dark_theme


class PartialStagingChoice(str, Enum):
    STAGE_ALL_AND_COMMIT = "stage_all"
    COMMIT_STAGED_ONLY = "staged_only"
    CANCEL = "cancel"


class PartialStagingDialog(QDialog):
    """Modal dialog prompting user whether to stage unstaged working-tree edits on commit."""

    def __init__(
        self,
        file_paths: list[str],
        commit_message: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.file_paths = file_paths
        self.commit_message = commit_message
        self.choice = PartialStagingChoice.CANCEL

        self.setWindowTitle(self.tr("Partially Staged Changes Detected"))
        self.setMinimumWidth(560)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header with icon and descriptive text
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("⚡", self)
        icon_lbl.setStyleSheet("font-size: 26px;")
        header_layout.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_lbl = QLabel(
            f"<b>{self.tr('Unstaged working-tree changes detected in checked files')}</b>",
            self,
        )
        title_lbl.setStyleSheet("font-size: 14px;")
        title_layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            self.tr(
                "The following checked files have staged changes in the index AND "
                "unstaged modifications on disk. Choose how you want to commit:"
            ),
            self,
        )
        desc_lbl.setWordWrap(True)
        title_layout.addWidget(desc_lbl)
        header_layout.addLayout(title_layout)
        layout.addLayout(header_layout)

        # File list
        self.file_list = QListWidget(self)
        self.file_list.setMaximumHeight(160)
        is_dark = is_dark_theme(self)
        fg, bg = get_badge_colors("MM", is_dark=is_dark)

        for path in self.file_paths:
            item = QListWidgetItem(self.file_list)
            row_widget = QWidget(self)
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(8)

            badge = QLabel("MM", row_widget)
            badge.setFixedWidth(30)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"QLabel {{ color: {fg}; background-color: {bg}; font-weight: bold; "
                f"font-size: 11px; border-radius: 3px; padding: 2px 4px; }}"
            )
            row_layout.addWidget(badge)

            path_lbl = QLabel(path, row_widget)
            row_layout.addWidget(path_lbl, 1)

            item.setSizeHint(row_widget.sizeHint())
            self.file_list.addItem(item)
            self.file_list.setItemWidget(item, row_widget)

        layout.addWidget(self.file_list)

        # Remember choice checkbox
        self.remember_cb = QCheckBox(self.tr("Remember this choice for this repository"), self)
        layout.addWidget(self.remember_cb)

        # Action button bar
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton(self.tr("Cancel"), self)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.staged_only_btn = QPushButton(self.tr("Commit Staged Hunks Only"), self)
        self.staged_only_btn.setToolTip(
            self.tr(
                "Commits only what is currently staged in the index; "
                "leaves working-tree modifications unstaged."
            )
        )
        self.staged_only_btn.clicked.connect(self._on_commit_staged_only)
        btn_layout.addWidget(self.staged_only_btn)

        self.stage_all_btn = QPushButton(self.tr("Stage All & Commit"), self)
        self.stage_all_btn.setDefault(True)
        self.stage_all_btn.setToolTip(
            self.tr(
                "Stages all working-tree edits for these files into the index, " "then commits."
            )
        )
        self.stage_all_btn.setStyleSheet(
            "font-weight: bold; background-color: palette(highlight); "
            "color: palette(highlighted-text); padding: 6px 14px; border-radius: 4px;"
        )
        self.stage_all_btn.clicked.connect(self._on_stage_all_and_commit)
        btn_layout.addWidget(self.stage_all_btn)

        layout.addLayout(btn_layout)

    def _on_stage_all_and_commit(self) -> None:
        self.choice = PartialStagingChoice.STAGE_ALL_AND_COMMIT
        self.accept()

    def _on_commit_staged_only(self) -> None:
        self.choice = PartialStagingChoice.COMMIT_STAGED_ONLY
        self.accept()

    def _on_cancel(self) -> None:
        self.choice = PartialStagingChoice.CANCEL
        self.reject()

    @classmethod
    def prompt(
        cls,
        parent: QWidget | None,
        file_paths: list[str],
        commit_message: str = "",
        default_choice: PartialStagingChoice | None = None,
    ) -> tuple[PartialStagingChoice, bool]:
        """Prompt user with dialog and return (choice, remember_for_repo)."""
        if default_choice is not None:
            return default_choice, False

        test_override = os.environ.get("WRENCH_TEST_PARTIAL_STAGING_CHOICE")
        if test_override:
            return PartialStagingChoice(test_override), False

        dlg = cls(file_paths, commit_message=commit_message, parent=parent)
        if dlg.exec() == QDialog.Accepted:
            return dlg.choice, dlg.remember_cb.isChecked()
        return PartialStagingChoice.CANCEL, False
