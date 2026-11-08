"""Dedicated recovery dialogs for server-side push rejection errors.

These dialogs provide actionable UI for specific GitHub push protection
errors, replacing generic error messages with guided recovery flows.
"""

import logging
import re

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from wrench.core import engine
from wrench.core.exceptions import (
    FileTooLargeRejectedError,
    GitNetworkTransferError,
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
        warning.setStyleSheet("color: palette(bright-text); font-size: 13px; padding: 8px;")
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
            "• Or track it with <a href='https://git-lfs.github.com'>Git LFS</a>.<br><br>"
            "<i>• Note: Native Git LFS integration in Wrench is currently under development "
            "for an upcoming release.</i>"
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


class PrePushLargeFilesDialog(QDialog):
    """Pre-flight warning dialog when large files (>= 50MB) are detected in unpushed commits.

    Provides critical warning for files >= 100MB (GitHub GH001 rejection), explains Git LFS
    guidance, and offers an Extreme Compression trial or Cancel to prevent network timeouts.
    """

    def __init__(
        self,
        large_blobs: list[tuple[str, float]],
        remote: str = "origin",
        branch: str = "main",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.large_blobs = large_blobs
        self.action: str = "cancel"

        has_over_100 = any(size >= 100.0 for _, size in large_blobs)
        title = (
            self.tr("Critical: Files Exceed Size Limits")
            if has_over_100
            else self.tr("Warning: Large Files Detected")
        )
        self.setWindowTitle(title)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        if has_over_100:
            header = QLabel(
                self.tr(
                    "🚨 <b>Critical: One or more files exceed the 100 MB limit (&ge; 100 MB).</b>"
                    "<br>GitHub and major Git providers will reject this push at pre-receive "
                    "(GH001). These files should be tracked with <b>Git LFS</b> instead of "
                    "Git history."
                )
            )
            header.setStyleSheet("color: palette(bright-text); font-size: 13px; padding: 4px 0;")
        else:
            header = QLabel(
                self.tr(
                    "⚠️ <b>Large files detected in unpushed commits (&ge; 50 MB).</b><br>"
                    "Large files frequently cause network timeouts (HTTP 408) or warnings on "
                    "GitHub. Consider tracking these with <b>Git LFS</b>."
                )
            )
            header.setStyleSheet("color: palette(highlight); font-size: 13px; padding: 4px 0;")
        header.setWordWrap(True)
        layout.addWidget(header)

        # File List Group
        self.files_box = QGroupBox(self.tr(f"Unpushed Large Files (Branch: {branch} → {remote})"))
        files_layout = QVBoxLayout(self.files_box)

        items_html = []
        for path, size_mb in large_blobs[:6]:
            if size_mb >= 100.0:
                badge = "<b>[Exceeds 100 MB Limit]</b>"
            else:
                badge = "<b>[Large File &ge; 50 MB]</b>"
            items_html.append(f"• <code>{path}</code> — <b>{size_mb:.1f} MB</b> &nbsp; {badge}")

        if len(large_blobs) > 6:
            items_html.append(f"<i>... and {len(large_blobs) - 6} more large files</i>")

        self.files_label = QLabel("<br>".join(items_html))
        self.files_label.setWordWrap(True)
        files_layout.addWidget(self.files_label)
        layout.addWidget(self.files_box)

        # Git LFS Guidance Box
        lfs_box = QGroupBox(self.tr("📦 Git LFS (Large File Storage) Guidance"))
        lfs_layout = QVBoxLayout(lfs_box)
        lfs_desc = QLabel(
            self.tr(
                "Git forges (GitHub, GitLab) strictly reject individual files over 100 MB. "
                "These files should be tracked with <b>Git LFS</b>.<br><br>"
                "<i>• Note: Native Git LFS integration in Wrench is currently under "
                "development for an upcoming release.</i><br>"
                "• <b>To track with Git LFS now from terminal:</b><br>"
                '&nbsp;&nbsp;<code>git lfs install && git lfs track "*.ext" && '
                "git add .gitattributes</code><br>"
                "• <b>Or to remove the file from git tracking (keeps it on disk):</b><br>"
                "&nbsp;&nbsp;<code>git rm --cached &lt;file&gt;</code>"
            )
        )
        lfs_desc.setWordWrap(True)
        lfs_desc.setStyleSheet("font-size: 11px;")
        lfs_layout.addWidget(lfs_desc)
        layout.addWidget(lfs_box)

        # Extreme Compression Box
        comp_box = QGroupBox(self.tr("⚡ Extreme Pack Compression (7-Zip Style)"))
        comp_layout = QVBoxLayout(comp_box)
        comp_desc = QLabel(
            self.tr(
                "If pushing to a self-hosted server with higher quotas, or if the files contain "
                "compressible data (SQL dumps, CSV, logs), Wrench can compress the packfile with "
                "<b>zlib level 9 compression, deep sliding window (250), and a 500 MB buffer</b>."
            )
        )
        comp_desc.setWordWrap(True)
        comp_desc.setStyleSheet("color: palette(text); font-size: 11px;")
        comp_layout.addWidget(comp_desc)
        layout.addWidget(comp_box)

        # Button Row
        btn_layout = QHBoxLayout()
        self.cancel_btn = QPushButton(self.tr("Cancel Push (Recommended)"))
        self.cancel_btn.setDefault(True)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(self.cancel_btn)

        self.extreme_btn = QPushButton(self.tr("⚡ Push with Extreme Compression"))
        self.extreme_btn.clicked.connect(self._on_extreme)
        btn_layout.addWidget(self.extreme_btn)

        self.anyway_btn = QPushButton(self.tr("Push Anyway (Standard)"))
        self.anyway_btn.clicked.connect(self._on_anyway)
        btn_layout.addWidget(self.anyway_btn)

        layout.addLayout(btn_layout)

    def _on_cancel(self) -> None:
        self.action = "cancel"
        self.reject()

    def _on_extreme(self) -> None:
        self.action = "extreme_compression"
        self.accept()

    def _on_anyway(self) -> None:
        self.action = "standard"
        self.accept()


class GitNetworkRecoveryDialog(QDialog):
    """Guided multi-method recovery dialog for Git push network, timeout, and RPC failures."""

    def __init__(
        self,
        exc: GitNetworkTransferError,
        remote_url: str | None = None,
        unpushed_large_blobs: list[tuple[str, float]] | None = None,
        has_multiple_commits: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._exc = exc
        self._remote_url = remote_url
        self._unpushed_large_blobs = unpushed_large_blobs or []
        self._has_multiple_commits = has_multiple_commits

        self._action = "cancel"
        self._config_overrides: dict[str, str] = {}
        self._ssh_url: str | None = self._compute_ssh_url(remote_url)

        self.setWindowTitle(self.tr("Push Failed — Network / RPC Issue"))
        self.setMinimumWidth(540)

        self._init_ui()

    def _compute_ssh_url(self, url: str | None) -> str | None:
        if not url:
            return None
        m = re.match(r"^https?://([^/]+)/(.+?)(?:\.git)?$", url)
        if m:
            host = m.group(1)
            path = m.group(2)
            return f"git@{host}:{path}.git"
        return None

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(self.tr("⚠️ <b>Push was interrupted by a network or transfer error.</b>"))
        header.setStyleSheet("font-size: 13px; padding: 4px 0;")
        layout.addWidget(header)

        mb_str = f"<b>{self._exc.payload_mb:.1f} MB</b>" if self._exc.payload_mb else "large"
        diag_lines = []
        if self._exc.is_timeout:
            diag_lines.append(
                f"The remote server closed the connection (HTTP {self._exc.status_code or 408}) "
                f"while uploading a {mb_str} packfile.<br>"
                "• <b>Cause:</b> Git's default 1 MB buffer used chunked transfer "
                "that exceeded the remote 120s timeout."
            )
        elif self._exc.is_http2_error:
            diag_lines.append(
                "The connection was terminated by an HTTP/2 protocol stream error "
                f"(curl {self._exc.curl_code or 92}).<br>"
                "• <b>Cause:</b> An intermediary proxy, VPN, or firewall "
                "mishandled HTTP/2 framing on heavy data."
            )
        elif self._exc.is_payload_too_large:
            diag_lines.append(
                "The remote server rejected the payload as too large "
                f"(HTTP {self._exc.status_code or 413}).<br>"
                "• <b>Cause:</b> The push payload exceeds server-side upload quotas "
                "(e.g. Nginx <code>client_max_body_size</code>)."
            )
        elif self._exc.kind == "connection_reset_56":
            diag_lines.append(
                "The connection was forcibly reset by peer mid-transfer "
                f"(curl {self._exc.curl_code or 56}).<br>"
                "• <b>Cause:</b> Network drop, aggressive firewall inspection, "
                "or proxy buffer overflow."
            )
        else:
            diag_lines.append(
                f"Transfer disconnected unexpectedly while uploading a {mb_str} packfile."
            )

        self.info_label = QLabel("<br>".join(diag_lines))
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Large Blobs Warning (if detected)
        if self._unpushed_large_blobs:
            blob_box = QGroupBox(self.tr("Large Files Detected in This Push"))
            blob_layout = QVBoxLayout(blob_box)
            blob_list_str = "<br>".join(
                f"• <code>{path}</code> ({size_mb:.1f} MB)"
                for path, size_mb in self._unpushed_large_blobs[:5]
            )
            self.large_blobs_label = QLabel(
                f"{blob_list_str}<br><br>"
                "<i>GitHub rejects files over 100 MB (GH001). Files over 50–100 MB should be "
                "tracked with Git LFS (planned in an upcoming Wrench release).</i>"
            )
            self.large_blobs_label.setWordWrap(True)
            blob_layout.addWidget(self.large_blobs_label)
            layout.addWidget(blob_box)
        else:
            self.large_blobs_label = None

        # Auto-Heal Card (Primary)
        auto_box = QGroupBox(self.tr("Automated Recovery"))
        auto_layout = QVBoxLayout(auto_box)
        auto_desc = QLabel(
            self.tr(
                "Trials safe ephemeral parameters (Resilient 500MB buffer, HTTP/1.1 downgrade, "
                "and commit chunking) sequentially without altering your configuration "
                "until push succeeds."
            )
        )
        auto_desc.setWordWrap(True)
        auto_desc.setStyleSheet("color: palette(text); font-size: 11px;")
        auto_layout.addWidget(auto_desc)

        self.auto_heal_btn = QPushButton(self.tr("⚡ Auto-Heal Push (Recommended)"), auto_box)
        self.auto_heal_btn.setDefault(True)
        self.auto_heal_btn.clicked.connect(self._on_auto_heal)
        auto_layout.addWidget(self.auto_heal_btn)
        layout.addWidget(auto_box)

        # Advanced Manual Methods Group
        manual_box = QGroupBox(self.tr("Alternative Manual Remedies"))
        manual_layout = QVBoxLayout(manual_box)

        btn_row1 = QHBoxLayout()
        self.retry_buffer_btn = QPushButton(self.tr("Try 500 MB Buffer"))
        self.retry_buffer_btn.clicked.connect(self._on_retry_buffer)
        btn_row1.addWidget(self.retry_buffer_btn)

        self.retry_extreme_btn = QPushButton(self.tr("⚡ Extreme Compression"))
        self.retry_extreme_btn.clicked.connect(self._on_retry_extreme)
        btn_row1.addWidget(self.retry_extreme_btn)

        self.retry_http1_btn = QPushButton(self.tr("Try HTTP/1.1 Protocol"))
        self.retry_http1_btn.clicked.connect(self._on_retry_http1)
        btn_row1.addWidget(self.retry_http1_btn)
        manual_layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self.chunk_btn = QPushButton(self.tr("Push Incrementally in Batches"))
        self.chunk_btn.setEnabled(self._has_multiple_commits)
        self.chunk_btn.clicked.connect(self._on_chunk_push)
        btn_row2.addWidget(self.chunk_btn)

        self.switch_ssh_btn = QPushButton(self.tr("Switch Remote to SSH"))
        self.switch_ssh_btn.setEnabled(self._ssh_url is not None)
        self.switch_ssh_btn.clicked.connect(self._on_switch_ssh)
        btn_row2.addWidget(self.switch_ssh_btn)
        manual_layout.addLayout(btn_row2)

        layout.addWidget(manual_box)

        # Bottom row
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        cancel_btn = QPushButton(self.tr("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        bottom_row.addWidget(cancel_btn)
        layout.addLayout(bottom_row)

    def _on_auto_heal(self) -> None:
        self._action = "auto_heal"
        self.accept()

    def _on_retry_buffer(self) -> None:
        self._action = "retry_config"
        self._config_overrides = {
            "http.postBuffer": "524288000",
            "http.lowSpeedLimit": "0",
            "http.lowSpeedTime": "999999",
        }
        self.accept()

    def _on_retry_extreme(self) -> None:
        self._action = "retry_config"
        self._config_overrides = engine.EXTREME_COMPRESSION_CONFIG.copy()
        self.accept()

    def _on_retry_http1(self) -> None:
        self._action = "retry_config"
        self._config_overrides = {
            "http.version": "HTTP/1.1",
        }
        self.accept()

    def _on_chunk_push(self) -> None:
        self._action = "chunk_push"
        self.accept()

    def _on_switch_ssh(self) -> None:
        self._action = "switch_ssh"
        self.accept()

    def get_action(self) -> str:
        return self._action

    def get_config_overrides(self) -> dict[str, str]:
        return self._config_overrides

    def get_ssh_url(self) -> str | None:
        return self._ssh_url
