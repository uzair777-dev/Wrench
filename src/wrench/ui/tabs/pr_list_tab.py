"""PRListTab: Virtualized table view for browsing repository pull requests."""

import logging
import time
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core.engine import RepoHandle
from wrench.forge.capability import ForgeAdapter
from wrench.forge.models import PullRequest
from wrench.forge.registry import get_adapter_for_account
from wrench.storage import db, forge_accounts
from wrench.ui.forge_panel.badges import paint_pr_state_badge
from wrench.ui.forge_panel.create_pr_dialog import CreatePRDialog
from wrench.ui.forge_panel.error_banner import ForgeErrorBanner
from wrench.ui.theme import is_dark_theme
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class PRStateDelegate(QStyledItemDelegate):
    """Paints Catppuccin Velvet pastel status pills directly on the QTableView canvas."""

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        state = index.data(Qt.DisplayRole)
        if state:
            is_dark = is_dark_theme(option.palette)
            paint_pr_state_badge(painter, option.rect, str(state), is_dark)
        else:
            super().paint(painter, option, index)


class PRTableModel(QAbstractTableModel):
    """High-performance virtualized model for pull requests."""

    COLUMNS = ["ID", "Title", "Branches", "Author", "State", "Created"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_prs: list[PullRequest] = []
        self._filtered_prs: list[PullRequest] = []

    def set_prs(self, prs: list[PullRequest]) -> None:
        self.beginResetModel()
        self._all_prs = list(prs)
        self._filtered_prs = list(prs)
        self.endResetModel()

    def filter_items(self, search_text: str) -> None:
        self.beginResetModel()
        if not search_text:
            self._filtered_prs = list(self._all_prs)
        else:
            q = search_text.lower()
            self._filtered_prs = [
                pr
                for pr in self._all_prs
                if q in pr.title.lower()
                or q in pr.id.lower()
                or q in pr.author.lower()
                or q in pr.source_branch.lower()
            ]
        self.endResetModel()

    def get_pr_at(self, row: int) -> PullRequest | None:
        if 0 <= row < len(self._filtered_prs):
            return self._filtered_prs[row]
        return None

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return len(self._filtered_prs)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return len(self.COLUMNS)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._filtered_prs)):
            return None

        pr = self._filtered_prs[index.row()]
        col = index.column()

        if role == Qt.DisplayRole:
            if col == 0:
                return f"#{pr.id}"
            if col == 1:
                return pr.title
            if col == 2:
                return f"{pr.source_branch} → {pr.target_branch}"
            if col == 3:
                return pr.author
            if col == 4:
                return pr.state
            if col == 5:
                # Return shortened date part of ISO timestamp
                return pr.created_at[:10] if pr.created_at else ""

        if role == Qt.TextAlignmentRole:
            if col in (0, 4, 5):
                return int(Qt.AlignCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)

        return None


class PRListTab(QWidget):
    """Category tab displaying pull requests for the active repository."""

    pr_selected = Signal(str, str, str)  # (repo_path, remote_name, pr_id)
    link_requested = Signal(str)  # repo_path

    def __init__(self, repo_path: str, parent=None):
        super().__init__(parent)
        self.repo_path = repo_path
        self._load_generation = 0
        self._active_link: forge_accounts.RepoForgeLink | None = None
        self._active_adapter: ForgeAdapter | None = None
        # SWR Cache: (repo_path, remote_name) -> (timestamp, items)
        self._cache: dict[tuple[str, str], tuple[float, list[PullRequest]]] = {}

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(150)
        self._debounce_timer.timeout.connect(self._on_search_debounced)

        self._init_ui()
        self.reload_links_and_data()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        # 1. Error Banner
        self.error_banner = ForgeErrorBanner(self)
        self.error_banner.action_requested.connect(self._on_error_banner_action)
        main_layout.addWidget(self.error_banner)

        # 2. Filter & Toolbar Header
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)

        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("🔍 Filter pull requests…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda: self._debounce_timer.start())
        toolbar.addWidget(self.search_input, 2)

        # Multi-Website Remote Selector
        self.remote_combo = QComboBox(self)
        self.remote_combo.currentIndexChanged.connect(self._on_remote_changed)
        toolbar.addWidget(self.remote_combo, 1)

        # State filter dropdown
        self.state_combo = QComboBox(self)
        self.state_combo.addItems(["Open", "Merged", "Closed", "All"])
        self.state_combo.currentIndexChanged.connect(self._on_state_filter_changed)
        toolbar.addWidget(self.state_combo)

        # Refresh button
        self.refresh_btn = QToolButton(self)
        self.refresh_btn.setText("🔄")
        self.refresh_btn.setToolTip("Refresh Pull Requests")
        self.refresh_btn.clicked.connect(lambda: self.load_prs(bypass_cache=True))
        toolbar.addWidget(self.refresh_btn)

        # New PR button
        self.new_pr_btn = QPushButton("+ New Pull Request", self)
        self.new_pr_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 4px 10px; }")
        self.new_pr_btn.clicked.connect(self._open_create_pr_dialog)
        toolbar.addWidget(self.new_pr_btn)

        main_layout.addLayout(toolbar)

        # 3. Virtualized Table View
        self.table_view = QTableView(self)
        self.table_model = PRTableModel(self)
        self.table_view.setModel(self.table_model)
        self.table_view.setItemDelegateForColumn(4, PRStateDelegate(self))

        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.setSelectionMode(QTableView.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.horizontalHeader().setStretchLastSection(False)
        self.table_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_view.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_view.doubleClicked.connect(self._on_row_double_clicked)
        main_layout.addWidget(self.table_view, 1)

        # 4. Empty State Widget (unlinked or 0 items)
        self.empty_widget = QWidget(self)
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(10)

        self.empty_title = QLabel("No Pull Requests", self.empty_widget)
        self.empty_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: palette(placeholder-text);"
        )
        empty_layout.addWidget(self.empty_title)

        self.empty_sub = QLabel(
            "Link this repository to a forge account to browse pull requests.", self.empty_widget
        )
        self.empty_sub.setStyleSheet("font-size: 12px; color: palette(placeholder-text);")
        empty_layout.addWidget(self.empty_sub)

        self.link_btn = QPushButton("Link Repository to Forge Account…", self.empty_widget)
        self.link_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 6px 14px; }")
        self.link_btn.clicked.connect(lambda: self.link_requested.emit(self.repo_path))
        empty_layout.addWidget(self.link_btn)

        self.empty_widget.setVisible(False)
        main_layout.addWidget(self.empty_widget, 1)

    def reload_links_and_data(self) -> None:
        """Discover all linked remotes for this repo and populate remote_combo."""
        conn = db.get_connection()
        try:
            repo_row = conn.execute(
                "SELECT id FROM repos WHERE path = ?", (self.repo_path,)
            ).fetchone()
            if not repo_row:
                self._show_unlinked_state()
                return

            repo_id = repo_row[0]
            links = forge_accounts.list_links_for_repo(conn, repo_id)
            if not links:
                self._show_unlinked_state()
                return

            self.empty_widget.setVisible(False)
            self.table_view.setVisible(True)

            self.remote_combo.blockSignals(True)
            self.remote_combo.clear()
            for link in links:
                acc = forge_accounts.get_account_full(conn, link.forge_account_id)
                label = acc.label if acc else link.remote_name
                self.remote_combo.addItem(f"{link.remote_name} ({label})", userData=link)
            self.remote_combo.blockSignals(False)

            self._active_link = links[0]
            self._setup_adapter_and_load()
        finally:
            conn.close()

    def _setup_adapter_and_load(self) -> None:
        if not self._active_link:
            return

        conn = db.get_connection()
        try:
            acc = forge_accounts.get_account_full(conn, self._active_link.forge_account_id)
            if not acc:
                self._show_unlinked_state("Linked account no longer exists.")
                return
            if self._active_adapter:
                self._active_adapter.close()
            self._active_adapter = get_adapter_for_account(acc)
        finally:
            conn.close()

        self.load_prs(bypass_cache=False)

    def load_prs(self, bypass_cache: bool = False) -> None:
        if not self._active_adapter or not self._active_link:
            return

        cache_key = (self.repo_path, self._active_link.remote_name)
        state_str = self.state_combo.currentText().lower()

        # Check SWR cache
        if not bypass_cache and cache_key in self._cache:
            ts, cached_items = self._cache[cache_key]
            self.table_model.set_prs(cached_items)
            # If cache is fresh (<60s), do not fetch
            if time.time() - ts < 60.0:
                return

        self._load_generation += 1
        gen_id = self._load_generation
        self.refresh_btn.setEnabled(False)
        self.error_banner.hide_banner()

        adapter = self._active_adapter
        owner = self._active_link.owner_slug
        repo = self._active_link.repo_slug

        run_in_background(
            fn=lambda: adapter.list_pull_requests(owner, repo, state=state_str),
            on_finished=lambda prs: self._on_prs_loaded(prs, gen_id, cache_key),
            on_failed=lambda exc: self._on_prs_failed(exc, gen_id),
        )

    def _on_prs_loaded(
        self, prs: list[PullRequest], gen_id: int, cache_key: tuple[str, str]
    ) -> None:
        if gen_id != self._load_generation:
            return

        self.refresh_btn.setEnabled(True)
        self._cache[cache_key] = (time.time(), prs)
        self.table_model.set_prs(prs)

        if not prs:
            self.empty_title.setText("No Pull Requests")
            self.empty_sub.setText("No matching pull requests found for this filter.")
            self.link_btn.setVisible(False)
            self.empty_widget.setVisible(True)
            self.table_view.setVisible(False)
        else:
            self.empty_widget.setVisible(False)
            self.table_view.setVisible(True)

    def _on_prs_failed(self, exc: Exception, gen_id: int) -> None:
        if gen_id != self._load_generation:
            return
        self.refresh_btn.setEnabled(True)
        self.error_banner.show_error(exc)

    def set_active_repository(self, active_path: str) -> None:
        """Update active repository path, reset state, and reload forge links and PRs."""
        if self.repo_path == active_path:
            return
        self.repo_path = active_path
        self._load_generation += 1
        self._cache.clear()
        if self._active_adapter:
            try:
                self._active_adapter.close()
            except Exception:
                pass
            self._active_adapter = None
        self._active_link = None
        self.search_input.clear()
        self.reload_links_and_data()

    def _show_unlinked_state(
        self, message: str = "Link this repository to a forge account."
    ) -> None:
        self.table_view.setVisible(False)
        self.table_model.set_prs([])
        self.remote_combo.blockSignals(True)
        self.remote_combo.clear()
        self.remote_combo.blockSignals(False)
        self.refresh_btn.setEnabled(False)
        self.error_banner.hide_banner()
        self.empty_title.setText("Repository Not Linked")
        self.empty_sub.setText(message)
        self.link_btn.setVisible(True)
        self.empty_widget.setVisible(True)

    def _on_remote_changed(self) -> None:
        link = self.remote_combo.currentData()
        if link and isinstance(link, forge_accounts.RepoForgeLink):
            self._active_link = link
            self._setup_adapter_and_load()

    def _on_state_filter_changed(self) -> None:
        self.load_prs(bypass_cache=True)

    def _on_search_debounced(self) -> None:
        self.table_model.filter_items(self.search_input.text().strip())

    def _on_row_double_clicked(self, index: QModelIndex) -> None:
        pr = self.table_model.get_pr_at(index.row())
        if pr and self._active_link:
            self.pr_selected.emit(self.repo_path, self._active_link.remote_name, pr.id)

    def _open_create_pr_dialog(self) -> None:
        if not self._active_adapter or not self._active_link:
            return

        # Fetch local branch list from pygit2
        try:
            repo_handle = RepoHandle(self.repo_path)
            branches = sorted(list(repo_handle.pygit2_repo.branches.local))
            current = (
                repo_handle.pygit2_repo.head.shorthand
                if not repo_handle.pygit2_repo.head_is_unborn
                else "main"
            )
        except Exception:
            branches = ["main"]
            current = "main"

        dlg = CreatePRDialog(
            self._active_adapter,
            self._active_link.owner_slug,
            self._active_link.repo_slug,
            branches=branches,
            current_branch=current,
            parent=self,
        )
        dlg.pr_created.connect(lambda _: self.load_prs(bypass_cache=True))
        dlg.exec()

    def _on_error_banner_action(self, action: str) -> None:
        if action == "retry":
            self.load_prs(bypass_cache=True)
        elif action in ("reenter_token", "edit_account"):
            self.link_requested.emit(self.repo_path)
