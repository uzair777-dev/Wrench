"""Dialog for creating a new pull request / merge request."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTextEdit,
    QVBoxLayout,
)

from wrench.forge.capability import ForgeAdapter
from wrench.forge.models import PullRequest
from wrench.ui.workers import run_in_background


class CreatePRDialog(QDialog):
    """Create Pull Request dialog with branch validation and non-destructive error handling."""

    pr_created = Signal(object)  # PullRequest

    def __init__(
        self,
        adapter: ForgeAdapter,
        owner: str,
        repo: str,
        branches: list[str],
        current_branch: str,
        default_target_branch: str = "main",
        parent=None,
    ):
        super().__init__(parent)
        self.adapter = adapter
        self.owner = owner
        self.repo = repo
        self.branches = branches
        self.current_branch = current_branch
        self.default_target_branch = default_target_branch

        self.setWindowTitle(f"Create Pull Request — {owner}/{repo}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Inline error label
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #d20f39; font-weight: bold; padding: 4px;")
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        form = QFormLayout()
        form.setSpacing(8)

        # Title
        self.title_input = QLineEdit(self)
        self.title_input.setPlaceholderText("Pull request title…")
        self.title_input.textChanged.connect(self._validate_form)
        form.addRow("Title *:", self.title_input)

        # Branches selection row
        branch_layout = QHBoxLayout()
        self.source_combo = QComboBox(self)
        self.source_combo.addItems(self.branches)
        if self.current_branch in self.branches:
            self.source_combo.setCurrentText(self.current_branch)
        self.source_combo.currentIndexChanged.connect(self._validate_form)

        arrow_label = QLabel("→", self)
        arrow_label.setAlignment(Qt.AlignCenter)

        self.target_combo = QComboBox(self)
        self.target_combo.addItems(self.branches)
        if self.default_target_branch in self.branches:
            self.target_combo.setCurrentText(self.default_target_branch)
        self.target_combo.currentIndexChanged.connect(self._validate_form)

        branch_layout.addWidget(self.source_combo, 1)
        branch_layout.addWidget(arrow_label)
        branch_layout.addWidget(self.target_combo, 1)
        form.addRow("Branches:", branch_layout)

        # Description
        self.desc_input = QTextEdit(self)
        self.desc_input.setPlaceholderText("Optional description or Markdown summary…")
        form.addRow("Description:", self.desc_input)

        layout.addLayout(form)

        # Dialog Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        self.ok_btn = self.button_box.button(QDialogButtonBox.Ok)
        self.ok_btn.setText("Create Pull Request")
        self.button_box.accepted.connect(self._submit)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._validate_form()

    def _validate_form(self) -> None:
        title = self.title_input.text().strip()
        source = self.source_combo.currentText()
        target = self.target_combo.currentText()

        valid = True
        err = ""

        if not title:
            valid = False
        elif source == target:
            valid = False
            err = "Source and target branches cannot be the same."

        if err:
            self.error_label.setText(err)
            self.error_label.setVisible(True)
        else:
            self.error_label.setVisible(False)

        self.ok_btn.setEnabled(valid)

    def _submit(self) -> None:
        title = self.title_input.text().strip()
        source = self.source_combo.currentText()
        target = self.target_combo.currentText()
        desc = self.desc_input.toPlainText().strip()

        self.ok_btn.setEnabled(False)
        self.ok_btn.setText("Creating…")
        self.error_label.setVisible(False)

        run_in_background(
            fn=lambda: self.adapter.create_pull_request(
                self.owner,
                self.repo,
                title=title,
                source_branch=source,
                target_branch=target,
                description=desc,
            ),
            on_finished=self._on_success,
            on_failed=self._on_failure,
        )

    def _on_success(self, pr: PullRequest) -> None:
        self.pr_created.emit(pr)
        self.accept()

    def _on_failure(self, exc: Exception) -> None:
        self.ok_btn.setEnabled(True)
        self.ok_btn.setText("Create Pull Request")
        self.error_label.setText(str(exc))
        self.error_label.setVisible(True)
