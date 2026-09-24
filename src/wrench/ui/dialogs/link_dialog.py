"""FR-5.6 / FR-8.7: Link Repository to Forge Account Dialog."""

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine, identity
from wrench.core.engine import RepoHandle
from wrench.core.remote_urls import parse_remote_url
from wrench.forge.registry import create_adapter
from wrench.storage import db, forge_accounts
from wrench.ui.dialogs.accounts_dialog import AccountsDialog
from wrench.ui.workers import run_in_background

logger = logging.getLogger(__name__)


class LinkRepoDialog(QDialog):
    """Modal dialog to inspect repository remotes and link them to forge accounts."""

    links_changed = Signal()

    def __init__(self, repo_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.repo_path = repo_path
        self.setWindowTitle("Link Repository to Forge Account")
        self.resize(720, 380)

        self._repo_id: int | None = None
        self._accounts: list[forge_accounts.ForgeAccountRecord] = []
        self._remotes: list[engine.RemoteInfo] = []
        self._existing_links: dict[str, forge_accounts.RepoForgeLink] = {}
        # Mapping from row index to remote data: (remote_name, host, owner, repo)
        self._row_data: dict[int, tuple[str, str, str, str]] = {}
        self._combos: dict[int, QComboBox] = {}

        self._init_ui()
        self.reload_data()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        desc_label = QLabel(
            "Associate Git remotes with your configured forge accounts. "
            "Linking enables PR reviews, issue tracking, and automatically enables "
            "<code>credential.useHttpPath = true</code> to isolate credentials per-repository.",
            self,
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: palette(placeholder-text); font-size: 12px;")
        layout.addWidget(desc_label)

        # Remotes Table
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Remote", "URL", "Parsed Slug", "Linked Account"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        # Toolbar
        btn_bar = QHBoxLayout()

        self.manage_accounts_btn = QPushButton("Manage Accounts…", self)
        self.manage_accounts_btn.clicked.connect(self._open_accounts_manager)
        btn_bar.addWidget(self.manage_accounts_btn)

        self.auto_match_btn = QPushButton("Auto-Match by Host", self)
        self.auto_match_btn.clicked.connect(self._auto_match_remotes)
        btn_bar.addWidget(self.auto_match_btn)

        btn_bar.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(self.cancel_btn)

        self.save_btn = QPushButton("Save Links", self)
        self.save_btn.setStyleSheet("font-weight: bold;")
        self.save_btn.clicked.connect(self._save_links)
        btn_bar.addWidget(self.save_btn)

        layout.addLayout(btn_bar)

    def reload_data(self) -> None:
        conn = db.get_connection()
        try:
            repo_row = conn.execute(
                "SELECT id FROM repos WHERE path = ?", (self.repo_path,)
            ).fetchone()
            if not repo_row:
                QMessageBox.critical(
                    self, "Error", f"Repository not found in database: {self.repo_path}"
                )
                self.reject()
                return

            self._repo_id = repo_row[0]
            self._accounts = forge_accounts.list_accounts(conn)
            links = forge_accounts.list_links_for_repo(conn, self._repo_id)
            self._existing_links = {lnk.remote_name: lnk for lnk in links}
        finally:
            conn.close()

        # Load git remotes
        try:
            handle = RepoHandle(self.repo_path)
            self._remotes = engine.list_remotes(handle)
        except Exception as exc:
            logger.warning("Could not list remotes for %s: %s", self.repo_path, exc)
            self._remotes = []

        self._populate_table()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self._remotes))
        self._row_data.clear()
        self._combos.clear()

        for row, remote in enumerate(self._remotes):
            name_item = QTableWidgetItem(remote.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            url_item = QTableWidgetItem(remote.url)
            url_item.setFlags(url_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 1, url_item)

            # Try to parse remote URL
            host = ""
            owner = ""
            repo = ""
            try:
                host, owner, repo = parse_remote_url(remote.url)
                slug_text = f"{owner}/{repo} ({host})"
            except ValueError:
                slug_text = "(Non-forge / Local URL)"

            self._row_data[row] = (remote.name, host, owner, repo)

            slug_item = QTableWidgetItem(slug_text)
            slug_item.setFlags(slug_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 2, slug_item)

            # Build Accounts ComboBox
            combo = QComboBox(self.table)
            combo.addItem("— Unlinked —", userData=None)

            current_link = self._existing_links.get(remote.name)
            selected_idx = 0

            for acc in self._accounts:
                label = f"{acc.label} ({acc.provider})"
                combo.addItem(label, userData=acc.id)
                if current_link and current_link.forge_account_id == acc.id:
                    selected_idx = combo.count() - 1

            combo.setCurrentIndex(selected_idx)
            self._combos[row] = combo
            self.table.setCellWidget(row, 3, combo)

    def _auto_match_remotes(self) -> None:
        """Heuristically matches each remote to an account by hostname."""
        for row, (_name, host, _owner, _repo) in self._row_data.items():
            if not host:
                continue
            combo = self._combos.get(row)
            if not combo:
                continue

            # Look for an account whose instance_url contains host
            for i in range(1, combo.count()):
                acc_id = combo.itemData(i)
                acc = next((a for a in self._accounts if a.id == acc_id), None)
                if acc and (host in acc.instance_url.lower() or acc.provider in host):
                    combo.setCurrentIndex(i)
                    break

    def _open_accounts_manager(self) -> None:
        dlg = AccountsDialog(self)
        dlg.exec()
        self.reload_data()

    def _save_links(self) -> None:
        if self._repo_id is None:
            return

        conn = db.get_connection()
        try:
            for row, (remote_name, _host, owner, repo) in self._row_data.items():
                combo = self._combos.get(row)
                if not combo:
                    continue

                account_id = combo.currentData()
                if account_id is None:
                    # Unlink if previously linked
                    if remote_name in self._existing_links:
                        forge_accounts.unlink_repo_account(conn, self._repo_id, remote_name)
                else:
                    if not owner or not repo:
                        QMessageBox.warning(
                            self,
                            "Cannot Link Remote",
                            f"Remote '{remote_name}' has an unsupported or unparseable URL. "
                            "Cannot link.",
                        )
                        return
                    forge_accounts.link_repo_to_account(
                        conn,
                        self._repo_id,
                        account_id,
                        remote_name,
                        owner,
                        repo,
                    )

                    # Auto-align local git author identity
                    _repo_path = str(self.repo_path)
                    _account_id = account_id

                    def _align_identity(
                        target_repo: str = _repo_path,
                        target_acct_id: int = _account_id,
                    ) -> None:
                        """Background: fetch email from forge and set local git identity."""
                        try:
                            from wrench.storage import db as db_mod
                            from wrench.storage import forge_accounts as fa_mod

                            c = db_mod.get_connection()
                            try:
                                acct = fa_mod.get_account_full(c, target_acct_id)
                            finally:
                                c.close()
                            if acct is None:
                                return
                            adapter = create_adapter(acct)
                            try:
                                email = adapter.get_primary_email()
                            finally:
                                adapter.close()
                            if email:
                                identity.set_identity(
                                    target_repo,
                                    acct.username or acct.label,
                                    email,
                                )
                        except Exception:
                            pass  # best-effort, don't block linking

                    run_in_background(fn=_align_identity, on_finished=lambda _: None)
        finally:
            conn.close()

        # Configure local git credential.useHttpPath = true for disambiguation
        try:
            handle = RepoHandle(self.repo_path)
            handle.pygit2_repo.config["credential.useHttpPath"] = "true"
        except Exception as exc:
            logger.warning(
                "Could not set credential.useHttpPath on repository %s: %s",
                self.repo_path,
                exc,
            )

        self.links_changed.emit()
        self.accept()
