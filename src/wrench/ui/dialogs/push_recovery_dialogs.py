"""Dedicated recovery dialogs for server-side push rejection errors.

These dialogs provide actionable UI for specific GitHub push protection
errors, replacing generic error messages with guided recovery flows.
"""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from wrench.core.exceptions import (
    FileTooLargeRejectedError,
    ProtectedBranchRejectedError,
    SecretScanningRejectedError,
)

logger = logging.getLogger(__name__)


class SecretScanningDialog(QDialog):
    """Recovery dialog for GitHub Secret Scanning (GH007) push rejection.

    Shows detected secret type, file location, and provides an "Unblock" button
    that opens the GitHub URL to allow the push (if provided).
    """

    def __init__(
        self,
        exc: SecretScanningRejectedError,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._exc = exc
        self.setWindowTitle("Push Blocked — Secret Detected")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # Warning banner
        warning = QLabel(
            "⚠️ <b>GitHub Secret Scanning blocked your push.</b><br>"
            "A secret or credential was detected in your commit."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #d20f39; font-size: 13px; padding: 8px;")
        layout.addWidget(warning)

        # Secret type
        self.secret_type_label = QLabel(f"<b>Secret Type:</b> {exc.secret_type or 'Unknown'}")
        self.secret_type_label.setWordWrap(True)
        layout.addWidget(self.secret_type_label)

        # File location
        self.location_label = QLabel(f"<b>Location:</b> {exc.file_location or 'Unknown'}")
        self.location_label.setWordWrap(True)
        layout.addWidget(self.location_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.unblock_btn = QPushButton("Open Unblock URL in Browser")
        self.unblock_btn.setEnabled(exc.unblock_url is not None)
        self.unblock_btn.clicked.connect(self._open_unblock_url)
        btn_row.addWidget(self.unblock_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _open_unblock_url(self) -> None:
        if self._exc.unblock_url:
            QDesktopServices.openUrl(QUrl(self._exc.unblock_url))


class ProtectedBranchDialog(QDialog):
    """Recovery dialog for GitHub Protected Branch (GH006) push rejection.

    Informs user that direct push is blocked, and offers to create a new branch
    and push there instead.
    """

    def __init__(
        self,
        exc: ProtectedBranchRejectedError,
        default_new_branch: str = "patch-1",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._exc = exc
        self.setWindowTitle("Push Blocked — Protected Branch")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        # Info
        branch = exc.branch_name or "this branch"
        reason = exc.reason or "Branch protection rules are enabled."
        info = QLabel(
            f"⛔ <b>Direct push to '{branch}' was rejected.</b><br>"
            f"{reason}<br><br>"
            "You can create a new branch and push there instead:"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Branch name input
        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("New branch name:"))
        self.branch_name_edit = QLineEdit()
        self.branch_name_edit.setText(default_new_branch)
        input_row.addWidget(self.branch_name_edit)
        layout.addLayout(input_row)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        create_btn = QPushButton("Create Branch && Push")
        create_btn.setDefault(True)
        create_btn.clicked.connect(self.accept)
        btn_row.addWidget(create_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        layout.addLayout(btn_row)

    def get_new_branch_name(self) -> str:
        return self.branch_name_edit.text().strip()


class FileTooLargeDialog(QDialog):
    """Recovery dialog for GitHub File Size Quota (GH001) push rejection.

    Displays the offending file name, size, and limit. Guides user toward
    removing the file from git cache or setting up Git LFS.
    """

    def __init__(
        self,
        exc: FileTooLargeRejectedError,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._exc = exc
        self.setWindowTitle("Push Blocked — File Too Large")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        warning = QLabel("📦 <b>Your push was rejected because a file exceeds the size limit.</b>")
        warning.setWordWrap(True)
        warning.setStyleSheet("font-size: 13px; padding: 8px;")
        layout.addWidget(warning)

        self.filename_label = QLabel(f"<b>File:</b> {exc.filename or 'Unknown'}")
        self.filename_label.setWordWrap(True)
        layout.addWidget(self.filename_label)

        size_str = f"{exc.filesize_mb} MB" if exc.filesize_mb is not None else "Unknown"
        self.filesize_label = QLabel(f"<b>Size:</b> {size_str} (limit: {exc.limit_mb} MB)")
        layout.addWidget(self.filesize_label)

        guidance = QLabel(
            "<br><b>To resolve this:</b><br>"
            "• Remove the file from git: <code>git rm --cached &lt;file&gt;</code><br>"
            "• Or install <a href='https://git-lfs.github.com'>Git LFS</a> "
            "to track large files."
        )
        guidance.setWordWrap(True)
        guidance.setOpenExternalLinks(True)
        layout.addWidget(guidance)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)
