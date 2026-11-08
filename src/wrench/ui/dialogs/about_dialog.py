"""Phase 4.6: About dialog (Help -> About).

Standard shape, personality inside — the one surface where flavor text
is the content. Licensing-compliance NFR makes the notices pane a gate,
not garnish.
"""

import importlib.metadata
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from wrench.ui.quotes import ABOUT_WISDOM, random_quote


class AboutDialog(QDialog):
    """About dialog with application metadata, links, licenses, and rotating wisdom."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("About Wrench"))
        self.setMinimumSize(480, 440)
        self.setModal(True)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # App name
        name_label = QLabel(self.tr("Wrench"), self)
        name_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_label)

        # Version (from importlib.metadata — never hardcoded)
        try:
            version = importlib.metadata.version("wrench")
        except importlib.metadata.PackageNotFoundError:
            version = "dev"
        self.version_label = QLabel(self.tr(f"Version {version}"), self)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.version_label.setStyleSheet("color: palette(placeholder-text); font-size: 13px;")
        layout.addWidget(self.version_label)

        # One-line pitch
        pitch = QLabel(self.tr("A native Git client for Linux."), self)
        pitch.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(pitch)

        # Wisdom line (rotating from ABOUT_WISDOM)
        quote_text = random_quote(ABOUT_WISDOM)
        if isinstance(quote_text, tuple):
            quote_text = quote_text[0]
        self.wisdom_label = QLabel(self.tr(quote_text), self)
        self.wisdom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wisdom_label.setStyleSheet(
            "font-style: italic; color: palette(placeholder-text); font-size: 11px;"
        )
        self.wisdom_label.setWordWrap(True)
        layout.addWidget(self.wisdom_label)

        # Wisdom rotation timer (every 6s)
        self._wisdom_timer = QTimer(self)
        self._wisdom_timer.setInterval(6000)
        self._wisdom_timer.timeout.connect(self._rotate_wisdom)
        self._wisdom_timer.start()

        # Links row
        self.links_row = QHBoxLayout()
        self.links_row.setSpacing(12)
        self.links_row.addStretch()

        btn_github = QPushButton(self.tr("GitHub"), self)
        btn_github.setFlat(True)
        btn_github.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/uzair777-dev/Wrench"))
        )
        self.links_row.addWidget(btn_github)

        btn_issues = QPushButton(self.tr("Report Issue"), self)
        btn_issues.setFlat(True)
        btn_issues.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/uzair777-dev/Wrench/issues"))
        )
        self.links_row.addWidget(btn_issues)

        self.links_row.addStretch()
        layout.addLayout(self.links_row)

        # License & third-party notices pane
        self.license_text = QTextBrowser(self)
        self.license_text.setOpenExternalLinks(True)
        self.license_text.setMinimumHeight(140)
        self.license_text.setPlainText(self._build_license_text())
        layout.addWidget(self.license_text)

        # Bottom buttons: About Qt + Close
        btn_row = QHBoxLayout()
        btn_about_qt = QPushButton(self.tr("About Qt"), self)
        btn_about_qt.clicked.connect(QApplication.aboutQt)
        btn_row.addWidget(btn_about_qt)

        btn_row.addStretch()

        btn_close = QPushButton(self.tr("Close"), self)
        btn_close.clicked.connect(self.accept)
        btn_close.setDefault(True)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _rotate_wisdom(self) -> None:
        quote_text = random_quote(ABOUT_WISDOM)
        if isinstance(quote_text, tuple):
            quote_text = quote_text[0]
        self.wisdom_label.setText(self.tr(quote_text))

    def _build_license_text(self) -> str:
        """Build the license + third-party attribution string."""
        sections = [
            "Wrench is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).",
            "",
            "Third-Party Components & Licenses:",
            "─" * 50,
            "• Qt / PySide6 — LGPL v3 (The Qt Company)",
            "• pygit2 / libgit2 — GPL v2 with Linking Exception",
            "• httpx — BSD 3-Clause",
            "• watchdog — Apache License 2.0",
            "• SecretStorage — BSD 3-Clause",
            "• platformdirs — MIT",
            "",
        ]
        # Locate LICENSE file in parent directories
        current = Path(__file__).resolve()
        license_path = None
        for parent in current.parents:
            cand = parent / "LICENSE"
            if cand.is_file():
                license_path = cand
                break

        if license_path:
            try:
                sections.append("═" * 50)
                sections.append("Wrench License Text:")
                sections.append("═" * 50)
                sections.append(license_path.read_text(encoding="utf-8")[:4000])
            except Exception:
                pass

        return "\n".join(sections)

    def closeEvent(self, event) -> None:
        self._wisdom_timer.stop()
        super().closeEvent(event)
