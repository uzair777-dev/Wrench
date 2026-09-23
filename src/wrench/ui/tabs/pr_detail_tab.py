"""PRDetailTab: Dedicated detail view for an individual pull request."""

import logging

from PySide6.QtCore import QUrl, Signal
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

from wrench.core import write_ops
from wrench.core.engine import RepoHandle
from wrench.forge.capability import ForgeAdapter
from wrench.forge.models import CIStatus, PullRequest
from wrench.forge.registry import get_adapter_for_account
from wrench.storage import db, forge_accounts
from wrench.ui.forge_panel.badges import CIIconWidget, PRStateBadge, RemoteBadge
from wrench.ui.forge_panel.review_dialog import SubmitReviewDialog
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class PRDetailTab(QWidget):
    """Dynamic detail tab displaying full information, CI status, and actions for a pull request."""

    branch_checkout_requested = Signal(str)  # branch name

    def __init__(
        self,
        repo_path: str,
        remote_name: str,
        pr_id: str,
        parent=None,
    ):
        super().__init__(parent)
        self.repo_path = repo_path
        self.remote_name = remote_name
        self.pr_id = pr_id
        self._pr: PullRequest | None = None
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

        self.title_label = QLabel(f"Loading Pull Request #{self.pr_id}…", self)
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.title_label.setWordWrap(True)
        header_layout.addWidget(self.title_label, 1)

        self.state_badge = PRStateBadge("open", self)
        header_layout.addWidget(self.state_badge)

        self.remote_badge = RemoteBadge(self.remote_name, "forge", self)
        header_layout.addWidget(self.remote_badge)

        self.ci_icon = CIIconWidget(None, self)
        header_layout.addWidget(self.ci_icon)

        main_layout.addLayout(header_layout)

        # 3. Meta Subtitle (Author, Branches, Date)
        self.meta_label = QLabel(self)
        self.meta_label.setStyleSheet("color: palette(placeholder-text); font-size: 12px;")
        main_layout.addWidget(self.meta_label)

        # 4. Action Toolbar
        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.open_browser_btn = QPushButton("Open in Browser ↗", self)
        self.open_browser_btn.clicked.connect(self._open_in_browser)
        action_bar.addWidget(self.open_browser_btn)

        self.review_btn = QPushButton("Submit Review…", self)
        self.review_btn.clicked.connect(self._open_review_dialog)
        action_bar.addWidget(self.review_btn)

        self.checkout_btn = QPushButton("Checkout Branch", self)
        self.checkout_btn.clicked.connect(self._checkout_branch)
        action_bar.addWidget(self.checkout_btn)

        action_bar.addStretch()

        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.clicked.connect(self._load_adapter_and_data)
        action_bar.addWidget(self.refresh_btn)

        main_layout.addLayout(action_bar)

        # 5. CI Status Card
        self.ci_card = QFrame(self)
        self.ci_card.setFrameShape(QFrame.StyledPanel)
        ci_layout = QHBoxLayout(self.ci_card)
        ci_layout.setContentsMargins(8, 6, 8, 6)
        self.ci_desc_label = QLabel("CI Status: Checking…", self.ci_card)
        self.ci_desc_label.setStyleSheet("font-size: 12px;")
        ci_layout.addWidget(self.ci_desc_label, 1)

        self.ci_link_btn = QPushButton("View Build ↗", self.ci_card)
        self.ci_link_btn.setVisible(False)
        self.ci_link_btn.clicked.connect(self._open_ci_build)
        ci_layout.addWidget(self.ci_link_btn)

        main_layout.addWidget(self.ci_card)

        # 6. Description Viewer
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
            from pathlib import Path

            saved_name = Path(self.repo_path).name
            self.stale_label.setText(
                f"This tab displays data for '{saved_name}'. "
                "Switch to that repository to interact or refresh."
            )
            self.stale_banner.setVisible(True)
            self.refresh_btn.setEnabled(False)
            self.checkout_btn.setEnabled(False)
        else:
            self.stale_banner.setVisible(False)
            self.refresh_btn.setEnabled(True)
            self.checkout_btn.setEnabled(True)

    def _load_adapter_and_data(self) -> None:
        conn = db.get_connection()
        try:
            repo_row = conn.execute(
                "SELECT id FROM repos WHERE path = ?", (self.repo_path,)
            ).fetchone()
            if not repo_row:
                self.title_label.setText("Repository not found")
                return

            repo_id = repo_row[0]
            link = forge_accounts.get_link_for_remote(conn, repo_id, self.remote_name)
            if not link:
                self.title_label.setText("Remote not linked to any forge account")
                return

            acc = forge_accounts.get_account_full(conn, link.forge_account_id)
            if not acc:
                self.title_label.setText("Configured account no longer exists")
                return

            self._owner = link.owner_slug
            self._repo_slug = link.repo_slug
            self.remote_badge.update_remote(self.remote_name, acc.provider)

            if self._adapter:
                self._adapter.close()
            self._adapter = get_adapter_for_account(acc)
        finally:
            conn.close()

        self._fetch_pr_details()

    def _fetch_pr_details(self) -> None:
        if not self._adapter:
            return

        adapter = self._adapter
        owner = self._owner
        repo = self._repo_slug

        # Fetch list to find this specific PR
        run_in_background(
            fn=lambda: adapter.list_pull_requests(owner, repo, state="all"),
            on_finished=self._on_pr_loaded,
            on_failed=self._on_error,
        )

    def _on_pr_loaded(self, prs: list[PullRequest]) -> None:
        target_pr = next((p for p in prs if p.id == self.pr_id), None)
        if not target_pr:
            self.title_label.setText(f"Pull Request #{self.pr_id} not found on remote")
            return

        self._pr = target_pr
        self.title_label.setText(f"#{target_pr.id}: {target_pr.title}")
        self.state_badge.set_state(target_pr.state)
        self.meta_label.setText(
            f"Opened by {target_pr.author} · {target_pr.source_branch} → "
            f"{target_pr.target_branch} · {target_pr.created_at[:10]}"
        )
        self.desc_viewer.setPlainText(target_pr.description or "No description provided.")

        # Trigger CI status fetch
        if self._adapter and target_pr.source_branch:
            adapter = self._adapter
            owner = self._owner
            repo = self._repo_slug
            run_in_background(
                fn=lambda: adapter.get_ci_status(owner, repo, target_pr.source_branch),
                on_finished=self._on_ci_loaded,
                on_failed=lambda _: self._on_ci_loaded(CIStatus(state="unknown")),
            )

    def _on_ci_loaded(self, status: CIStatus) -> None:
        self.ci_icon.set_status(status)
        desc = status.description or f"State: {status.state.capitalize()}"
        self.ci_desc_label.setText(f"CI Status: {desc}")
        if status.url:
            self.ci_link_btn.setProperty("ci_url", status.url)
            self.ci_link_btn.setVisible(True)
        else:
            self.ci_link_btn.setVisible(False)

    def _on_error(self, exc: Exception) -> None:
        self.title_label.setText(f"Failed to load PR: {exc}")

    def _open_in_browser(self) -> None:
        if self._pr and self._pr.url:
            QDesktopServices.openUrl(QUrl(self._pr.url))

    def _open_ci_build(self) -> None:
        url = self.ci_link_btn.property("ci_url")
        if url:
            QDesktopServices.openUrl(QUrl(str(url)))

    def _open_review_dialog(self) -> None:
        if not self._adapter or not self._pr:
            return

        dlg = SubmitReviewDialog(
            self._adapter,
            self._owner,
            self._repo_slug,
            int(self.pr_id),
            parent=self,
        )
        dlg.review_submitted.connect(self._load_adapter_and_data)
        dlg.exec()

    def _checkout_branch(self) -> None:
        if not self._pr or not self._pr.source_branch:
            return
        branch_name = self._pr.source_branch
        try:
            repo_handle = RepoHandle(self.repo_path)
            # Switch to local branch if it exists, or create local tracking branch
            if branch_name in repo_handle.pygit2_repo.branches.local:
                write_ops.checkout_branch(repo_handle, branch_name)
            else:
                remote_ref = f"{self.remote_name}/{branch_name}"
                if remote_ref in repo_handle.pygit2_repo.branches.remote:
                    write_ops.create_branch(repo_handle, branch_name, remote_ref)
                    write_ops.checkout_branch(repo_handle, branch_name)
            self.branch_checkout_requested.emit(branch_name)
        except Exception as e:
            logger.error("Checkout failed for branch %s: %s", branch_name, e)
