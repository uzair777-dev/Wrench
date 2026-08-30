"""Dialog presenting classified error diagnoses and 1-click recovery actions."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core.recovery.actions import RecoveryAction
from wrench.core.recovery.classifier import DiagnosticReport

logger = logging.getLogger(__name__)


class RecoveryDialog(QDialog):
    """Actionable dialog providing 1-click recovery options for Git and environment failures."""

    action_completed = Signal(str)

    def __init__(
        self,
        report: DiagnosticReport,
        repo_path: Path | str | None = None,
        context: dict | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.report = report
        self.repo_path = Path(repo_path) if repo_path else None
        self.context = context or {}

        self.setWindowTitle(self.report.title)
        self.setMinimumWidth(540)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Header
        header_layout = QHBoxLayout()
        icon_lbl = QLabel("🛠️", self)
        icon_lbl.setStyleSheet("font-size: 28px;")
        header_layout.addWidget(icon_lbl)

        title_layout = QVBoxLayout()
        title_lbl = QLabel(f"<b>{self.report.title}</b>", self)
        title_lbl.setStyleSheet("font-size: 15px;")
        title_layout.addWidget(title_lbl)

        desc_lbl = QLabel(self.report.description, self)
        desc_lbl.setWordWrap(True)
        title_layout.addWidget(desc_lbl)
        header_layout.addLayout(title_layout)
        layout.addLayout(header_layout)

        # Technical details (expandable/scrollable)
        if self.report.technical_details:
            details_lbl = QLabel("<b>Technical Details:</b>", self)
            layout.addWidget(details_lbl)

            self.details_edit = QTextEdit(self)
            self.details_edit.setPlainText(self.report.technical_details)
            self.details_edit.setReadOnly(True)
            self.details_edit.setFixedHeight(110)
            self.details_edit.setStyleSheet(
                "background-color: #1e1e1e; color: #f1f1f1; "
                "font-family: monospace; font-size: 11px;"
            )

            layout.addWidget(self.details_edit)

        # Status text
        self.status_lbl = QLabel("", self)
        self.status_lbl.setStyleSheet("font-style: italic; color: #7f8c8d;")
        layout.addWidget(self.status_lbl)

        # Action Buttons
        btn_bar = QHBoxLayout()
        btn_bar.addStretch()

        self.action_buttons: list[QPushButton] = []
        for action in self.report.actions:
            btn = QPushButton(action.title, self)
            btn.setToolTip(action.description)
            if action.is_primary:
                btn.setDefault(True)
                btn.setStyleSheet(
                    "font-weight: bold; background-color: #2980b9; color: white; padding: 6px 14px;"
                )
            btn.clicked.connect(lambda _, a=action: self._on_execute_action(a))
            btn_bar.addWidget(btn)
            self.action_buttons.append(btn)

        self.cancel_btn = QPushButton("Dismiss", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self.cancel_btn)

        layout.addLayout(btn_bar)

    def _on_execute_action(self, action: RecoveryAction) -> None:
        self.status_lbl.setText(f"Executing '{action.title}'...")
        if not self.repo_path:
            QMessageBox.warning(self, "No Repository", "No repository path available for recovery.")
            return

        try:
            res = action.execute(self.repo_path, self.context)
            if res.success:
                QMessageBox.information(self, "Recovery Complete", res.message)
                self.action_completed.emit(action.action_id)
                self.accept()
            else:
                err_msg = f"{res.message}\n\nError: {res.error}" if res.error else res.message
                QMessageBox.critical(self, "Action Failed", err_msg)
                self.status_lbl.setText("Recovery action failed.")
        except Exception as e:
            logger.exception("Error executing recovery action %s: %s", action.action_id, e)
            QMessageBox.critical(self, "Recovery Error", f"Unexpected error during recovery:\n{e}")
            self.status_lbl.setText("Unexpected error.")
