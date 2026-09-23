"""IssueDetailTab: Dedicated detail view for an individual issue."""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.forge.capability import ForgeAdapter
from wrench.forge.models import Issue
from wrench.forge.registry import get_adapter_for_account
from wrench.storage import db, forge_accounts
from wrench.ui.forge_panel.badges import IssueStateBadge, RemoteBadge
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class IssueDetailTab(QWidget):
    """Dynamic detail tab displaying full information and actions for an issue."""

    def __init__(
        self,
        repo_path: str,
        remote_name: str,
        issue_id: str,
        parent=None,
    ):
        super().__init__(parent)
        self.repo_path = repo_path
        self.remote_name = remote_name
        self.issue_id = issue_id
        self._issue: Issue | None = None
        self._adapter: ForgeAdapter | None = None
        self._owner = ""
        self._repo_slug = ""
        self._active_repo_path: str = repo_path

        self._init_ui()
        self._load_adapter_and_data()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(8)

        # 1. Stale Repo Informational Banner
        self.stale_banner = QFrame(self)
        self.stale_banner.setStyleSheet(
            "QFrame { background-color: #38281a; border: 1px solid #fab387; "
            "border-radius: 4px; padding: 4px; }"
        )
        stale_layout = QHBoxLayout(self.stale_banner)
        stale_layout.setContentsMargins(6, 2, 6, 2)
        self.stale_label = QLabel(self)
        self.stale_label.setStyleSheet("color: #fab387; font-size: 11px;")
        stale_layout.addWidget(self.stale_label)
        self.stale_banner.setVisible(False)
        main_layout.addWidget(self.stale_banner)

        # 2. Header Section: Title and Badges
        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)

        self.title_label = QLabel(f"Loading Issue #{self.issue_id}…", self)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label, 1)

        self.state_badge = IssueStateBadge("open", self)
        header_layout.addWidget(self.state_badge)

        self.remote_badge = RemoteBadge(self.remote_name, "forge", self)
        header_layout.addWidget(self.remote_badge)

        main_layout.addLayout(header_layout)

        # 3. Meta Subtitle (Author, Date)
        self.meta_label = QLabel(self)
        self.meta_label.setStyleSheet("color: palette(placeholder-text); font-size: 12px;")
        main_layout.addWidget(self.meta_label)

        # 4. Action Toolbar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.open_browser_btn = QPushButton("Open in Browser ↗", self)
        self.open_browser_btn.clicked.connect(self._open_in_browser)
        action_bar.addWidget(self.open_browser_btn)

        action_bar.addStretch()

        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.clicked.connect(self._load_adapter_and_data)
        action_bar.addWidget(self.refresh_btn)

        main_layout.addLayout(action_bar)

        # 5. Description Viewer
        desc_label = QLabel("Description:", self)
        desc_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        main_layout.addWidget(desc_label)

        self.desc_viewer = QTextEdit(self)
        self.desc_viewer.setReadOnly(True)
        main_layout.addWidget(self.desc_viewer, 1)

    def set_active_repository(self, active_path: str) -> None:
        """Called when user switches repositories in MainWindow."""
        self._active_repo_path = active_path
        if active_path != self.repo_path:
            self.stale_label.setText(f"ℹ Viewing issue from inactive repository: {self.repo_path}")
            self.stale_banner.setVisible(True)
        else:
            self.stale_banner.setVisible(False)

    def _load_adapter_and_data(self) -> None:
        conn = db.get_connection()
        try:
            repo_row = conn.execute(
                "SELECT id FROM repos WHERE path = ?", (self.repo_path,)
            ).fetchone()
            if not repo_row:
                self.title_label.setText("Error: Repository not found in database.")
                return

            repo_id = repo_row[0]
            links = forge_accounts.list_links_for_repo(conn, repo_id)
            link = next((lnk for lnk in links if lnk.remote_name == self.remote_name), None)
            if not link:
                self.title_label.setText(f"Error: Remote '{self.remote_name}' is not linked.")
                return

            self._owner = link.owner_slug
            self._repo_slug = link.repo_slug

            acc = forge_accounts.get_account_full(conn, link.forge_account_id)
            if not acc:
                self.title_label.setText("Error: Linked forge account not found.")
                return

            self.remote_badge.update_remote(self.remote_name, acc.provider)

            if self._adapter:
                self._adapter.close()
            self._adapter = get_adapter_for_account(acc)
        finally:
            conn.close()

        self._fetch_issue_data()

    def _fetch_issue_data(self) -> None:
        if not self._adapter:
            return

        adapter = self._adapter
        owner = self._owner
        repo = self._repo_slug
        issue_id = self.issue_id

        run_in_background(
            fn=lambda: adapter.get_issue(owner, repo, issue_id),
            on_finished=self._on_issue_loaded,
            on_failed=self._on_issue_failed,
        )

    def _on_issue_loaded(self, issue: Issue) -> None:
        self._issue = issue
        self.title_label.setText(f"#{issue.id}: {issue.title}")
        self.state_badge.set_state(issue.state)

        created = issue.created_at[:10] if issue.created_at else "Unknown date"
        self.meta_label.setText(f"Opened by {issue.author} on {created}")
        self.desc_viewer.setPlainText(issue.description or "No description provided.")

    def _on_issue_failed(self, exc: Exception) -> None:
        self.title_label.setText(f"Error loading Issue #{self.issue_id}: {exc}")
        logger.warning("Failed to load issue %s: %s", self.issue_id, exc)

    def _open_in_browser(self) -> None:
        if self._issue and self._issue.url:
            QDesktopServices.openUrl(QUrl(self._issue.url))

    def closeEvent(self, event) -> None:
        if self._adapter:
            self._adapter.close()
            self._adapter = None
        super().closeEvent(event)
