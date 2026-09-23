"""Dialog for submitting a pull request / merge request review."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
)

from wrench.forge.capability import ForgeAdapter
from wrench.ui.workers import run_in_background


class SubmitReviewDialog(QDialog):
    """Submit review dialog supporting Approve, Request Changes, and Comment."""

    review_submitted = Signal()

    def __init__(
        self,
        adapter: ForgeAdapter,
        owner: str,
        repo: str,
        pr_number: int,
        parent=None,
    ):
        super().__init__(parent)
        self.adapter = adapter
        self.owner = owner
        self.repo = repo
        self.pr_number = pr_number

        self.setWindowTitle(f"Submit Review — PR #{pr_number}")
        self.setMinimumWidth(450)
        self.setMinimumHeight(320)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #d20f39; font-weight: bold; padding: 4px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        # Action radio buttons
        self.action_group = QButtonGroup(self)

        self.approve_radio = QRadioButton("Approve (leaves approval on this pull request)", self)
        self.action_group.addButton(self.approve_radio)
        layout.addWidget(self.approve_radio)

        self.request_changes_radio = QRadioButton(
            "Request Changes (submits feedback that must be addressed)", self
        )
        self.action_group.addButton(self.request_changes_radio)
        layout.addWidget(self.request_changes_radio)

        self.comment_radio = QRadioButton(
            "Comment (general feedback without approval/rejection)", self
        )
        self.action_group.addButton(self.comment_radio)
        layout.addWidget(self.comment_radio)

        # Check supported actions
        supported = self.adapter.supported_review_actions
        if "request_changes" not in supported:
            self.request_changes_radio.setEnabled(False)
            self.request_changes_radio.setToolTip(
                f"{self.adapter.provider_id.capitalize()} does not support "
                "requesting changes via API."
            )

        if "approve" in supported:
            self.approve_radio.setChecked(True)
        else:
            self.comment_radio.setChecked(True)

        self.action_group.buttonToggled.connect(self._validate)

        # Body input
        layout.addWidget(QLabel("Review Comments:", self))
        self.body_input = QTextEdit(self)
        self.body_input.setPlaceholderText("Write your review comments here…")
        self.body_input.textChanged.connect(self._validate)
        layout.addWidget(self.body_input)

        # Button Box
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.ok_btn = self.button_box.button(QDialogButtonBox.Ok)
        self.ok_btn.setText("Submit Review")
        self.button_box.accepted.connect(self._submit)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._validate()

    def _get_action(self) -> str:
        if self.approve_radio.isChecked():
            return "approve"
        if self.request_changes_radio.isChecked():
            return "request_changes"
        return "comment"

    def _validate(self) -> None:
        action = self._get_action()
        body = self.body_input.toPlainText().strip()

        # Comment action strictly requires body text
        if action == "comment" and not body:
            self.ok_btn.setEnabled(False)
        else:
            self.ok_btn.setEnabled(True)

    def _submit(self) -> None:
        action = self._get_action()
        body = self.body_input.toPlainText().strip()

        self.ok_btn.setEnabled(False)
        self.ok_btn.setText("Submitting…")
        self.error_label.setVisible(False)

        run_in_background(
            fn=lambda: self.adapter.submit_review(
                self.owner,
                self.repo,
                self.pr_number,
                action=action,
                body=body,
            ),
            on_finished=self._on_success,
            on_failed=self._on_failure,
        )

    def _on_success(self, _=None) -> None:
        self.review_submitted.emit()
        self.accept()

    def _on_failure(self, exc: Exception) -> None:
        self.ok_btn.setEnabled(True)
        self.ok_btn.setText("Submit Review")
        self.error_label.setText(str(exc))
        self.error_label.setVisible(True)
