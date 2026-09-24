"""Main application window (ui-planning.md §1, Phase 1.5).

Provides:
- Native QMenuBar with File, Edit, View, Help menus
- Central TabContainer hosting ChangesTab and HistoryTab
- Window geometry and tab orientation persistence
- Quit confirmation guards for unsaved drafts and background tasks
- Status bar for repository and branch state
- Lifecycle ownership of RepoHandle and RepoWatcher
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, Qt, QTimer
from PySide6.QtGui import QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine, snapshots
from wrench.core.engine import RepoHandle
from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CLITimeoutError,
    CloneAbortedError,
    FileTooLargeRejectedError,
    GitCommandError,
    MergeRequiredError,
    ProtectedBranchRejectedError,
    PushRejectedError,
    RemoteNotFoundError,
    RepoPermissionDeniedError,
    SecretScanningRejectedError,
    SignedCommitsRequiredError,
    WorkflowScopeRequiredError,
)
from wrench.storage import repo_registry, settings
from wrench.storage.db import get_connection
from wrench.ui.dialogs.accounts_dialog import AccountsDialog
from wrench.ui.dialogs.link_dialog import LinkRepoDialog
from wrench.ui.dialogs.push_recovery_dialogs import (
    FileTooLargeDialog,
    ProtectedBranchDialog,
    SecretScanningDialog,
)
from wrench.ui.dialogs.remotes_dialog import RemotesDialog
from wrench.ui.recovery.busy_dialog import BusyOperationDialog
from wrench.ui.snapshots_panel import SnapshotsPanel
from wrench.ui.tabs.changes_tab import ChangesTab
from wrench.ui.tabs.history_tab import HistoryTab
from wrench.ui.tabs.issue_detail_tab import IssueDetailTab
from wrench.ui.tabs.issue_list_tab import IssueListTab
from wrench.ui.tabs.pr_detail_tab import PRDetailTab
from wrench.ui.tabs.pr_list_tab import PRListTab
from wrench.ui.tabs.tab_bar import TabContainer
from wrench.ui.theme import apply_theme
from wrench.ui.workers import run_in_background
from wrench.watcher.inotify_watcher import RepoWatcher

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application shell."""

    def __init__(self, conn: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wrench")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

        self._conn = conn if conn is not None else get_connection()
        self._current_repo: RepoHandle | None = None
        self._watcher: RepoWatcher | None = None
        self._repos_state: dict[str, dict] = {}
        self._is_restoring: bool = True

        # 1000ms debounce timer for coalescing auto-save writes
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1000)
        self._auto_save_timer.timeout.connect(self._save_session_state)

        # Snapshot timer (every 5 minutes / 300_000ms)
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(300_000)
        self._snapshot_timer.timeout.connect(self._on_snapshot_timer)
        self._snapshot_timer.start()

        self._current_theme_mode: str = "auto"
        style_hints = QGuiApplication.styleHints()
        if hasattr(style_hints, "colorSchemeChanged"):
            style_hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)

        self._init_ui()
        self._restore_settings()

    def _init_ui(self) -> None:
        # Central TabContainer
        self.tab_container = TabContainer(orientation=Qt.Vertical, parent=self)
        self.setCentralWidget(self.tab_container)

        # 1. Changes tab (Default pinned, user can unpin/close)
        self.changes_tab = ChangesTab(self._conn, self)
        self.changes_tab.repo_changed.connect(self._on_repo_changed)
        self.changes_tab.open_repo_dialog_requested.connect(self._on_open_repo)
        self.changes_tab.clone_repo_dialog_requested.connect(self._on_clone_repo)
        self.changes_tab.resolve_conflicts_requested.connect(self._on_resolve_conflicts)
        self.changes_tab.state_changed.connect(self._on_changes_tab_state_changed)
        self.changes_tab.forge_accounts_requested.connect(self._on_manage_forge_accounts)
        self.changes_tab.link_repo_requested.connect(self._on_link_forge)
        self.tab_container.add_tab(
            widget=self.changes_tab,
            label=self.tr("Changes"),
            tab_type="changes",
            closable=True,
            is_pinned=True,
        )

        # 2. History tab (Index 1, closable)
        self.history_tab = HistoryTab(self)
        self.history_tab.rebase_requested.connect(self._on_history_rebase)
        self.history_tab.merge_requested.connect(self._on_history_merge)
        self.history_tab.create_branch_requested.connect(self._on_history_create_branch)
        self.history_tab.create_tag_requested.connect(self._on_history_create_tag)
        self.tab_container.add_tab(
            widget=self.history_tab,
            label=self.tr("History"),
            tab_type="history",
            closable=True,
        )

        # 3. Snapshots panel instance
        self.snapshots_panel = SnapshotsPanel(self._conn, self)

        # Connect add category tab request from (+) menu
        self.tab_container.add_category_tab_requested.connect(self._on_add_category_tab)

        # Connect auto-save signals on tab changes and UI layout adjustments
        self.tab_container.current_changed.connect(lambda *_: self._schedule_auto_save())
        self.tab_container.tabs_mutated.connect(lambda *_: self._schedule_auto_save())
        self.tab_container.orientation_changed.connect(lambda *_: self._schedule_auto_save())
        self.changes_tab.splitter.splitterMoved.connect(lambda *_: self._schedule_auto_save())
        self.history_tab.graph_widget.horizontalHeader().sectionResized.connect(
            lambda *_: self._schedule_auto_save()
        )
        self.history_tab.content_splitter.splitterMoved.connect(
            lambda *_: self._schedule_auto_save()
        )

        # Menu bar

        self._create_menu_bar()

        # Status bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel(self.tr("Ready"), self.status_bar)
        self.status_bar.addWidget(self.status_label)

    def _schedule_auto_save(self) -> None:
        """Restarts the 1000ms debounce timer to batch session persistence writes."""
        if getattr(self, "_is_restoring", False):
            return
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.start()

    def _on_changes_tab_state_changed(self) -> None:
        if getattr(self, "_is_restoring", False):
            return
        if self.changes_tab._repo:
            repo_path = str(self.changes_tab._repo.path)
            self._repos_state[repo_path] = self.changes_tab.get_current_repo_state()
        self._schedule_auto_save()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_auto_save()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._schedule_auto_save()

    def _create_menu_bar(self) -> None:
        menu_bar = self.menuBar()

        # ---------------- File Menu ----------------
        file_menu = menu_bar.addMenu(self.tr("&File"))

        act_new = file_menu.addAction(self.tr("&New Repository…"))
        act_new.setShortcut(QKeySequence("Ctrl+N"))
        act_new.triggered.connect(self._on_new_repo)

        act_open = file_menu.addAction(self.tr("&Open Repository…"))
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._on_open_repo)

        act_clone = file_menu.addAction(self.tr("&Clone Repository…"))
        act_clone.setShortcut(QKeySequence("Ctrl+Shift+C"))
        act_clone.triggered.connect(self._on_clone_repo)

        file_menu.addSeparator()

        act_close = file_menu.addAction(self.tr("&Close Repository"))
        act_close.setShortcut(QKeySequence("Ctrl+W"))
        act_close.triggered.connect(self._on_close_repo)

        file_menu.addSeparator()

        act_quit = file_menu.addAction(self.tr("&Quit"))
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)

        # ---------------- Edit Menu ----------------
        edit_menu = menu_bar.addMenu(self.tr("&Edit"))

        act_undo = edit_menu.addAction(self.tr("&Undo"))
        act_undo.setShortcut(QKeySequence.Undo)
        act_redo = edit_menu.addAction(self.tr("&Redo"))
        act_redo.setShortcut(QKeySequence.Redo)

        edit_menu.addSeparator()

        act_cut = edit_menu.addAction(self.tr("Cu&t"))
        act_cut.setShortcut(QKeySequence.Cut)
        act_copy = edit_menu.addAction(self.tr("&Copy"))
        act_copy.setShortcut(QKeySequence.Copy)
        act_paste = edit_menu.addAction(self.tr("&Paste"))
        act_paste.setShortcut(QKeySequence.Paste)
        act_select_all = edit_menu.addAction(self.tr("Select &All"))
        act_select_all.setShortcut(QKeySequence.SelectAll)

        edit_menu.addSeparator()

        act_stash = edit_menu.addAction(self.tr("&Stash Changes…"))
        act_stash.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_stash.triggered.connect(self._on_stash_changes)

        act_pop_stash = edit_menu.addAction(self.tr("&Pop Stash"))
        act_pop_stash.setShortcut(QKeySequence("Ctrl+Shift+P"))
        act_pop_stash.triggered.connect(self._on_pop_stash)

        edit_menu.addSeparator()

        act_identity = edit_menu.addAction(self.tr("Git &Identity…"))
        act_identity.triggered.connect(self._on_git_identity)

        # ---------------- View Menu ----------------
        view_menu = menu_bar.addMenu(self.tr("&View"))

        self.act_toggle_tab_pos = view_menu.addAction(self.tr("&Toggle Tab Orientation"))
        self.act_toggle_tab_pos.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.act_toggle_tab_pos.triggered.connect(self._on_toggle_tab_orientation)

        view_menu.addSeparator()
        theme_menu = view_menu.addMenu(self.tr("&Theme"))
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)

        self.act_theme_auto = theme_menu.addAction(self.tr("&Auto (System Default)"))
        self.act_theme_auto.setCheckable(True)
        self.act_theme_auto.setChecked(True)
        self.act_theme_auto.triggered.connect(lambda: self._set_theme("auto"))
        self.theme_group.addAction(self.act_theme_auto)

        self.act_theme_light = theme_menu.addAction(self.tr("Pastel &Light"))
        self.act_theme_light.setCheckable(True)
        self.act_theme_light.triggered.connect(lambda: self._set_theme("light"))
        self.theme_group.addAction(self.act_theme_light)

        self.act_theme_dark = theme_menu.addAction(self.tr("Pastel &Dark"))
        self.act_theme_dark.setCheckable(True)
        self.act_theme_dark.triggered.connect(lambda: self._set_theme("dark"))
        self.theme_group.addAction(self.act_theme_dark)

        # ---------------- Repository Menu ----------------
        repo_menu = menu_bar.addMenu(self.tr("&Repository"))

        self.act_fetch = repo_menu.addAction(self.tr("&Fetch"))
        self.act_fetch.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_fetch.triggered.connect(self._on_fetch_remote)

        self.act_pull = repo_menu.addAction(self.tr("&Pull"))
        self.act_pull.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self.act_pull.triggered.connect(self._on_pull_remote)

        self.act_push = repo_menu.addAction(self.tr("&Push"))
        self.act_push.setShortcut(QKeySequence("Ctrl+Shift+U"))
        self.act_push.triggered.connect(self._on_push_remote)

        repo_menu.addSeparator()

        self.act_remotes = repo_menu.addAction(self.tr("&Remotes…"))
        self.act_remotes.triggered.connect(self._on_manage_remotes)

        repo_menu.addSeparator()

        self.act_forge_accounts = repo_menu.addAction(self.tr("Forge &Accounts…"))
        self.act_forge_accounts.triggered.connect(self._on_manage_forge_accounts)

        self.act_link_forge = repo_menu.addAction(self.tr("&Link to Forge…"))
        self.act_link_forge.triggered.connect(lambda: self._on_link_forge())

        # ---------------- Help Menu ----------------
        help_menu = menu_bar.addMenu(self.tr("&Help"))

        act_about = help_menu.addAction(self.tr("&About Wrench"))
        act_about.triggered.connect(self._on_about)

        act_report = help_menu.addAction(self.tr("&Report a Bug…"))
        act_report.triggered.connect(self._on_report_bug)

    def _restore_settings(self) -> None:
        """Restores full session state (window, tabs, orientation, active repo, selections)."""
        raw_session = settings.get_setting(self._conn, "ui.session_state")
        session_data = None
        if raw_session:
            try:
                session_data = json.loads(raw_session)
            except Exception as e:
                logger.warning("Could not parse ui.session_state JSON: %s", e)

        if session_data and isinstance(session_data, dict):
            win_data = session_data.get("window", {})
            # Tab orientation
            orient_str = win_data.get("tab_orientation", "vertical")
            if orient_str == "horizontal":
                self.tab_container.set_orientation(Qt.Horizontal)
            else:
                self.tab_container.set_orientation(Qt.Vertical)

            # Window geometry and state
            geom_hex = win_data.get("geometry_hex")
            if geom_hex:
                try:
                    self.restoreGeometry(QByteArray.fromHex(geom_hex.encode("utf-8")))
                except Exception as e:
                    logger.warning("Could not restore window geometry: %s", e)

            state_hex = win_data.get("state_hex")
            if state_hex:
                try:
                    self.restoreState(QByteArray.fromHex(state_hex.encode("utf-8")))
                except Exception as e:
                    logger.warning("Could not restore window state: %s", e)

            # Repos state cache
            self._repos_state = session_data.get("repos_state", {})
            self.changes_tab._commit_drafts.update(self._repos_state)

            # Changes tab splitter position
            splitter_hex = session_data.get("changes_tab", {}).get("splitter_hex")
            if splitter_hex:
                self.changes_tab.restore_splitter_state(splitter_hex)

            # History tab column sizes and splitter position
            hist_data = session_data.get("history_tab", {})
            hist_header_hex = hist_data.get("header_hex")
            if hist_header_hex:
                self.history_tab.restore_header_state(hist_header_hex)

            hist_splitter_hex = hist_data.get("splitter_hex")
            if hist_splitter_hex:
                self.history_tab.restore_splitter_state(hist_splitter_hex)

            # Active repository

            saved_repo_path = session_data.get("active_repo_path")
            self.changes_tab.load_repos(select_path=saved_repo_path)

            if saved_repo_path and saved_repo_path in self._repos_state:
                self.changes_tab.restore_repo_state(self._repos_state[saved_repo_path])

            # Restore open tabs
            tabs_data = session_data.get("tabs")
            if tabs_data and isinstance(tabs_data, dict):
                items = tabs_data.get("items", [])
                saved_active_idx = tabs_data.get("active_index", 0)
                if items:
                    self.tab_container.clear_tabs()
                    for item in items:
                        t_type = item.get("tab_type")
                        label = item.get("label", "")
                        closable = item.get("closable", True)
                        is_pinned = item.get("is_pinned", False)

                        if t_type == "changes":
                            self.tab_container.add_tab(
                                widget=self.changes_tab,
                                label=label or self.tr("Changes"),
                                tab_type="changes",
                                closable=closable,
                                is_pinned=is_pinned,
                            )
                        elif t_type == "history":
                            self.tab_container.add_tab(
                                widget=self.history_tab,
                                label=label or self.tr("History"),
                                tab_type="history",
                                closable=closable,
                                is_pinned=is_pinned,
                            )
                        elif t_type == "snapshots":
                            self.tab_container.add_tab(
                                widget=self.snapshots_panel,
                                label=label or self.tr("Snapshots"),
                                tab_type="snapshots",
                                closable=closable,
                                is_pinned=is_pinned,
                            )

                        elif t_type == "pr_list":
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            pr_tab = PRListTab(tab_repo, self)
                            pr_tab.pr_selected.connect(self._open_pr_detail_tab)
                            pr_tab.link_requested.connect(self._on_link_forge)
                            self.tab_container.add_tab(
                                widget=pr_tab,
                                label=label or self.tr("Pull Requests"),
                                tab_type="pr_list",
                                repo_path=tab_repo,
                                closable=closable,
                                is_pinned=is_pinned,
                            )
                        elif t_type in ("issues_list", "issue_list"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            issue_tab = IssueListTab(tab_repo, self)
                            issue_tab.issue_selected.connect(self._open_issue_detail_tab)
                            issue_tab.link_requested.connect(self._on_link_forge)
                            self.tab_container.add_tab(
                                widget=issue_tab,
                                label=label or self.tr("Issues"),
                                tab_type="issues_list",
                                repo_path=tab_repo,
                                closable=closable,
                                is_pinned=is_pinned,
                            )
                        elif t_type == "pr_detail" and item.get("entity_id"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            entity_id = item.get("entity_id", "")
                            parts = entity_id.split(":", 1)
                            if len(parts) == 2:
                                detail_tab = PRDetailTab(tab_repo, parts[0], parts[1], self)
                                detail_tab.branch_checkout_requested.connect(
                                    self._on_checkout_branch
                                )
                                self.tab_container.add_tab(
                                    widget=detail_tab,
                                    label=label or f"PR #{parts[1]}",
                                    tab_type="pr_detail",
                                    repo_path=tab_repo,
                                    entity_id=entity_id,
                                    closable=closable,
                                    is_pinned=is_pinned,
                                )
                        elif t_type == "issue_detail" and item.get("entity_id"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            entity_id = item.get("entity_id", "")
                            parts = entity_id.split(":", 1)
                            if len(parts) == 2:
                                detail_tab = IssueDetailTab(tab_repo, parts[0], parts[1], self)
                                self.tab_container.add_tab(
                                    widget=detail_tab,
                                    label=label or f"Issue #{parts[1]}",
                                    tab_type="issue_detail",
                                    repo_path=tab_repo,
                                    entity_id=entity_id,
                                    closable=closable,
                                    is_pinned=is_pinned,
                                )
                        else:
                            placeholder = QWidget(self)
                            layout = QVBoxLayout(placeholder)
                            layout.setAlignment(Qt.AlignCenter)
                            lbl = QLabel(self.tr(f"{t_type.title()} coming soon"), placeholder)
                            layout.addWidget(lbl)
                            self.tab_container.add_tab(
                                widget=placeholder,
                                label=label or t_type.title(),
                                tab_type=t_type,
                                closable=closable,
                                is_pinned=is_pinned,
                            )
                    if self.tab_container.count() > 0:
                        idx = max(0, min(saved_active_idx, self.tab_container.count() - 1))
                        self.tab_container.set_current_index(idx)
        else:
            # Fallback for initial launch or legacy settings
            saved_orientation = settings.get_setting(self._conn, "ui.tab_orientation")
            if saved_orientation == "horizontal":
                self.tab_container.set_orientation(Qt.Horizontal)
            else:
                self.tab_container.set_orientation(Qt.Vertical)

            saved_geom = settings.get_setting(self._conn, "ui.window_geometry")
            if saved_geom:
                try:
                    self.restoreGeometry(QByteArray.fromHex(saved_geom.encode("utf-8")))
                except Exception as e:
                    logger.warning("Could not restore window geometry: %s", e)

            self.changes_tab.load_repos()

        # Ensure window is visible on a valid screen
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            self.resize(1200, 800)
            if QGuiApplication.primaryScreen():
                center = QGuiApplication.primaryScreen().availableGeometry().center()
                self.move(center.x() - 600, center.y() - 400)

        # Restore theme preference
        saved_theme = settings.get_setting(self._conn, "theme") or "auto"
        self._set_theme(saved_theme)

        # Mark restoration complete and ensure no lingering auto-save timer
        self._is_restoring = False
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()

    def _set_theme(self, mode: str) -> None:
        """Applies the selected theme mode, updates UI actions, and persists setting."""
        self._current_theme_mode = mode
        app = QApplication.instance()
        if app:
            apply_theme(app, mode)
        settings.set_setting(self._conn, "theme", mode)

        if hasattr(self, "act_theme_auto"):
            if mode == "light":
                self.act_theme_light.setChecked(True)
            elif mode == "dark":
                self.act_theme_dark.setChecked(True)
            else:
                self.act_theme_auto.setChecked(True)

        self._propagate_theme_refresh()

    def _on_system_color_scheme_changed(self) -> None:
        """Reacts when desktop/system color scheme changes while in 'auto' mode."""
        if getattr(self, "_current_theme_mode", "auto") == "auto":
            app = QApplication.instance()
            if app:
                apply_theme(app, "auto")
            self._propagate_theme_refresh()

    def _propagate_theme_refresh(self) -> None:
        """Propagates theme change to all child tabs and diff views."""
        if hasattr(self, "tab_container"):
            self.tab_container.refresh_theme()
        if hasattr(self, "changes_tab"):
            self.changes_tab.refresh_theme()
        if hasattr(self, "history_tab"):
            self.history_tab.refresh_theme()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self._propagate_theme_refresh()

    def _save_session_state(self) -> None:
        """Persists the complete session state to app_settings."""
        try:
            if self.changes_tab._repo:
                repo_path = str(self.changes_tab._repo.path)
                self._repos_state[repo_path] = self.changes_tab.get_current_repo_state()

            geom_hex = self.saveGeometry().toHex().data().decode("utf-8")
            state_hex = self.saveState().toHex().data().decode("utf-8")
            orient_str = (
                "horizontal" if self.tab_container.orientation() == Qt.Horizontal else "vertical"
            )

            session_data = {
                "version": 1,
                "window": {
                    "geometry_hex": geom_hex,
                    "state_hex": state_hex,
                    "tab_orientation": orient_str,
                },
                "tabs": self.tab_container.serialize_tabs(),
                "active_repo_path": (
                    str(self.changes_tab._repo.path) if self.changes_tab._repo else None
                ),
                "changes_tab": {
                    "splitter_hex": self.changes_tab.save_splitter_state(),
                },
                "history_tab": {
                    "header_hex": self.history_tab.save_header_state(),
                    "splitter_hex": self.history_tab.save_splitter_state(),
                },
                "repos_state": self._repos_state,
            }

            settings.set_setting(self._conn, "ui.session_state", json.dumps(session_data))
            settings.set_setting(self._conn, "ui.window_geometry", geom_hex)
            settings.set_setting(self._conn, "ui.tab_orientation", orient_str)
        except Exception as e:
            logger.warning("Failed to save UI session settings: %s", e)

    def _save_settings(self) -> None:
        """Public alias for persisting session settings."""
        self._save_session_state()

    def closeEvent(self, event) -> None:
        # Quit guard 1: Check unsaved commit draft
        if self.changes_tab.has_unsaved_commit_text():
            reply = QMessageBox.question(
                self,
                self.tr("Unsaved Commit Message"),
                self.tr(
                    "You have an uncommitted commit message in progress.\n"
                    "Are you sure you want to quit?"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return

        # Flush auto-save timer and persist session synchronously
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()
        self._save_session_state()

        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        super().closeEvent(event)

    def _on_repo_changed(self, path: str) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        try:
            self._current_repo = engine.open_repo(path)
            self.history_tab.set_repo(self._current_repo)
            self.snapshots_panel.set_repo(self._current_repo)

            # Start inotify watcher
            self._watcher = RepoWatcher(
                path,
                on_change=self.changes_tab.refresh,
                parent=self,
            )
            self._watcher.status_changed.connect(self.history_tab.refresh)
            self._watcher.status_changed.connect(self.snapshots_panel.refresh)
            self._watcher.start()

            status = getattr(self.changes_tab, "_current_status", None)
            if status:
                branch = status.branch_name or "detached"
            elif self._current_repo.pygit2_repo.head_is_detached:
                branch = "detached"
            else:
                try:
                    branch = self._current_repo.pygit2_repo.head.shorthand
                except Exception:
                    branch = "main"
            self.status_label.setText(self.tr(f"Opened: {Path(path).name} ({branch})"))

            # Restore cached draft/selections if available for this repo
            if path in self._repos_state:
                self.changes_tab.restore_repo_state(self._repos_state[path])

            # Trigger background reachability probing for all remotes
            try:
                engine.probe_remotes_async(self._current_repo, db_conn=self._conn)
            except Exception as probe_err:
                logger.debug("Remotes reachability probe skipped: %s", probe_err)

            # Notify open tabs of repo change
            for i in range(self.tab_container.count()):
                w = self.tab_container.widget(i)
                meta = self.tab_container.tab_metadata(i)
                if meta and meta.tab_type in ("pr_list", "issues_list", "issue_list"):
                    self.tab_container.update_tab_repo_path(i, path)
                if hasattr(w, "set_active_repository"):
                    w.set_active_repository(path)
                elif hasattr(w, "reload_links_and_data") and getattr(w, "repo_path", None) == path:
                    w.reload_links_and_data()

            self._schedule_auto_save()
        except Exception as e:
            logger.error("Error setting up repo watcher: %s", e)
            self.status_label.setText(self.tr(f"Error opening repository: {e}"))

    def _on_new_repo(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Directory for New Repository"),
        )
        if not dir_path:
            return

        try:
            engine.init_repo(dir_path)
            repo_registry.add_repo(self._conn, dir_path, Path(dir_path).name)
            self.changes_tab.load_repos(select_path=dir_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Init Failed"),
                self.tr(f"Could not initialize repository at '{dir_path}': {e}"),
            )

    def _on_open_repo(self) -> None:
        dir_path = QFileDialog.getExistingDirectory(self, self.tr("Open Git Repository"))
        if not dir_path:
            return

        try:
            engine.open_repo(dir_path)
            repo_registry.add_repo(self._conn, dir_path, Path(dir_path).name)
            self.changes_tab.load_repos(select_path=dir_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Open Failed"),
                self.tr(f"'{dir_path}' is not a valid Git repository: {e}"),
            )

    def _on_clone_repo(self) -> None:
        url, ok = QInputDialog.getText(
            self,
            self.tr("Clone Repository"),
            self.tr("Repository URL (HTTPS or SSH):"),
        )
        if not ok or not url.strip():
            return

        clean_url = url.strip()
        repo_name = clean_url.rstrip("/").split("/")[-1].replace(".git", "")
        dest_parent = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Destination Folder"),
        )
        if not dest_parent:
            return

        target_dest = str(Path(dest_parent) / repo_name)
        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Clone Repository"),
            self.tr(f"Cloning {clean_url}..."),
            cancel_event=cancel_event,
            parent=self,
        )

        def on_finished(_res):
            busy_dlg.accept()
            repo_registry.add_repo(self._conn, target_dest, repo_name)
            self.changes_tab.load_repos(select_path=target_dest)
            self._on_repo_changed(target_dest)

        def on_failed(exc):
            busy_dlg.reject()
            self._route_remote_error(exc, "origin", op="clone")

        busy_dlg.show()
        run_in_background(
            engine.clone_repo,
            clean_url,
            Path(target_dest),
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=busy_dlg.set_progress,
            cancel_event=cancel_event,
        )

    def _get_default_remote(self) -> str | None:
        if not self._current_repo:
            return None
        remotes = [r.name for r in self._current_repo.pygit2_repo.remotes]
        if not remotes:
            return None

        # Check if active branch has an upstream tracking remote configured
        branch_name = self._get_current_branch()
        if branch_name:
            # 1. Check git config 'branch.<branch>.remote' directly
            try:
                cfg_key = f"branch.{branch_name}.remote"
                if cfg_key in self._current_repo.pygit2_repo.config:
                    cfg_remote = self._current_repo.pygit2_repo.config[cfg_key]
                    if cfg_remote in remotes:
                        return cfg_remote
            except Exception:
                pass

            # 2. Check pygit2 branch object upstream references
            try:
                branch = self._current_repo.pygit2_repo.branches.get(branch_name)
                if branch:
                    if branch.upstream:
                        remote_name = getattr(branch.upstream, "remote_name", None)
                        if remote_name and remote_name in remotes:
                            return remote_name
                    try:
                        upstream_name = getattr(branch, "upstream_name", None)
                        if upstream_name and upstream_name.startswith("refs/remotes/"):
                            parts = upstream_name[len("refs/remotes/") :].split("/")
                            if parts and parts[0] in remotes:
                                return parts[0]
                    except Exception:
                        pass
            except Exception:
                pass

        if "origin" in remotes:
            return "origin"
        return remotes[0]

    def _get_current_branch(self) -> str | None:
        if not self._current_repo:
            return None
        try:
            if self._current_repo.pygit2_repo.head_is_detached:
                return None
            return self._current_repo.pygit2_repo.head.shorthand
        except Exception:
            return None

    def _refresh_after_git_op(self) -> None:
        """Force full UI refresh after remote or write git operation."""
        if hasattr(self, "changes_tab"):
            self.changes_tab.refresh()
        if hasattr(self, "history_tab"):
            self.history_tab.refresh()
        if hasattr(self, "snapshots_panel"):
            self.snapshots_panel.refresh()
        if self._current_repo:
            try:
                status = getattr(self.changes_tab, "_current_status", None)
                if status:
                    branch = status.branch_name or "detached"
                elif self._current_repo.pygit2_repo.head_is_detached:
                    branch = "detached"
                else:
                    try:
                        branch = self._current_repo.pygit2_repo.head.shorthand
                    except Exception:
                        branch = "main"
                self.status_label.setText(
                    self.tr(f"Opened: {self._current_repo.path.name} ({branch})")
                )
            except Exception:
                pass

    def _on_manage_remotes(self) -> None:
        if not self._current_repo:
            QMessageBox.information(
                self,
                self.tr("No Repository Open"),
                self.tr("Please open a repository first to manage remotes."),
            )
            return
        dlg = RemotesDialog(self._current_repo, parent=self, db_conn=self._conn, auto_probe=True)
        dlg.exec()
        self._refresh_after_git_op()

    def _on_fetch_remote(self) -> None:
        if not self._current_repo:
            return
        remote = self._get_default_remote()
        if not remote:
            ret = QMessageBox.question(
                self,
                self.tr("No Remotes"),
                self.tr("No remotes are configured. Would you like to add one?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if ret == QMessageBox.StandardButton.Yes:
                self._on_manage_remotes()
            return

        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Fetch"),
            self.tr(f"Fetching from '{remote}'..."),
            cancel_event=cancel_event,
            parent=self,
        )

        def on_finished(_res):
            busy_dlg.accept()
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Fetched from '{remote}'."))

        def on_failed(exc):
            busy_dlg.reject()
            self._route_remote_error(exc, remote, op="fetch")

        busy_dlg.show()
        run_in_background(
            engine.fetch,
            self._current_repo,
            remote,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=busy_dlg.set_progress,
            cancel_event=cancel_event,
        )

    def _on_pull_remote(self) -> None:
        if not self._current_repo:
            return
        remote = self._get_default_remote()
        if not remote:
            self._on_manage_remotes()
            return
        branch = self._get_current_branch()
        if not branch:
            QMessageBox.warning(
                self,
                self.tr("Detached HEAD"),
                self.tr("Cannot pull while HEAD is detached."),
            )
            return

        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Pull"),
            self.tr(f"Pulling branch '{branch}' from '{remote}'..."),
            cancel_event=cancel_event,
            parent=self,
        )

        def on_finished(_res):
            busy_dlg.accept()
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Pulled '{branch}' from '{remote}'."))

        def on_failed(exc):
            busy_dlg.reject()
            self._route_remote_error(exc, remote, branch=branch, op="pull")

        busy_dlg.show()
        run_in_background(
            engine.pull,
            self._current_repo,
            remote,
            branch,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=busy_dlg.set_progress,
            cancel_event=cancel_event,
        )

    def _on_push_remote(self, *, force: bool = False) -> None:
        if not self._current_repo:
            return
        remote = self._get_default_remote()
        if not remote:
            self._on_manage_remotes()
            return
        branch = self._get_current_branch()
        if not branch:
            QMessageBox.warning(
                self,
                self.tr("Detached HEAD"),
                self.tr("Cannot push while HEAD is detached."),
            )
            return

        cancel_event = threading.Event()
        title = self.tr("Force Push") if force else self.tr("Push")
        busy_dlg = BusyOperationDialog(
            title,
            self.tr(f"Pushing branch '{branch}' to '{remote}'..."),
            cancel_event=cancel_event,
            parent=self,
        )

        def on_finished(_res):
            busy_dlg.accept()
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Pushed '{branch}' to '{remote}'."))

        def on_failed(exc):
            busy_dlg.reject()
            self._route_remote_error(exc, remote, branch=branch, op="push")

        busy_dlg.show()
        run_in_background(
            engine.push,
            self._current_repo,
            remote,
            branch,
            force=force,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=busy_dlg.set_progress,
            cancel_event=cancel_event,
        )

    def _route_remote_error(
        self,
        exc: Exception,
        remote_name: str,
        branch: str | None = None,
        op: str = "remote",
    ) -> None:
        if isinstance(exc, CloneAbortedError):
            return

        if isinstance(exc, AuthRequiredError):
            QMessageBox.warning(
                self,
                self.tr("Authentication Required"),
                self.tr(
                    f"No credentials found for host '{exc.host}'.\n"
                    "Please configure credentials for this host in your Git settings "
                    "or forge account."
                ),
            )
            return

        if isinstance(exc, AuthFailedError):
            QMessageBox.critical(
                self,
                self.tr("Authentication Failed"),
                self.tr(
                    f"Stored credentials for host '{exc.host}' were rejected.\n"
                    "Please check your account token or SSH keys."
                ),
            )
            return

        if isinstance(exc, WorkflowScopeRequiredError):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(self.tr("Workflow Scope Required"))
            box.setText(
                self.tr(
                    f"Push to '{remote_name}' was rejected because GitHub requires the "
                    "'workflow' OAuth scope to create or modify GitHub Actions workflow files "
                    "(such as .github/workflows/ci.yml).\n\n"
                    "Please re-authenticate your GitHub account with 'Full Access' "
                    "or configure a Personal Access Token with the 'workflow' scope enabled."
                )
            )
            reauth_btn = box.addButton(
                self.tr("Manage Accounts…"), QMessageBox.ButtonRole.ActionRole
            )
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() == reauth_btn:
                self._on_manage_forge_accounts()
            return

        if isinstance(exc, SecretScanningRejectedError):
            dlg = SecretScanningDialog(exc, parent=self)
            dlg.exec()
            return

        if isinstance(exc, ProtectedBranchRejectedError):
            default_branch = f"patch-{branch}" if branch else "patch-1"
            dlg = ProtectedBranchDialog(exc, default_new_branch=default_branch, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                new_branch = dlg.get_new_branch_name()
                if new_branch and self._current_repo:
                    try:
                        engine.create_branch(self._current_repo, new_branch)
                        engine.switch_branch(self._current_repo, new_branch)
                        self._refresh_after_git_op()
                        self._on_push_remote(force=False)
                    except Exception as e:
                        QMessageBox.critical(
                            self,
                            self.tr("Branch Creation Failed"),
                            str(e),
                        )
            return

        if isinstance(exc, FileTooLargeRejectedError):
            dlg = FileTooLargeDialog(exc, parent=self)
            dlg.exec()
            return

        if isinstance(exc, SignedCommitsRequiredError):
            QMessageBox.warning(
                self,
                self.tr("Signed Commits Required"),
                self.tr(
                    f"Push to '{remote_name}' was rejected because this branch "
                    "requires signed commits (GH008).\n\n"
                    "To resolve this:\n"
                    "1. Configure GPG or SSH commit signing in your git config\n"
                    "2. Sign your commits with 'git commit -S'\n"
                    "3. Push again"
                ),
            )
            return

        if isinstance(exc, RepoPermissionDeniedError):
            QMessageBox.critical(
                self,
                self.tr("Permission Denied"),
                self.tr(
                    f"You do not have write access to push to '{remote_name}'.\n\n"
                    "Check that your account has the necessary permissions "
                    "for this repository."
                ),
            )
            return

        if isinstance(exc, PushRejectedError):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(self.tr("Push Rejected"))
            box.setText(
                self.tr(
                    f"Push to '{remote_name}' was rejected because the remote contains "
                    "work that you do not have locally.\n\n"
                    "Would you like to fetch from the remote and retry, or force push with lease?"
                )
            )
            fetch_btn = box.addButton(self.tr("Fetch && Retry"), QMessageBox.ButtonRole.ActionRole)
            force_btn = box.addButton(
                self.tr("Force Push (with lease)"), QMessageBox.ButtonRole.DestructiveRole
            )
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()

            clicked = box.clickedButton()
            if clicked == fetch_btn:
                cancel_event = threading.Event()
                fetch_dlg = BusyOperationDialog(
                    self.tr("Fetch & Retry"),
                    self.tr(f"Fetching from '{remote_name}' before retrying push..."),
                    cancel_event=cancel_event,
                    parent=self,
                )

                def on_fetch_done(_):
                    fetch_dlg.accept()
                    self._refresh_after_git_op()
                    self._on_push_remote(force=False)

                def on_fetch_failed(e):
                    fetch_dlg.reject()
                    self._route_remote_error(e, remote_name, branch=branch, op="fetch")

                fetch_dlg.show()
                run_in_background(
                    engine.fetch,
                    self._current_repo,
                    remote_name,
                    on_finished=on_fetch_done,
                    on_failed=on_fetch_failed,
                    on_progress=fetch_dlg.set_progress,
                    cancel_event=cancel_event,
                )
            elif clicked == force_btn:
                self._on_push_remote(force=True)
            return

        if isinstance(exc, MergeRequiredError):
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(self.tr("Merge Required"))
            box.setText(
                self.tr(
                    f"Pull cannot fast-forward because your local branch has diverged from "
                    f"'{remote_name}/{branch}'.\n\n"
                    "How would you like to reconcile the branches?"
                )
            )
            merge_btn = box.addButton(self.tr("Merge"), QMessageBox.ButtonRole.ActionRole)
            rebase_btn = box.addButton(self.tr("Rebase"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()

            clicked = box.clickedButton()
            target_ref = f"{remote_name}/{branch}" if branch else remote_name
            if clicked == merge_btn:
                self._on_history_merge(target_ref)
            elif clicked == rebase_btn:
                self._on_history_rebase(target_ref)
            return

        if isinstance(exc, RemoteNotFoundError):
            QMessageBox.warning(
                self,
                self.tr("Remote Not Found"),
                self.tr(f"Remote '{remote_name}' was not found. Opening Remotes settings..."),
            )
            self._on_manage_remotes()
            return

        if isinstance(exc, CLITimeoutError):
            QMessageBox.critical(
                self,
                self.tr("Operation Timed Out"),
                self.tr(f"The Git operation timed out after {exc.timeout}s."),
            )
            return

        msg = exc.stderr if isinstance(exc, GitCommandError) and exc.stderr else str(exc)
        QMessageBox.critical(
            self,
            self.tr(f"{op.capitalize()} Failed"),
            self.tr(f"Git operation failed: {msg}"),
        )

    def _on_close_repo(self) -> None:
        current_idx = self.tab_container.current_index()
        meta = self.tab_container.tab_metadata(current_idx)
        if meta and meta.closable:
            self.tab_container.remove_tab(current_idx)
            return

        if self._current_repo:
            self._current_repo = None
            if self._watcher:
                self._watcher.stop()
                self._watcher = None
            self.changes_tab.set_repo(None)
            self.history_tab.set_repo(None)
            self.snapshots_panel.set_repo(None)
            self.status_label.setText(self.tr("Repository closed"))

    def _on_stash_changes(self) -> None:
        if not self._current_repo:
            return
        msg, ok = QInputDialog.getText(
            self,
            self.tr("Stash Changes"),
            self.tr("Stash message (optional):"),
        )
        if ok:
            try:
                engine.stash_create(self._current_repo, msg.strip() or None)
                self.changes_tab.refresh()
                self.status_label.setText(self.tr("Stash created"))
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Stash Failed"),
                    self.tr(f"Could not stash changes: {e}"),
                )

    def _on_pop_stash(self) -> None:
        if not self._current_repo:
            return
        try:
            engine.stash_pop(self._current_repo, 0)
            self.changes_tab.refresh()
            self.status_label.setText(self.tr("Stash popped"))
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Pop Stash Failed"),
                self.tr(f"Could not pop stash: {e}"),
            )

    def _on_git_identity(self) -> None:
        if not self._current_repo:
            return
        name, ok1 = QInputDialog.getText(
            self,
            self.tr("Git Identity"),
            self.tr("User name:"),
        )
        if not ok1:
            return
        email, ok2 = QInputDialog.getText(
            self,
            self.tr("Git Identity"),
            self.tr("User email:"),
        )
        if not ok2:
            return

        try:
            engine.set_identity(self._current_repo, name.strip(), email.strip())
            QMessageBox.information(
                self,
                self.tr("Identity Updated"),
                self.tr("Repository git identity saved successfully."),
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Identity Update Failed"),
                self.tr(f"Could not save identity: {e}"),
            )

    def _on_toggle_tab_orientation(self) -> None:
        new_orient = (
            Qt.Horizontal if self.tab_container.orientation() == Qt.Vertical else Qt.Vertical
        )
        self.tab_container.set_orientation(new_orient)

    def _on_add_category_tab(self, tab_type: str) -> None:
        if tab_type == "changes":
            if self.tab_container.find_tab("changes", "") is None:
                self.tab_container.add_tab(
                    widget=self.changes_tab,
                    label=self.tr("Changes"),
                    tab_type="changes",
                    closable=True,
                )
        elif tab_type == "history":
            if self.tab_container.find_tab("history", "") is None:
                self.tab_container.add_tab(
                    widget=self.history_tab,
                    label=self.tr("History"),
                    tab_type="history",
                    closable=True,
                )
        elif tab_type == "snapshots":
            if self.tab_container.find_tab("snapshots", "") is None:
                self.tab_container.add_tab(
                    widget=self.snapshots_panel,
                    label=self.tr("Snapshots"),
                    tab_type="snapshots",
                    closable=True,
                )
        elif tab_type == "pr_list":
            repo_path = str(self._current_repo.path) if self._current_repo else ""
            idx = self.tab_container.find_tab("pr_list", repo_path)
            if idx is None:
                pr_tab = PRListTab(repo_path, self)
                pr_tab.pr_selected.connect(self._open_pr_detail_tab)
                pr_tab.link_requested.connect(self._on_link_forge)
                self.tab_container.add_tab(
                    widget=pr_tab,
                    label=self.tr("Pull Requests"),
                    tab_type="pr_list",
                    repo_path=repo_path,
                    closable=True,
                )
            else:
                self.tab_container.set_current_index(idx)
        elif tab_type in ("issues_list", "issue_list"):
            repo_path = str(self._current_repo.path) if self._current_repo else ""
            idx = self.tab_container.find_tab("issues_list", repo_path)
            if idx is None:
                issue_tab = IssueListTab(repo_path, self)
                issue_tab.issue_selected.connect(self._open_issue_detail_tab)
                issue_tab.link_requested.connect(self._on_link_forge)
                self.tab_container.add_tab(
                    widget=issue_tab,
                    label=self.tr("Issues"),
                    tab_type="issues_list",
                    repo_path=repo_path,
                    closable=True,
                )
            else:
                self.tab_container.set_current_index(idx)
        else:
            placeholder = QWidget(self)
            layout = QVBoxLayout(placeholder)
            layout.setAlignment(Qt.AlignCenter)
            label_text = f"{tab_type.replace('_', ' ').title()}"
            label = QLabel(self.tr(label_text), placeholder)
            layout.addWidget(label)
            self.tab_container.add_tab(
                widget=placeholder,
                label=tab_type.replace("_", " ").title(),
                tab_type=tab_type,
                closable=True,
            )

    def _on_manage_forge_accounts(self) -> None:
        dlg = AccountsDialog(self)
        dlg.exec()
        self._refresh_forge_tabs()

    def _on_link_forge(self, repo_path: str = "") -> None:
        target_path = repo_path or (str(self._current_repo.path) if self._current_repo else "")
        if not target_path:
            QMessageBox.information(
                self,
                self.tr("No Active Repository"),
                self.tr("Please open a repository first to link it to a forge account."),
            )
            return
        dlg = LinkRepoDialog(target_path, self)
        dlg.links_changed.connect(self._refresh_forge_tabs)
        dlg.exec()

    def _refresh_forge_tabs(self) -> None:
        for i in range(self.tab_container.count()):
            w = self.tab_container.widget(i)
            if hasattr(w, "reload_links_and_data"):
                w.reload_links_and_data()

    def _open_pr_detail_tab(self, repo_path: str, remote_name: str, pr_id: str) -> None:
        entity_id = f"{remote_name}:{pr_id}"
        idx = self.tab_container.find_tab("pr_detail", repo_path, entity_id)
        if idx is not None:
            self.tab_container.set_current_index(idx)
            return

        detail_tab = PRDetailTab(repo_path, remote_name, pr_id, self)
        detail_tab.branch_checkout_requested.connect(self._on_checkout_branch)
        if self._current_repo:
            detail_tab.set_active_repository(str(self._current_repo.path))

        self.tab_container.add_tab(
            widget=detail_tab,
            label=f"PR #{pr_id}",
            tab_type="pr_detail",
            repo_path=repo_path,
            entity_id=entity_id,
            closable=True,
        )

    def _open_issue_detail_tab(self, repo_path: str, remote_name: str, issue_id: str) -> None:
        entity_id = f"{remote_name}:{issue_id}"
        idx = self.tab_container.find_tab("issue_detail", repo_path, entity_id)
        if idx is not None:
            self.tab_container.set_current_index(idx)
            return

        detail_tab = IssueDetailTab(repo_path, remote_name, issue_id, self)
        if self._current_repo:
            detail_tab.set_active_repository(str(self._current_repo.path))

        self.tab_container.add_tab(
            widget=detail_tab,
            label=f"Issue #{issue_id}",
            tab_type="issue_detail",
            repo_path=repo_path,
            entity_id=entity_id,
            closable=True,
        )

    def _on_checkout_branch(self, branch_name: str) -> None:
        self.status_label.setText(self.tr(f"Switched to branch: {branch_name}"))
        self.changes_tab.refresh()
        self.history_tab.refresh()

    def _on_resolve_conflicts(self) -> None:
        self.changes_tab._resolve_conflicts()

    def _on_snapshot_timer(self) -> None:
        if self._current_repo:
            try:
                snapshots.take_snapshot(self._current_repo, "timer", conn=self._conn)
            except Exception as e:
                logger.debug("Automatic periodic snapshot skipped: %s", e)

    def _on_history_rebase(self, target_ref: str) -> None:
        if not self._current_repo:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Rebase Branch"),
            self.tr(f"Rebase current branch onto '{target_ref}'?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            res = engine.rebase(self._current_repo, target_ref)
            if res.status == "conflict":
                n_conflicts = len(res.conflicted_files)
                QMessageBox.warning(
                    self,
                    self.tr("Rebase Conflict"),
                    self.tr(
                        f"Rebase encountered conflicts in {n_conflicts} file(s). "
                        "Please resolve them in the Changes tab."
                    ),
                )
                idx = self.tab_container.find_tab("changes", "")
                if idx is not None:
                    self.tab_container.set_current_index(idx)
            else:
                self.status_label.setText(self.tr("Rebase completed successfully."))
            self.changes_tab.refresh()
            self.history_tab.refresh()
        except Exception as e:
            logger.exception("Rebase failed: %s", e)
            QMessageBox.critical(self, self.tr("Rebase Failed"), str(e))

    def _on_history_merge(self, source_ref: str) -> None:
        if not self._current_repo:
            return
        reply = QMessageBox.question(
            self,
            self.tr("Merge Branch"),
            self.tr(f"Merge '{source_ref}' into current branch?"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            res = engine.merge(self._current_repo, source_ref)
            if res.status == "conflict":
                n_conflicts = len(res.conflicted_files)
                QMessageBox.warning(
                    self,
                    self.tr("Merge Conflict"),
                    self.tr(
                        f"Merge encountered conflicts in {n_conflicts} file(s). "
                        "Please resolve them in the Changes tab."
                    ),
                )

                idx = self.tab_container.find_tab("changes", "")
                if idx is not None:
                    self.tab_container.set_current_index(idx)
            elif res.status == "up_to_date":
                self.status_label.setText(self.tr("Already up to date."))
            else:
                self.status_label.setText(self.tr("Merged successfully."))
            self.changes_tab.refresh()
            self.history_tab.refresh()
        except Exception as e:
            logger.exception("Merge failed: %s", e)
            QMessageBox.critical(self, self.tr("Merge Failed"), str(e))

    def _on_history_create_branch(self, from_sha: str) -> None:
        if not self._current_repo:
            return
        name, ok = QInputDialog.getText(
            self,
            self.tr("Create Branch"),
            self.tr(f"Create new branch from '{from_sha[:8]}':\nBranch name:"),
        )
        if not ok or not name.strip():
            return

        try:
            engine.create_branch(self._current_repo, name.strip(), from_ref=from_sha)
            self.history_tab.refresh()
            self.changes_tab.refresh()
        except Exception as e:
            logger.exception("Create branch failed: %s", e)
            QMessageBox.critical(self, self.tr("Create Branch Failed"), str(e))

    def _on_history_create_tag(self, from_sha: str) -> None:
        if not self._current_repo:
            return
        name, ok = QInputDialog.getText(
            self,
            self.tr("Create Tag"),
            self.tr(f"Create tag pointing to '{from_sha[:8]}':\nTag name:"),
        )
        if not ok or not name.strip():
            return

        try:
            engine.create_tag(self._current_repo, name.strip(), target=from_sha)
            self.history_tab.refresh()
        except Exception as e:
            logger.exception("Create tag failed: %s", e)
            QMessageBox.critical(self, self.tr("Create Tag Failed"), str(e))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("About Wrench"),
            self.tr(
                "<h3>Wrench</h3>"
                "<p>A native Linux desktop Git client built with Qt & PySide6.</p>"
                "<p>Version: 0.1.0<br>License: AGPL-3.0-or-later</p>"
            ),
        )

    def _on_report_bug(self) -> None:
        QMessageBox.information(
            self,
            self.tr("Report a Bug"),
            self.tr("Please file issues at: https://github.com/uzair/wrench/issues"),
        )
