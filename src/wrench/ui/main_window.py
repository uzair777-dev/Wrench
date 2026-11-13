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

import ctypes
import gc
import json
import logging
import os
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QByteArray,
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    QRunnable,
    QSignalBlocker,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QActionGroup, QGuiApplication, QKeySequence, QPixmapCache, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolButton,
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
    GitNetworkTransferError,
    MergeRequiredError,
    ProtectedBranchRejectedError,
    PushRejectedError,
    RemoteNotFoundError,
    RepoPermissionDeniedError,
    SecretScanningRejectedError,
    SignedCommitsRequiredError,
    WorkflowScopeRequiredError,
    WrenchRepoNotFoundError,
)
from wrench.core.remote_urls import host_of_instance_url, parse_remote_url
from wrench.forge.registry import close_avatar_http_client
from wrench.storage import forge_accounts, get_connection, repo_registry, settings
from wrench.storage.settings_registry import SettingScope, SettingsRegistry, get_settings_registry
from wrench.ui.dialogs.about_dialog import AboutDialog
from wrench.ui.dialogs.accounts_dialog import AccountsDialog
from wrench.ui.dialogs.clone_dialog import CloneDialog
from wrench.ui.dialogs.discover_repos_dialog import DiscoverReposDialog
from wrench.ui.dialogs.interactive_rebase_dialog import InteractiveRebaseDialog
from wrench.ui.dialogs.link_dialog import LinkRepoDialog
from wrench.ui.dialogs.push_recovery_dialogs import (
    FileTooLargeDialog,
    GitNetworkRecoveryDialog,
    PrePushLargeFilesDialog,
    ProtectedBranchDialog,
    SecretScanningDialog,
)
from wrench.ui.dialogs.remotes_dialog import RemotesDialog
from wrench.ui.dialogs.sparse_checkout_dialog import SparseCheckoutDialog
from wrench.ui.recovery.busy_dialog import BusyOperationDialog
from wrench.ui.snapshots_panel import SnapshotsPanel
from wrench.ui.tabs.changes_tab import ChangesTab
from wrench.ui.tabs.history_tab import HistoryTab
from wrench.ui.tabs.issue_detail_tab import IssueDetailTab
from wrench.ui.tabs.issue_list_tab import IssueListTab
from wrench.ui.tabs.pr_detail_tab import PRDetailTab
from wrench.ui.tabs.pr_list_tab import PRListTab
from wrench.ui.tabs.tab_bar import TabContainer
from wrench.ui.theme import (
    apply_theme,
    get_status_pill_style,
    is_dark_theme,
    normalize_theme_mode,
    repolish_widget,
)
from wrench.ui.widgets.activity_log import ActivityLogBar, ActivityLogModel
from wrench.ui.widgets.avatar import clear_author_avatar_cache
from wrench.ui.widgets.context_header_bar import ContextHeaderBar, GitTerminalDrawer
from wrench.ui.workers import clear_activity_log, run_in_background, set_activity_log
from wrench.watcher.inotify_watcher import RepoWatcher

logger = logging.getLogger(__name__)

RESTART_EXIT_CODE = 75

_MALLOC_TRIM_INITIALIZED = False
_MALLOC_TRIM_FN: Callable[[int], int] | None = None


def _get_malloc_trim() -> Callable[[int], int] | None:
    """Resolve and cache glibc malloc_trim(0) once per process."""
    global _MALLOC_TRIM_INITIALIZED, _MALLOC_TRIM_FN
    if _MALLOC_TRIM_INITIALIZED:
        return _MALLOC_TRIM_FN
    _MALLOC_TRIM_INITIALIZED = True
    try:
        libc = ctypes.CDLL("libc.so.6")
        trim = libc.malloc_trim
        trim.argtypes = [ctypes.c_size_t]
        trim.restype = ctypes.c_int
        _MALLOC_TRIM_FN = trim
    except Exception as exc:
        logger.debug("glibc malloc_trim unavailable: %s", exc)
        _MALLOC_TRIM_FN = None
    return _MALLOC_TRIM_FN


def _same_repo_path(path_a: Path | str | None, path_b: Path | str | None) -> bool:
    if path_a is None or path_b is None:
        return False
    try:
        return Path(path_a).resolve() == Path(path_b).resolve()
    except OSError:
        return Path(path_a) == Path(path_b)


class _CommitGraphDispatcher(QObject):
    """Application-lifetime queued dispatcher routing background commit-graph maintenance."""

    finished = Signal(object, int, object)  # (window_ref, generation_id, CommitGraphStats | None)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.finished.connect(self._deliver_finished, Qt.ConnectionType.QueuedConnection)

    @Slot(object, int, object)
    def _deliver_finished(self, window_ref: Any, generation_id: int, stats: Any) -> None:
        win = window_ref() if callable(window_ref) else None
        if win is not None and win._is_alive():
            win._on_commit_graph_finished(generation_id, stats)


_commit_graph_dispatcher: _CommitGraphDispatcher | None = None


def _get_commit_graph_dispatcher() -> _CommitGraphDispatcher:
    global _commit_graph_dispatcher
    if _commit_graph_dispatcher is None or not shiboken6.isValid(_commit_graph_dispatcher):
        _commit_graph_dispatcher = _CommitGraphDispatcher(parent=QCoreApplication.instance())
    return _commit_graph_dispatcher


class _CommitGraphWorker(QRunnable):
    """Runs background git commit-graph maintenance on QThreadPool."""

    def __init__(
        self,
        *,
        generation_id: int,
        repo_path: Path,
        settings_registry: SettingsRegistry | None,
        window_ref: weakref.ref[MainWindow],
        dispatcher: _CommitGraphDispatcher,
    ) -> None:
        super().__init__()
        self._generation_id = generation_id
        self._repo_path = repo_path
        self._settings_registry = settings_registry
        self._window_ref = window_ref
        self._dispatcher = dispatcher
        self.setAutoDelete(True)

    def run(self) -> None:
        if self._window_ref() is None:
            return
        stats = None
        try:
            stats = engine.maybe_write_commit_graph(
                self._repo_path,
                settings_registry=self._settings_registry,
            )
        except Exception as exc:
            logger.debug("Background commit-graph maintenance skipped: %s", exc)
        if self._window_ref() is not None and shiboken6.isValid(self._dispatcher):
            self._dispatcher.finished.emit(self._window_ref, self._generation_id, stats)


class MainWindow(QMainWindow):
    """Main application shell."""

    def __init__(self, conn: Any = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wrench")
        self.setMinimumSize(900, 600)
        self.resize(1200, 800)

        self._conn = conn if conn is not None else get_connection()
        self._settings_registry = get_settings_registry(self._conn)
        QPixmapCache.setCacheLimit(16384)
        self._engine = engine.GitEngine(settings=self._settings_registry)
        self._registry_connected: bool = False
        self._current_repo: RepoHandle | None = None
        self._watcher: RepoWatcher | None = None
        self._repos_state: dict[str, dict] = {}
        self._is_restoring: bool = True
        self._is_closing: bool = False
        self._restart_requested: bool = False
        self._repo_switch_generation: int = 0
        self._commit_graph_generation: int = 0
        self._discovery_cancel_event: threading.Event | None = None
        self._sparse_dialog: SparseCheckoutDialog | None = None
        self._interactive_rebase_dialog: InteractiveRebaseDialog | None = None
        self._active_settings_dialog: QDialog | None = None

        # 1000ms debounce timer for coalescing auto-save writes
        self._auto_save_timer = QTimer(self)
        self._auto_save_timer.setSingleShot(True)
        self._auto_save_timer.setInterval(1000)
        self._auto_save_timer.timeout.connect(self._save_session_state)

        # Delayed single-shot timer to reclaim C++ DeferredDelete widget heap pages
        self._heap_trim_timer = QTimer(self)
        self._heap_trim_timer.setSingleShot(True)
        self._heap_trim_timer.setInterval(150)
        self._heap_trim_timer.timeout.connect(self._on_delayed_heap_trim)

        # In-flight fetch tracking per repo to prevent concurrent ref locking collisions
        self._fetch_in_progress: set[str] = set()

        # Snapshot timer (every 5 minutes / 300_000ms)
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(300_000)
        self._snapshot_timer.timeout.connect(self._on_snapshot_timer)
        self._snapshot_timer.start()

        self._current_theme_mode: str = "auto"
        self._applying_theme_setting: bool = False
        self._in_set_theme: bool = False
        self._refreshing_theme: bool = False
        self._style_hints = QGuiApplication.styleHints()
        self._style_hints_connected: bool = False
        if hasattr(self._style_hints, "colorSchemeChanged"):
            self._style_hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
            self._style_hints_connected = True

        self._init_ui()
        self._restore_settings()
        self._settings_registry.setting_changed.connect(self._on_registry_setting_changed)
        self._registry_connected = True

    def _init_ui(self) -> None:
        # Central TabContainer & Activity Dock
        _central_widget = QWidget(self)
        _central_layout = QVBoxLayout(_central_widget)
        _central_layout.setContentsMargins(0, 0, 0, 0)
        _central_layout.setSpacing(0)

        # Context Header Bar (VP-2.5)
        self.context_header_bar = ContextHeaderBar(self)
        self.context_header_bar.repo_selector_clicked.connect(self._on_open_repo)
        self.context_header_bar.branch_selector_clicked.connect(self._on_branch_selector_clicked)
        self.context_header_bar.sync_requested.connect(self._on_sync_requested)
        self.context_header_bar.terminal_toggled.connect(self._toggle_terminal_drawer)
        self.context_header_bar.undo_requested.connect(self._on_undo_last_commit)
        self.context_header_bar.pull_requested.connect(self._on_pull_remote)
        self.context_header_bar.push_requested.connect(self._on_push_remote)
        self.context_header_bar.stash_requested.connect(self._on_stash_changes)
        self.context_header_bar.pop_requested.connect(self._on_pop_stash)
        _central_layout.addWidget(self.context_header_bar)

        self.tab_container = TabContainer(orientation=Qt.Vertical, parent=self)
        _central_layout.addWidget(self.tab_container)

        # Embedded Git Terminal Drawer (VP-2.5)
        self.terminal_drawer = GitTerminalDrawer(self)
        self.terminal_drawer.setVisible(False)
        self.terminal_drawer.set_command_runner(self._run_terminal_git_command)
        _central_layout.addWidget(self.terminal_drawer)

        QShortcut(QKeySequence("Ctrl+`"), self, activated=self._toggle_terminal_drawer)
        QShortcut(QKeySequence("Ctrl+~"), self, activated=self._toggle_terminal_drawer)

        self._activity_log = ActivityLogModel(maxlen=200, parent=self)
        self._activity_dock = ActivityLogBar(self._activity_log, parent=self)
        _central_layout.addWidget(self._activity_dock)
        set_activity_log(self._activity_log)

        self.setCentralWidget(_central_widget)

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
        self.history_tab = HistoryTab(self, settings_registry=self._settings_registry)
        self.history_tab.detail_panel._conn = self._conn
        self.history_tab.rebase_requested.connect(self._on_history_rebase)
        self.history_tab.interactive_rebase_requested.connect(self._on_history_interactive_rebase)
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
        self.tab_container.current_changed.connect(self._schedule_auto_save)
        self.tab_container.tabs_mutated.connect(self._schedule_auto_save)
        self.tab_container.orientation_changed.connect(self._schedule_auto_save)
        self.changes_tab.splitter.splitterMoved.connect(self._schedule_auto_save)
        self.history_tab.graph_widget.horizontalHeader().sectionResized.connect(
            self._schedule_auto_save
        )
        self.history_tab.content_splitter.splitterMoved.connect(self._schedule_auto_save)

        # Menu bar

        self._create_menu_bar()

        # Status bar (always reuse QMainWindow's single built-in bar)
        self.status_bar = self.statusBar()
        self.status_label = QLabel(self.tr("Ready"), self.status_bar)
        self.status_bar.addWidget(self.status_label)

        self.watcher_mode_label = QLabel("", self.status_bar)
        self.watcher_mode_label.setVisible(False)
        self.status_bar.addPermanentWidget(self.watcher_mode_label)

        self.sparse_status_btn = QToolButton(self.status_bar)
        self.sparse_status_btn.setVisible(False)
        self.sparse_status_btn.setAutoRaise(True)
        self.sparse_status_btn.clicked.connect(self._on_manage_sparse_checkout)
        self.status_bar.addPermanentWidget(self.sparse_status_btn)
        self._sync_sparse_ui_visibility()

    def _is_alive(self) -> bool:
        return shiboken6.isValid(self) and not getattr(self, "_is_closing", False)

    @staticmethod
    def _close_dialog_safely(dlg: Any) -> None:
        if isinstance(dlg, QDialog) and shiboken6.isValid(dlg):
            dlg.close()

    @staticmethod
    def _finish_busy_dialog(dlg: Any, *, accepted: bool) -> None:
        if dlg is None:
            return
        if isinstance(dlg, QObject) and not shiboken6.isValid(dlg):
            return
        if accepted:
            dlg.accept()
        else:
            dlg.reject()
        if isinstance(dlg, QDialog) and shiboken6.isValid(dlg):
            dlg.close()

    @staticmethod
    def _safe_busy_progress(dlg: Any) -> Callable[[int], None]:
        def _update(pct: int) -> None:
            if isinstance(dlg, QObject) and not shiboken6.isValid(dlg):
                return
            dlg.set_progress(pct)

        return _update

    @Slot()
    def _schedule_auto_save(self, *_args: Any) -> None:
        """Restarts the 1000ms debounce timer to batch session persistence writes."""
        if not self._is_alive() or getattr(self, "_is_restoring", False):
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

        edit_menu.addSeparator()

        self.act_preferences = edit_menu.addAction(self.tr("&Preferences…"))
        self.act_preferences.setShortcut(QKeySequence("Ctrl+,"))
        self.act_preferences.triggered.connect(self._on_open_preferences)

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
        self.act_theme_auto.triggered.connect(self._on_theme_auto_triggered)
        self.theme_group.addAction(self.act_theme_auto)

        self.act_theme_light = theme_menu.addAction(self.tr("Pastel &Light"))
        self.act_theme_light.setCheckable(True)
        self.act_theme_light.triggered.connect(self._on_theme_light_triggered)
        self.theme_group.addAction(self.act_theme_light)

        self.act_theme_dark = theme_menu.addAction(self.tr("Pastel &Dark"))
        self.act_theme_dark.setCheckable(True)
        self.act_theme_dark.triggered.connect(self._on_theme_dark_triggered)
        self.theme_group.addAction(self.act_theme_dark)

        view_menu.addSeparator()

        self.act_toggle_activity_dock = view_menu.addAction(self.tr("Toggle Activity &History"))
        self.act_toggle_activity_dock.setShortcut(QKeySequence("Ctrl+`"))
        self.act_toggle_activity_dock.triggered.connect(self._on_toggle_activity_dock)

        self.act_humor_lines = view_menu.addAction(self.tr("Show &Humor / Personality Lines"))
        self.act_humor_lines.setCheckable(True)
        self.act_humor_lines.toggled.connect(self._set_humor_lines)
        view_menu.aboutToShow.connect(self._sync_humor_lines_action)
        self._sync_humor_lines_action()

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

        self.act_sparse_checkout = repo_menu.addAction(self.tr("&Sparse-Checkout Directories…"))
        self.act_sparse_checkout.triggered.connect(self._on_manage_sparse_checkout)

        repo_menu.addSeparator()

        self.act_forge_accounts = repo_menu.addAction(self.tr("Forge &Accounts…"))
        self.act_forge_accounts.triggered.connect(self._on_manage_forge_accounts)

        self.act_link_forge = repo_menu.addAction(self.tr("&Link to Forge…"))
        self.act_link_forge.triggered.connect(self._on_link_forge)

        repo_menu.addSeparator()

        self.act_auto_fetch = repo_menu.addAction(
            self.tr("Fetch automatically when opening a repository")
        )
        self.act_auto_fetch.setCheckable(True)
        self.act_auto_fetch.toggled.connect(self._set_auto_fetch)
        repo_menu.aboutToShow.connect(self._sync_auto_fetch_action)
        self._sync_auto_fetch_action()

        # ---------------- Help Menu ----------------
        help_menu = menu_bar.addMenu(self.tr("&Help"))

        act_about = help_menu.addAction(self.tr("&About Wrench"))
        act_about.triggered.connect(self._on_about)

        act_report = help_menu.addAction(self.tr("&Report a Bug…"))
        act_report.triggered.connect(self._on_report_bug)

    def _restore_settings(self) -> None:
        """Restores full session state (window, tabs, orientation, active repo, selections)."""
        restore_session = self._settings_registry.get_bool("ui.session_state")
        restore_repos = self._settings_registry.get_bool("workspace.restore_session_on_startup")
        raw_session = (
            settings.get_setting(self._conn, "ui.session_state") if restore_session else None
        )
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
            if restore_repos:
                self.changes_tab.load_repos(select_path=saved_repo_path, auto_open=True)
                if saved_repo_path and saved_repo_path in self._repos_state:
                    self.changes_tab.restore_repo_state(self._repos_state[saved_repo_path])
            else:
                self.changes_tab.load_repos(auto_open=False)

            # Restore open tabs (Phase 4.2: lazy factory closures)
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

                        # "changes", "history", and "snapshots" are singleton
                        # widgets that already exist — always pass them directly
                        # (no factory needed).
                        if t_type == "changes":
                            self.tab_container.add_tab(
                                widget=self.changes_tab,
                                label=label or self.tr("Changes"),
                                tab_type="changes",
                                closable=closable,
                                is_pinned=is_pinned,
                                activate=False,
                            )
                        elif t_type == "history":
                            self.tab_container.add_tab(
                                widget=self.history_tab,
                                label=label or self.tr("History"),
                                tab_type="history",
                                closable=closable,
                                is_pinned=is_pinned,
                                activate=False,
                            )
                        elif t_type == "snapshots":
                            self.tab_container.add_tab(
                                widget=self.snapshots_panel,
                                label=label or self.tr("Snapshots"),
                                tab_type="snapshots",
                                closable=closable,
                                is_pinned=is_pinned,
                                activate=False,
                            )

                        elif t_type == "pr_list":
                            tab_repo = item.get("repo_path") or saved_repo_path or ""

                            def _make_pr_list(repo=tab_repo):
                                pr_tab = PRListTab(repo, self)
                                pr_tab.pr_selected.connect(self._open_pr_detail_tab)
                                pr_tab.link_requested.connect(self._on_link_forge)
                                return pr_tab

                            self.tab_container.add_tab(
                                widget=_make_pr_list,
                                label=label or self.tr("Pull Requests"),
                                tab_type="pr_list",
                                repo_path=tab_repo,
                                closable=closable,
                                is_pinned=is_pinned,
                                activate=False,
                            )
                        elif t_type in ("issues_list", "issue_list"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""

                            def _make_issue_list(repo=tab_repo):
                                issue_tab = IssueListTab(repo, self)
                                issue_tab.issue_selected.connect(self._open_issue_detail_tab)
                                issue_tab.link_requested.connect(self._on_link_forge)
                                return issue_tab

                            self.tab_container.add_tab(
                                widget=_make_issue_list,
                                label=label or self.tr("Issues"),
                                tab_type="issues_list",
                                repo_path=tab_repo,
                                closable=closable,
                                is_pinned=is_pinned,
                                activate=False,
                            )
                        elif t_type == "pr_detail" and item.get("entity_id"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            entity_id = item.get("entity_id", "")
                            parts = entity_id.split(":", 1)
                            if len(parts) == 2:

                                def _make_pr_detail(repo=tab_repo, remote=parts[0], pr_id=parts[1]):
                                    detail_tab = PRDetailTab(repo, remote, pr_id, self)
                                    detail_tab.branch_checkout_requested.connect(
                                        self._on_checkout_branch
                                    )
                                    return detail_tab

                                self.tab_container.add_tab(
                                    widget=_make_pr_detail,
                                    label=label or f"PR #{parts[1]}",
                                    tab_type="pr_detail",
                                    repo_path=tab_repo,
                                    entity_id=entity_id,
                                    closable=closable,
                                    is_pinned=is_pinned,
                                    activate=False,
                                )
                        elif t_type == "issue_detail" and item.get("entity_id"):
                            tab_repo = item.get("repo_path") or saved_repo_path or ""
                            entity_id = item.get("entity_id", "")
                            parts = entity_id.split(":", 1)
                            if len(parts) == 2:

                                def _make_issue_detail(
                                    repo=tab_repo, remote=parts[0], issue_id=parts[1]
                                ):
                                    return IssueDetailTab(repo, remote, issue_id, self)

                                self.tab_container.add_tab(
                                    widget=_make_issue_detail,
                                    label=label or f"Issue #{parts[1]}",
                                    tab_type="issue_detail",
                                    repo_path=tab_repo,
                                    entity_id=entity_id,
                                    closable=closable,
                                    is_pinned=is_pinned,
                                    activate=False,
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
                                activate=False,
                            )
                    # Activate ONLY the saved active tab — this triggers
                    # ensure_loaded() and constructs that single tab.
                    if self.tab_container.count() > 0:
                        idx = max(0, min(saved_active_idx, self.tab_container.count() - 1))
                        self.tab_container.set_current_index(idx)
        else:
            # Fallback for initial launch or legacy settings when session restore is enabled
            if restore_session:
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

            self.changes_tab.load_repos(auto_open=(restore_session and restore_repos))

        # Ensure window is visible on a valid screen
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            self.resize(1200, 800)
            if QGuiApplication.primaryScreen():
                center = QGuiApplication.primaryScreen().availableGeometry().center()
                self.move(center.x() - 600, center.y() - 400)

        if hasattr(self, "_activity_dock"):
            self._activity_dock.set_max_lines(
                self._settings_registry.get_int("ui.activity_dock.max_lines")
            )

        if self._settings_registry.has_explicit_setting("ui.font_size_pt"):
            self._apply_font_size_pt(self._settings_registry.get_int("ui.font_size_pt"))

        # Restore theme preference without re-writing stale legacy rows on launch
        saved_theme = settings.get_setting(self._conn, "theme") or "auto"
        self._set_theme(saved_theme, persist=False)

        self._sync_humor_lines_action()
        self._sync_auto_fetch_action()

        if hasattr(self, "context_header_bar"):
            self.context_header_bar.setVisible(
                self._settings_registry.is_enabled("ui.show_context_header_bar")
            )

        # Mark restoration complete and ensure no lingering auto-save timer
        self._is_restoring = False
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()

    def _apply_font_size_pt(self, point_size: int) -> None:
        """Applies interface point font size without clobbering defaults when unset."""
        if not shiboken6.isValid(self) or getattr(self, "_is_closing", False):
            return
        try:
            pt = max(8, min(18, int(point_size)))
        except ValueError, TypeError:
            pt = 10
        app = QApplication.instance()
        if app is not None:
            app_font = app.font()
            if app_font.pointSize() != pt:
                app_font.setPointSize(pt)
                app.setFont(app_font)
        win_font = self.font()
        if win_font.pointSize() != pt:
            win_font.setPointSize(pt)
            self.setFont(win_font)
        if hasattr(self, "history_tab") and shiboken6.isValid(self.history_tab):
            if hasattr(self.history_tab, "graph_widget") and shiboken6.isValid(
                self.history_tab.graph_widget
            ):
                self.history_tab.graph_widget.invalidate_paint_caches()
        if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
            self.changes_tab.refresh_theme()
        self._propagate_theme_refresh()

    def _set_theme(self, mode: str, *, persist: bool = True) -> None:
        """Applies the selected theme mode, updates UI actions, and optionally persists setting."""
        if getattr(self, "_in_set_theme", False):
            return
        self._in_set_theme = True
        try:
            menu_mode = normalize_theme_mode(mode, target="legacy")
            self._current_theme_mode = menu_mode
            app = QApplication.instance()
            if app:
                apply_theme(app, menu_mode)
            if persist:
                self._applying_theme_setting = True
                try:
                    settings.set_setting(self._conn, "theme", menu_mode)
                finally:
                    self._applying_theme_setting = False

            if hasattr(self, "theme_group") and hasattr(self, "act_theme_auto"):
                with (
                    QSignalBlocker(self.theme_group),
                    QSignalBlocker(self.act_theme_auto),
                    QSignalBlocker(self.act_theme_light),
                    QSignalBlocker(self.act_theme_dark),
                ):
                    if menu_mode == "light":
                        self.act_theme_light.setChecked(True)
                    elif menu_mode == "dark":
                        self.act_theme_dark.setChecked(True)
                    else:
                        self.act_theme_auto.setChecked(True)

            self._propagate_theme_refresh()
        finally:
            self._in_set_theme = False

    @Slot()
    def _on_theme_auto_triggered(self) -> None:
        self._set_theme("auto")

    @Slot()
    def _on_theme_light_triggered(self) -> None:
        self._set_theme("light")

    @Slot()
    def _on_theme_dark_triggered(self) -> None:
        self._set_theme("dark")

    @Slot(Qt.ColorScheme)
    @Slot()
    def _on_system_color_scheme_changed(self, *_args: Any) -> None:
        """Reacts when desktop/system color scheme changes while in 'auto' mode."""
        if not shiboken6.isValid(self) or getattr(self, "_in_set_theme", False):
            return
        if getattr(self, "_current_theme_mode", "auto") == "auto":
            app = QApplication.instance()
            if app:
                apply_theme(app, "auto")
            self._propagate_theme_refresh()

    def _apply_status_bar_theme(self) -> None:
        """Apply theme-tokenized styles on status bar pills."""
        is_dark = is_dark_theme(self)
        if hasattr(self, "sparse_status_btn"):
            sparse_style = get_status_pill_style("sparse_active", is_dark)
            self.sparse_status_btn.setStyleSheet(
                f"QToolButton {{ background-color: {sparse_style['bg']}; "
                f"color: {sparse_style['fg']}; "
                f"border: 1px solid {sparse_style['border']}; border-radius: 9px; "
                f"padding: 1px 8px; font-size: 11px; font-weight: bold; }}"
            )
        if hasattr(self, "watcher_mode_label"):
            watcher_style = get_status_pill_style("watcher", is_dark)
            self.watcher_mode_label.setStyleSheet(
                f"QLabel {{ background-color: {watcher_style['bg']}; "
                f"color: {watcher_style['fg']}; "
                f"border: 1px solid {watcher_style['border']}; border-radius: 9px; "
                f"padding: 1px 8px; font-size: 11px; }}"
            )

    def _propagate_theme_refresh(self) -> None:
        """Propagates theme change to all child tabs, diff views, and open dialogs."""
        if getattr(self, "_refreshing_theme", False) or not shiboken6.isValid(self):
            return
        self._refreshing_theme = True
        try:
            if hasattr(self, "tab_container") and shiboken6.isValid(self.tab_container):
                self.tab_container.refresh_theme()
            if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
                self.changes_tab.refresh_theme()
            if hasattr(self, "history_tab") and shiboken6.isValid(self.history_tab):
                self.history_tab.refresh_theme()
            if hasattr(self, "_activity_dock") and shiboken6.isValid(self._activity_dock):
                self._activity_dock.refresh_theme()
            self._apply_status_bar_theme()
            seen_dlgs: set[int] = set()
            candidates: list[Any] = [
                getattr(self, "_active_settings_dialog", None),
                getattr(self, "_sparse_dialog", None),
                getattr(self, "_interactive_rebase_dialog", None),
                *self.findChildren(QDialog),
            ]
            for dlg in candidates:
                if (
                    dlg is not None
                    and id(dlg) not in seen_dlgs
                    and shiboken6.isValid(dlg)
                    and hasattr(dlg, "_apply_theme")
                ):
                    seen_dlgs.add(id(dlg))
                    dlg._apply_theme()
            repolish_widget(self.menuBar() if shiboken6.isValid(self) else None)
            repolish_widget(self.statusBar() if shiboken6.isValid(self) else None)
            repolish_widget(self)
        finally:
            self._refreshing_theme = False

    def _is_gravatar_enabled(self) -> bool:
        """Returns True if user opted into gravatar commit avatars (default False)."""
        val = settings.get_setting(self._conn, "ui.avatars_gravatar")
        return val == "true"

    def _set_avatars_gravatar(self, enabled: bool) -> None:
        """Single-source setter for Gravatar privacy toggle."""
        settings.set_setting(self._conn, "ui.avatars_gravatar", "true" if enabled else "false")

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
        if getattr(self, "_is_closing", False):
            super().closeEvent(event)
            return

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

        self._is_closing = True
        self._repo_switch_generation += 1
        self._commit_graph_generation += 1
        self._fetch_in_progress.clear()
        if getattr(self, "_discovery_cancel_event", None) is not None:
            self._discovery_cancel_event.set()

        # Flush auto-save timer and persist session synchronously before closing child tabs
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()
        if hasattr(self, "_snapshot_timer"):
            self._snapshot_timer.stop()
        self._save_session_state()

        self._disconnect_style_hints()
        self._disconnect_settings_registry()

        self._close_dialog_safely(getattr(self, "_sparse_dialog", None))
        self._sparse_dialog = None
        self._close_dialog_safely(getattr(self, "_interactive_rebase_dialog", None))
        self._interactive_rebase_dialog = None
        self._close_dialog_safely(getattr(self, "_active_settings_dialog", None))
        self._active_settings_dialog = None
        for child_dlg in list(self.findChildren(QDialog)):
            self._close_dialog_safely(child_dlg)

        closed_tab_ids: set[int] = set()
        if hasattr(self, "tab_container") and shiboken6.isValid(self.tab_container):
            self.tab_container.hide_loading()
            for i in range(self.tab_container.count()):
                meta = self.tab_container.tab_metadata(i)
                if meta and meta.is_loaded:
                    w = self.tab_container.widget(i)
                    if w is not None and shiboken6.isValid(w) and id(w) not in closed_tab_ids:
                        closed_tab_ids.add(id(w))
                        w.close()

        for tab_attr in ("changes_tab", "history_tab", "snapshots_panel"):
            w = getattr(self, tab_attr, None)
            if w is not None and shiboken6.isValid(w) and id(w) not in closed_tab_ids:
                closed_tab_ids.add(id(w))
                w.close()

        if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
            self.changes_tab._disconnect_avatar_loader()
        if hasattr(self, "history_tab") and shiboken6.isValid(self.history_tab):
            if hasattr(self.history_tab, "_debounce_timer"):
                self.history_tab._debounce_timer.stop()
            if hasattr(self.history_tab, "graph_widget") and shiboken6.isValid(
                self.history_tab.graph_widget
            ):
                self.history_tab.graph_widget._page_generation_id += 1
                self.history_tab.graph_widget._search_generation_id += 1
                self.history_tab.graph_widget._disconnect_avatar_loader()
                self.history_tab.graph_widget._disconnect_registry()

        if self._watcher:
            old_watcher = self._watcher
            self._watcher = None
            old_watcher.stop()
            if shiboken6.isValid(old_watcher):
                old_watcher.deleteLater()

        for timer in list(self.findChildren(QTimer)):
            if shiboken6.isValid(timer):
                timer.stop()

        sb = self.statusBar()
        if sb is not None and shiboken6.isValid(sb):
            sb.clearMessage()
        clear_activity_log(getattr(self, "_activity_log", None))
        close_avatar_http_client()

        super().closeEvent(event)

    def _reload_active_repo_handles(self) -> None:
        """Reload open RepoHandle instances so .git/config.worktree changes are visible."""
        candidates: list[Any] = [
            getattr(self, "_current_repo", None),
            getattr(getattr(self, "changes_tab", None), "_repo", None),
            getattr(
                getattr(getattr(self, "changes_tab", None), "branch_switcher", None),
                "_repo",
                None,
            ),
            getattr(getattr(self, "history_tab", None), "_repo", None),
            getattr(getattr(self, "snapshots_panel", None), "_repo", None),
        ]
        seen: set[int] = set()
        for handle in candidates:
            if handle is None or id(handle) in seen:
                continue
            seen.add(id(handle))
            try:
                engine.refresh_repo_handle(handle)
            except Exception as exc:
                logger.debug("RepoHandle reload skipped: %s", exc)

    def _on_external_watcher_change(self) -> None:
        """Handle filesystem/git-dir watcher events cleanly without stale handles."""
        if not shiboken6.isValid(self):
            return
        self._reload_active_repo_handles()
        if hasattr(self, "changes_tab"):
            self.changes_tab.refresh()
        self._sync_sparse_ui_visibility()

    def _reclaim_heap_after_switch(self) -> None:
        """Collect freed Python objects and ask glibc malloc to return heap pages to OS."""
        if not shiboken6.isValid(self) or getattr(self, "_is_closing", False):
            return
        app = QApplication.instance()
        if app is not None and app.closingDown():
            return
        try:
            gc.collect()
            trim = _get_malloc_trim()
            if trim is not None:
                trim(0)
        except Exception as exc:
            logger.debug("Heap trim skipped: %s", exc)

    @Slot()
    def _on_delayed_heap_trim(self) -> None:
        self._reclaim_heap_after_switch()

    def _on_repo_changed(self, path: str) -> None:
        if self._watcher:
            old_watcher = self._watcher
            self._watcher = None
            old_watcher.stop()
            if shiboken6.isValid(old_watcher):
                old_watcher.deleteLater()

        # --- Phase 4.2: Bump generation counter to cancel stale warmers ---
        self._repo_switch_generation += 1
        current_gen = self._repo_switch_generation

        # --- Phase 4.2: Show loading overlay ---
        self.tab_container.show_loading(Path(path).name)

        try:
            changes_repo = getattr(getattr(self, "changes_tab", None), "_repo", None)
            reused_from_changes_tab = False
            if (
                changes_repo is not None
                and self._current_repo is not changes_repo
                and _same_repo_path(changes_repo.path, path)
            ):
                self._current_repo = changes_repo
                reused_from_changes_tab = True
            else:
                self._current_repo = engine.open_repo(path)
            self.history_tab.set_repo(self._current_repo)
            self.snapshots_panel.set_repo(self._current_repo)
            self.restart_snapshot_timer()

            # Start inotify watcher
            self._watcher = RepoWatcher(
                path,
                on_change=self._on_external_watcher_change,
                parent=self,
                settings_registry=self._settings_registry,
            )
            self._watcher.status_changed.connect(self.history_tab.refresh)
            self._watcher.status_changed.connect(self.snapshots_panel.refresh_if_visible)
            self._watcher.adaptive_fallback_activated.connect(self._on_watcher_mode_changed)
            self._watcher.start()
            watcher_status = getattr(self._watcher, "status_info", None)
            if isinstance(getattr(watcher_status, "mode", None), str):
                self._on_watcher_mode_changed(watcher_status.mode, watcher_status.reason or "")
            self._sync_sparse_ui_visibility()
            self._apply_status_bar_theme()
            self._maybe_write_commit_graph(path)

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
            self._update_context_header_bar()

            # Restore cached draft/selections if available for this repo (skip duplicate
            # restore when ChangesTab._open_repo_by_path already restored _commit_drafts)
            if path in self._repos_state and not (
                reused_from_changes_tab and path in getattr(self.changes_tab, "_commit_drafts", {})
            ):
                self.changes_tab.restore_repo_state(self._repos_state[path])

            # --- Phase 4.2: Ensure active tab is loaded and refresh it ---
            active_idx = self.tab_container.current_index()
            self.tab_container.ensure_loaded(active_idx)

            # Trigger background reachability probing for all remotes
            try:
                engine.probe_remotes_async(self._current_repo, db_conn=self._conn)
            except Exception as probe_err:
                logger.debug("Remotes reachability probe skipped: %s", probe_err)

            # Notify LOADED open tabs of repo change (skip unloaded placeholders)
            for i in range(self.tab_container.count()):
                meta = self.tab_container.tab_metadata(i)
                if meta and not meta.is_loaded:
                    # Skip unloaded lazy tabs — they will pick up the repo on activation
                    if meta.tab_type in ("pr_list", "issues_list", "issue_list"):
                        self.tab_container.update_tab_repo_path(i, path)
                    continue
                w = self.tab_container.widget(i)
                if meta and meta.tab_type in ("pr_list", "issues_list", "issue_list"):
                    self.tab_container.update_tab_repo_path(i, path)
                if hasattr(w, "set_active_repository"):
                    w.set_active_repository(path)
                elif hasattr(w, "reload_links_and_data") and getattr(w, "repo_path", None) == path:
                    w.reload_links_and_data()

            # --- Phase 4.2: Hide loading overlay ---
            self.tab_container.hide_loading()

            self._schedule_auto_save()

            # Phase 4.1: Open-time forge link resolution (runs before auto-fetch)
            self._maybe_offer_forge_link(path)

            # Phase 4.2: Auto-fetch after link resolution
            self._maybe_auto_fetch(current_gen)
            self._reclaim_heap_after_switch()
            if hasattr(self, "_heap_trim_timer") and shiboken6.isValid(self._heap_trim_timer):
                self._heap_trim_timer.start(150)
        except Exception as e:
            # --- Phase 4.2: Hide loading overlay on error ---
            self.tab_container.hide_loading()
            logger.error("Error setting up repo watcher: %s", e)
            self.status_label.setText(self.tr(f"Error opening repository: {e}"))

    def _maybe_offer_forge_link(self, repo_path: str) -> None:
        """Open-time link resolution: auto-link or offer banner for unlinked forge remotes.

        Phase 4.1 step 4: called after every open/switch, BEFORE auto-fetch (Phase 4.2).
        """
        if hasattr(self, "changes_tab") and hasattr(self.changes_tab, "hide_forge_link_banner"):
            self.changes_tab.hide_forge_link_banner()

        conn = self._conn
        repo_record = repo_registry.get_repo_by_path(conn, repo_path)
        if not repo_record:
            return

        repo_id = repo_record.id

        try:
            handle = (
                self._current_repo
                if (self._current_repo and _same_repo_path(self._current_repo.path, repo_path))
                else engine.open_repo(repo_path)
            )
            remotes = engine.list_remotes(handle, db_conn=conn)
        except Exception:
            return

        for remote in remotes:
            # a. Parse remote URL; skip non-supported or unparseable
            parts = parse_remote_url(remote.url)
            if not parts or parts.protocol not in ("https", "http", "ssh", "git"):
                continue
            if not parts.host:
                continue

            # b. Skip if already linked
            existing_link = forge_accounts.get_link_for_remote(conn, repo_id, remote.name)
            if existing_link:
                continue

            # c. Skip if declined
            declined_raw = settings.get_setting(conn, "forge.link_declined")
            declined_list: list[str] = []
            if declined_raw:
                try:
                    declined_list = json.loads(declined_raw)
                except json.JSONDecodeError, TypeError:
                    declined_list = []

            decline_key = f"{repo_id}:{remote.name}"
            if decline_key in declined_list:
                continue

            # d. Find candidate accounts (with host normalization for SSH)
            try:
                all_accounts = forge_accounts.list_accounts(conn)
            except Exception:
                all_accounts = []

            host = parts.host.lower()
            if host.endswith("github.com"):
                match_host = "github.com"
            elif host.endswith("gitlab.com"):
                match_host = "gitlab.com"
            else:
                match_host = host

            candidates = [
                a for a in all_accounts if host_of_instance_url(a.instance_url) == match_host
            ]

            if len(candidates) == 0:
                continue
            elif len(candidates) == 1:
                # Auto-link silently
                acc = candidates[0]
                forge_accounts.link_repo_to_account(
                    conn, repo_id, acc.id, remote.name, parts.owner, parts.repo
                )
                if self.statusBar():
                    self.statusBar().showMessage(
                        self.tr(f"Linked {parts.owner}/{parts.repo} to {acc.label}"),
                        5000,
                    )
                # Immediately notify ChangesTab and loaded forge tabs
                if hasattr(self, "changes_tab"):
                    self.changes_tab._update_account_btn()

                for i in range(self.tab_container.count()):
                    w = self.tab_container.widget(i)
                    if (
                        hasattr(w, "reload_links_and_data")
                        and getattr(w, "repo_path", None) == repo_path
                    ):
                        w.reload_links_and_data()

                # Background fetch account avatar if not cached
                if not settings.get_setting(conn, f"account.{acc.id}.avatar_url"):
                    self._trigger_account_avatar_fetch(acc)
            else:
                # Multiple candidates → show non-modal banner

                owner = parts.owner
                repo = parts.repo
                remote_name = remote.name
                r_id = repo_id

                def _on_link_clicked(_owner=owner, _repo=repo, _rpath=repo_path):
                    self.changes_tab.hide_forge_link_banner()
                    dlg = LinkRepoDialog(_rpath, parent=self, conn=self._conn)
                    dlg.links_changed.connect(
                        lambda: self._on_repo_changed(_rpath) if self._is_alive() else None
                    )
                    try:
                        dlg.exec()
                    finally:
                        self._close_dialog_safely(dlg)

                def _on_dismiss_clicked(_key=decline_key, _conn=conn):
                    self.changes_tab.hide_forge_link_banner()
                    raw = settings.get_setting(_conn, "forge.link_declined")
                    lst: list[str] = []
                    if raw:
                        try:
                            lst = json.loads(raw)
                        except json.JSONDecodeError, TypeError:
                            lst = []
                    if _key not in lst:
                        lst.append(_key)
                    settings.set_setting(_conn, "forge.link_declined", json.dumps(lst))

                self.changes_tab.show_forge_link_banner(
                    owner,
                    repo,
                    r_id,
                    remote_name,
                    on_link=_on_link_clicked,
                    on_dismiss=_on_dismiss_clicked,
                )
                break

    def _trigger_account_avatar_fetch(self, acc: forge_accounts.ForgeAccountRecord) -> None:
        """Fetch avatar URL in background for forge account and persist to settings."""
        full_acc = forge_accounts.get_account_full(self._conn, acc.id)
        if not full_acc:
            return

        def _fetch_fn():
            try:
                from wrench.forge.registry import create_adapter

                adapter = create_adapter(full_acc)
                try:
                    return adapter.get_avatar_url()
                finally:
                    adapter.close()
            except Exception:
                return None

        def _on_done(avatar_url: str | None):
            if not self._is_alive():
                return
            if avatar_url:
                settings.set_setting(self._conn, f"account.{acc.id}.avatar_url", avatar_url)
                if hasattr(self, "changes_tab"):
                    self.changes_tab._update_account_btn()
                from wrench.ui.widgets.avatar import get_avatar_loader

                get_avatar_loader().get_avatar(avatar_url, acc.username or acc.label)

        run_in_background(
            _fetch_fn,
            on_finished=_on_done,
        )

    def _maybe_auto_fetch(self, gen: int) -> None:
        """Phase 4.2 FR-4.7: Background auto-fetch for the default remote.

        Called at the end of ``_on_repo_changed`` *after* forge link resolution.
        Respects the ``repo.auto_fetch_on_open`` setting and the generation
        counter to discard results from superseded switches.
        """
        if not self._is_auto_fetch_enabled():
            return
        if not self._current_repo:
            return
        repo_key = str(self._current_repo.path)
        if repo_key in self._fetch_in_progress:
            logger.debug("Fetch already in progress for %s, skipping auto-fetch", repo_key)
            return

        remote = self._get_default_remote()
        if remote is None:
            return

        self._fetch_in_progress.add(repo_key)
        run_in_background(
            engine.fetch,
            self._current_repo,
            remote,
            on_finished=lambda _res: self._on_auto_fetch_finished(remote, gen, repo_key),
            on_failed=lambda exc: self._on_auto_fetch_failed(exc, gen, repo_key),
        )

    def _on_auto_fetch_finished(self, remote: str, gen: int, repo_key: str | None = None) -> None:
        """Callback for successful auto-fetch."""
        if not shiboken6.isValid(self):
            return
        if repo_key is not None:
            self._fetch_in_progress.discard(repo_key)
        elif self._current_repo:
            self._fetch_in_progress.discard(str(self._current_repo.path))

        if not self._is_alive() or gen != self._repo_switch_generation:
            return  # Stale or closed window — discard result
        self._refresh_after_git_op()

    def _on_auto_fetch_failed(self, exc: Exception, gen: int, repo_key: str | None = None) -> None:
        """Callback for failed auto-fetch — quiet transient status bar message only.

        NEVER shows a modal dialog, error banner, or retry loop.
        """
        if not shiboken6.isValid(self):
            return
        if repo_key is not None:
            self._fetch_in_progress.discard(repo_key)
        elif self._current_repo:
            self._fetch_in_progress.discard(str(self._current_repo.path))

        if not self._is_alive() or gen != self._repo_switch_generation:
            return  # Stale or closed window — discard result
        reason = str(exc)[:80] if str(exc) else type(exc).__name__
        self.statusBar().showMessage(self.tr(f"Auto-fetch skipped ({reason})"), 5000)

    def _is_auto_fetch_enabled(self) -> bool:
        """Returns True if auto-fetch on open/switch is enabled (default: True)."""
        val = settings.get_setting(self._conn, "repo.auto_fetch_on_open")
        return val != "false"

    def _set_auto_fetch(self, enabled: bool) -> None:
        """Single-source setter for the auto-fetch setting."""
        settings.set_setting(self._conn, "repo.auto_fetch_on_open", "true" if enabled else "false")
        self._sync_auto_fetch_action()

    def _sync_auto_fetch_action(self) -> None:
        """Synchronise the menu checkmark with the persisted setting."""
        if hasattr(self, "act_auto_fetch"):
            with QSignalBlocker(self.act_auto_fetch):
                self.act_auto_fetch.setChecked(self._is_auto_fetch_enabled())

    def _is_humor_lines_enabled(self) -> bool:
        """Returns True if humor / personality lines are enabled (default: True)."""
        val = settings.get_setting(self._conn, "ui.humor_lines")
        return val != "false"

    def _set_humor_lines(self, enabled: bool) -> None:
        """Single-source setter for the humor lines setting."""
        settings.set_setting(self._conn, "ui.humor_lines", "true" if enabled else "false")
        self._sync_humor_lines_action()
        if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
            self.changes_tab.refresh_humor_setting()

    def _sync_humor_lines_action(self) -> None:
        """Synchronise the menu checkmark with the persisted setting."""
        if hasattr(self, "act_humor_lines"):
            with QSignalBlocker(self.act_humor_lines):
                self.act_humor_lines.setChecked(self._is_humor_lines_enabled())

    def _on_toggle_activity_dock(self) -> None:
        """Toggle inline scrollback expansion of the activity log bar."""
        if hasattr(self, "_activity_dock"):
            self._activity_dock._toggle_expanded()

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
            opened_repo = engine.open_repo(dir_path)
            repo_registry.add_repo(self._conn, dir_path, Path(dir_path).name)
            self.changes_tab.load_repos(select_path=dir_path, opened_repo=opened_repo)
            return
        except WrenchRepoNotFoundError:
            pass  # Fall through to multi-repo directory discovery
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Open Failed"),
                self.tr(f"'{dir_path}' is not a valid Git repository: {e}"),
            )
            return

        self._start_directory_discovery(Path(dir_path))

    def _start_directory_discovery(self, root_path: Path) -> None:
        self._discovery_cancel_event = threading.Event()
        self.statusBar().showMessage(
            self.tr(f"Scanning for repositories in '{root_path}'..."),
            0,
        )

        def _on_progress(n: int) -> None:
            if not self._is_alive():
                return
            self.statusBar().showMessage(
                self.tr(f"Scanning for repositories in '{root_path}'... Found {n} so far"),
                0,
            )

        def _scan(progress_cb=None, cancel_event=None) -> list[Path]:
            return engine.discover_repos(
                root_path,
                max_depth=3,
                cancel_event=cancel_event or self._discovery_cancel_event,
                on_progress=progress_cb,
            )

        def _on_done(found_repos: list[Path]) -> None:
            if not self._is_alive():
                return
            self.statusBar().clearMessage()
            if not found_repos:
                QMessageBox.information(
                    self,
                    self.tr("No Repositories Found"),
                    self.tr(
                        f"No Git repositories found under '{root_path}' "
                        "(searched up to 3 levels deep)."
                    ),
                )
                return

            dlg = DiscoverReposDialog(repos=found_repos, root_dir=root_path, parent=self)
            try:
                if dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                selected = dlg.selected_repositories()
            finally:
                self._close_dialog_safely(dlg)

            added_count = 0
            known_count = 0
            for p in selected:
                p_str = str(p)
                rec = repo_registry.get_repo_by_path(self._conn, p_str)
                if rec and rec.is_missing:
                    repo_registry.clear_missing(self._conn, rec.id)
                    known_count += 1
                elif rec:
                    known_count += 1
                else:
                    repo_registry.add_repo(self._conn, p_str, p.name)
                    added_count += 1

            if selected:
                self.changes_tab.load_repos(select_path=str(selected[0]))
            else:
                self.changes_tab.load_repos()

            self.statusBar().showMessage(
                self.tr(f"Added {added_count} repositories ({known_count} already known)"),
                5000,
            )

        def _on_error(exc: Exception) -> None:
            if not self._is_alive():
                return
            self.statusBar().clearMessage()
            QMessageBox.warning(
                self,
                self.tr("Discovery Error"),
                self.tr(f"Error scanning '{root_path}': {exc}"),
            )

        self._discovery_worker = run_in_background(
            _scan,
            cancel_event=self._discovery_cancel_event,
            on_progress=_on_progress,
            on_finished=_on_done,
            on_failed=_on_error,
        )

    def _on_clone_repo(self) -> None:
        dlg = CloneDialog(
            parent=self,
            settings_registry=self._settings_registry,
            conn=self._conn,
        )
        try:
            if self._exec_dialog(dlg) != QDialog.DialogCode.Accepted:
                return
            raw_url = dlg.clone_url()
            dest_parent = dlg.dest_parent()
            repo_name = dlg.repo_name()
            fspec = dlg.filter_spec()
            use_sparse = dlg.sparse_enabled()
            chosen_account_id = dlg.selected_account_id()
        finally:
            self._close_dialog_safely(dlg)

        try:
            clean_url = engine.validate_clone_url(raw_url)
        except ValueError as exc:
            self.statusBar().showMessage(engine.redact_secrets(str(exc)), 6000)
            return

        if not dest_parent:
            return

        if not repo_name or repo_name in (".", "..") or "/" in repo_name or "\\" in repo_name:
            QMessageBox.critical(
                self,
                self.tr("Clone Repository"),
                self.tr("Invalid repository destination path rejected."),
            )
            self.statusBar().showMessage(
                self.tr("Invalid repository destination path rejected."),
                6000,
            )
            return
        try:
            parent_resolved = Path(dest_parent).resolve()
            dest_resolved = (parent_resolved / repo_name).resolve()
            if dest_resolved.parent != parent_resolved or dest_resolved == parent_resolved:
                QMessageBox.critical(
                    self,
                    self.tr("Clone Repository"),
                    self.tr("Invalid repository destination path rejected."),
                )
                self.statusBar().showMessage(
                    self.tr("Invalid repository destination path rejected."),
                    6000,
                )
                return
        except OSError:
            QMessageBox.critical(
                self,
                self.tr("Clone Repository"),
                self.tr("Invalid repository destination path rejected."),
            )
            self.statusBar().showMessage(
                self.tr("Invalid repository destination path rejected."),
                6000,
            )
            return

        target_dest = str(Path(dest_parent) / repo_name)
        filter_opt = None if fspec in ("", "none") else fspec

        # --- Phase 4.1: Multi-account clone pre-linking ---
        pre_created_repo = False
        url_parts = parse_remote_url(clean_url)

        if (
            chosen_account_id is not None
            and url_parts
            and url_parts.protocol in ("https", "http")
            and url_parts.host
        ):
            existing = repo_registry.get_repo_by_path(self._conn, target_dest)
            if existing:
                repo_id = existing.id
            else:
                repo_id = repo_registry.add_repo(self._conn, target_dest, repo_name)
                pre_created_repo = True

            forge_accounts.link_repo_to_account(
                self._conn,
                repo_id,
                chosen_account_id,
                "origin",
                url_parts.owner,
                url_parts.repo,
            )

        # --- Clone worker ---
        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Clone Repository"),
            self.tr(f"Cloning {engine.redact_secrets(clean_url)}..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_finished(_res):
            self._finish_busy_dialog(busy_dlg, accepted=True)
            if not self._is_alive():
                return
            if not pre_created_repo:
                repo_registry.add_repo(self._conn, target_dest, repo_name)
            prev_gen = self._repo_switch_generation
            self.changes_tab.load_repos(select_path=target_dest)
            if self._repo_switch_generation == prev_gen:
                self._on_repo_changed(target_dest)
            if use_sparse and self._settings_registry.is_enabled(
                "monorepo.sparse_checkout_ui.enabled", target_dest
            ):
                self._run_sparse_checkout_dialog(target_dest)

        def on_failed(exc):
            self._finish_busy_dialog(busy_dlg, accepted=False)
            if not self._is_alive():
                return
            # Mandatory rollback: remove pre-created row on clone failure
            if pre_created_repo:
                repo_registry.remove_repo(self._conn, target_dest)
            self._route_remote_error(exc, "origin", op="clone")

        busy_dlg.show()
        run_in_background(
            engine.clone_repo,
            clean_url,
            Path(target_dest),
            filter_spec=filter_opt,
            sparse=use_sparse,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=self._safe_busy_progress(busy_dlg),
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
            except Exception as e:
                logger.debug("Failed reading branch remote config: %s", e)

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
                    except Exception as e:
                        logger.debug("Failed parsing upstream name: %s", e)
            except Exception as e:
                logger.debug("Failed checking branch upstream references: %s", e)

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
        self._reload_active_repo_handles()
        if hasattr(self, "changes_tab"):
            self.changes_tab.refresh()
        if hasattr(self, "history_tab"):
            self.history_tab.refresh()
        if hasattr(self, "snapshots_panel"):
            self.snapshots_panel.refresh_if_visible()
        self._update_context_header_bar()
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
            except Exception as e:
                logger.debug("Failed updating status label: %s", e)
        self._sync_sparse_ui_visibility()

    def _update_context_header_bar(self) -> None:
        """Update ContextHeaderBar repository, branch, and sync status."""
        if not hasattr(self, "context_header_bar"):
            return
        if not self._current_repo:
            self.context_header_bar.update_repo(None, "", False)
            self.context_header_bar.update_sync_status(0, 0, False)
            return

        repo_path = self._current_repo.path
        is_detached = False
        branch_name = "main"
        try:
            is_detached = self._current_repo.pygit2_repo.head_is_detached
            if is_detached:
                branch_name = self._current_repo.pygit2_repo.head.target.hex[:7]
            else:
                branch_name = self._current_repo.pygit2_repo.head.shorthand
        except Exception:
            branch_name = "main"

        self.context_header_bar.update_repo(repo_path, branch_name, is_detached)

        try:
            sync = self._engine.get_branch_sync_status(self._current_repo, branch_name)
            self.context_header_bar.update_sync_status(sync.ahead, sync.behind, False)
        except Exception as exc:
            logger.debug("Branch sync status check skipped: %s", exc)
            self.context_header_bar.update_sync_status(0, 0, False)

    def _on_branch_selector_clicked(self) -> None:
        """Handle click on branch context cell in ContextHeaderBar."""
        if not self._current_repo:
            return
        try:
            branches = engine.list_branches(self._current_repo, local=True, remote=False)
            branch_names = [b.name for b in branches]
        except Exception as exc:
            logger.debug("Failed listing local branches: %s", exc)
            branch_names = []

        if not branch_names:
            return

        current_branch = self._get_current_branch() or ""
        curr_idx = branch_names.index(current_branch) if current_branch in branch_names else 0
        chosen, ok = QInputDialog.getItem(
            self,
            self.tr("Switch Branch"),
            self.tr("Select branch to checkout:"),
            branch_names,
            curr_idx,
            False,
        )
        if ok and chosen and chosen != current_branch:
            try:
                engine.checkout_branch(self._current_repo, chosen)
                self._on_checkout_branch(chosen)
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Checkout Failed"),
                    self.tr(f"Could not switch to branch '{chosen}': {e}"),
                )

    def _on_sync_requested(self, kind: str = "") -> None:
        """Handle click on SyncActionCell in ContextHeaderBar."""
        if not self._current_repo:
            return
        branch = self._get_current_branch()
        if not branch:
            QMessageBox.warning(
                self,
                self.tr("Detached HEAD"),
                self.tr("Cannot synchronize while HEAD is detached."),
            )
            return
        try:
            sync = self._engine.get_branch_sync_status(self._current_repo, branch)
        except Exception:
            sync = None

        if sync and sync.behind > 0 and sync.ahead == 0:
            self._on_pull_remote()
        elif sync and sync.ahead > 0 and sync.behind == 0:
            self._on_push_remote()
        elif sync and sync.ahead > 0 and sync.behind > 0:
            self._on_pull_remote()
        else:
            self._on_fetch_remote()

    def _toggle_terminal_drawer(self) -> None:
        """Toggle visibility of the embedded git terminal drawer."""
        if hasattr(self, "terminal_drawer"):
            self.terminal_drawer.toggle()
            if hasattr(self, "context_header_bar"):
                self.context_header_bar.quick_actions.set_terminal_active(
                    self.terminal_drawer.isVisible()
                )

    def _run_terminal_git_command(self, cmd_line: str) -> tuple[int, str, str]:
        """Execute a git command in the embedded terminal drawer."""
        if not self._current_repo:
            return (1, "", self.tr("No repository open"))
        args = cmd_line.strip().split()
        if not args:
            return (0, "", "")
        code, out, err = self._engine.run_git_terminal_command(args, cwd=self._current_repo.path)
        first_cmd = args[0].lower()
        if first_cmd in (
            "commit",
            "checkout",
            "switch",
            "branch",
            "merge",
            "rebase",
            "reset",
            "stash",
            "pull",
            "push",
            "cherry-pick",
            "revert",
        ):
            self._refresh_after_git_op()
        return (code, out, err)

    def _on_undo_last_commit(self) -> None:
        """Undo the most recent commit (git reset --soft HEAD~1)."""
        if not self._current_repo:
            return
        res = QMessageBox.question(
            self,
            self.tr("Undo Last Commit"),
            self.tr(
                "Are you sure you want to undo the last commit?\n\n"
                "Your changes will be kept staged in the working area."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if res == QMessageBox.StandardButton.Yes:
            code, stdout, stderr = self._engine.run_git_terminal_command(
                ["reset", "--soft", "HEAD~1"],
                cwd=self._current_repo.path,
            )
            if code == 0:
                self.status_label.setText(self.tr("Last commit undone (changes kept staged)."))
                self._refresh_after_git_op()
            else:
                QMessageBox.critical(
                    self,
                    self.tr("Undo Commit Failed"),
                    self.tr(f"git reset failed: {stderr or stdout}"),
                )

    def _on_manage_remotes(self) -> None:
        if not self._current_repo:
            QMessageBox.information(
                self,
                self.tr("No Repository Open"),
                self.tr("Please open a repository first to manage remotes."),
            )
            return
        dlg = RemotesDialog(self._current_repo, parent=self, db_conn=self._conn, auto_probe=True)
        try:
            dlg.exec()
        finally:
            self._close_dialog_safely(dlg)
        if self._is_alive():
            self._refresh_after_git_op()

    def _on_fetch_remote(self) -> None:
        if not self._current_repo:
            return
        repo_key = str(self._current_repo.path)
        if repo_key in self._fetch_in_progress:
            self.statusBar().showMessage(
                self.tr("Fetch already in progress for this repository..."), 3000
            )
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

        self._fetch_in_progress.add(repo_key)
        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Fetch"),
            self.tr(f"Fetching from '{remote}'..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_finished(_res):
            if shiboken6.isValid(self):
                self._fetch_in_progress.discard(repo_key)
            self._finish_busy_dialog(busy_dlg, accepted=True)
            if not self._is_alive():
                return
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Fetched from '{remote}'."))

        def on_failed(exc):
            if shiboken6.isValid(self):
                self._fetch_in_progress.discard(repo_key)
            self._finish_busy_dialog(busy_dlg, accepted=False)
            if not self._is_alive():
                return
            self._route_remote_error(exc, remote, op="fetch")

        busy_dlg.show()
        run_in_background(
            engine.fetch,
            self._current_repo,
            remote,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=self._safe_busy_progress(busy_dlg),
            cancel_event=cancel_event,
        )

    def _on_pull_remote(self) -> None:
        if not self._current_repo:
            return
        repo_key = str(self._current_repo.path)
        if repo_key in self._fetch_in_progress:
            self.statusBar().showMessage(
                self.tr("Fetch already in progress for this repository..."), 3000
            )
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

        self._fetch_in_progress.add(repo_key)
        cancel_event = threading.Event()
        busy_dlg = BusyOperationDialog(
            self.tr("Pull"),
            self.tr(f"Pulling branch '{branch}' from '{remote}'..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_finished(_res):
            if shiboken6.isValid(self):
                self._fetch_in_progress.discard(repo_key)
            self._finish_busy_dialog(busy_dlg, accepted=True)
            if not self._is_alive():
                return
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Pulled '{branch}' from '{remote}'."))

        def on_failed(exc):
            if shiboken6.isValid(self):
                self._fetch_in_progress.discard(repo_key)
            self._finish_busy_dialog(busy_dlg, accepted=False)
            if not self._is_alive():
                return
            self._route_remote_error(exc, remote, branch=branch, op="pull")

        busy_dlg.show()
        run_in_background(
            engine.pull,
            self._current_repo,
            remote,
            branch,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=self._safe_busy_progress(busy_dlg),
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

        # Pre-flight check for large blobs in unpushed commits (>= 50 MB)
        extra_config: dict[str, str] | None = None
        try:
            large_blobs = engine.scan_unpushed_large_blobs(
                self._current_repo, remote=remote, branch=branch, threshold_mb=50.0
            )
        except Exception:
            large_blobs = []

        if large_blobs:
            pre_dlg = PrePushLargeFilesDialog(
                large_blobs, remote=remote, branch=branch, parent=self
            )
            try:
                if pre_dlg.exec() != QDialog.DialogCode.Accepted:
                    return
                if pre_dlg.action == "extreme_compression":
                    extra_config = engine.EXTREME_COMPRESSION_CONFIG.copy()
            finally:
                self._close_dialog_safely(pre_dlg)

        title = self.tr("Force Push") if force else self.tr("Push")
        busy_dlg = BusyOperationDialog(
            title,
            self.tr(f"Pushing branch '{branch}' to '{remote}'..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_finished(_res):
            self._finish_busy_dialog(busy_dlg, accepted=True)
            if not self._is_alive():
                return
            self._refresh_after_git_op()
            self.status_label.setText(self.tr(f"Pushed '{branch}' to '{remote}'."))

        def on_failed(exc):
            self._finish_busy_dialog(busy_dlg, accepted=False)
            if not self._is_alive():
                return
            self._route_remote_error(exc, remote, branch=branch, op="push")

        busy_dlg.show()
        run_in_background(
            engine.push,
            self._current_repo,
            remote,
            branch,
            force=force,
            extra_config=extra_config,
            on_finished=on_finished,
            on_failed=on_failed,
            on_progress=self._safe_busy_progress(busy_dlg),
            cancel_event=cancel_event,
        )

    def _route_remote_error(
        self,
        exc: Exception,
        remote_name: str,
        branch: str | None = None,
        op: str = "remote",
    ) -> None:
        if not self._is_alive():
            return
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
            if exc.stderr and "Permission denied (publickey)" in exc.stderr:
                host_label = exc.host or "remote"
                QMessageBox.critical(
                    self,
                    self.tr("SSH Authentication Failed"),
                    self.tr(
                        f"SSH authentication to '{host_label}' failed (Permission denied).\n\n"
                        "Your SSH public key was not accepted by GitHub/remote host. "
                        "Please verify that your SSH key is added to your forge account "
                        "and loaded into ssh-agent, or use HTTPS to authenticate with your "
                        "stored Wrench account."
                    ),
                )
                return
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
            try:
                box.exec()
                clicked = box.clickedButton()
            finally:
                self._close_dialog_safely(box)
            if clicked == reauth_btn and self._is_alive():
                self._on_manage_forge_accounts()
            return

        if isinstance(exc, SecretScanningRejectedError):
            dlg = SecretScanningDialog(exc, parent=self)
            try:
                dlg.exec()
            finally:
                self._close_dialog_safely(dlg)
            return

        if isinstance(exc, ProtectedBranchRejectedError):
            default_branch = f"patch-{branch}" if branch else "patch-1"
            dlg = ProtectedBranchDialog(exc, default_new_branch=default_branch, parent=self)
            accepted = False
            new_branch = ""
            try:
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    accepted = True
                    new_branch = dlg.get_new_branch_name()
            finally:
                self._close_dialog_safely(dlg)
            if accepted and new_branch and self._current_repo and self._is_alive():
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
            try:
                dlg.exec()
            finally:
                self._close_dialog_safely(dlg)
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

        if isinstance(exc, GitNetworkTransferError):
            unpushed_blobs = []
            has_multiple = False
            remote_url = None
            if self._current_repo:
                try:
                    unpushed_blobs = engine.scan_unpushed_large_blobs(
                        self._current_repo,
                        remote=remote_name,
                        branch=branch,
                        threshold_mb=50.0,
                    )
                except Exception as e:
                    logger.debug("Failed scanning unpushed large blobs: %s", e)
                try:
                    count = engine.count_unpushed_commits(self._current_repo, remote_name, branch)
                    has_multiple = count > 1
                except Exception as e:
                    logger.debug("Failed counting unpushed commits: %s", e)
                try:
                    remote_url = engine.get_remote_url(self._current_repo, remote_name)
                except Exception as e:
                    logger.debug("Failed retrieving remote url: %s", e)

            dlg = GitNetworkRecoveryDialog(
                exc,
                remote_url=remote_url,
                unpushed_large_blobs=unpushed_blobs,
                has_multiple_commits=has_multiple,
                parent=self,
            )
            accepted = False
            action = ""
            cfg_overrides: dict[str, str] = {}
            ssh_url: str | None = None
            try:
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    accepted = True
                    action = dlg.get_action()
                    if action == "retry_config":
                        cfg_overrides = dlg.get_config_overrides()
                    elif action == "switch_ssh":
                        ssh_url = dlg.get_ssh_url()
            finally:
                self._close_dialog_safely(dlg)

            if accepted and self._is_alive():
                target_branch = branch or "HEAD"
                if action == "auto_heal":
                    self._start_auto_heal_push(
                        remote_name, target_branch, has_multiple=has_multiple
                    )
                elif action == "retry_config":
                    self._retry_push_with_config(remote_name, target_branch, cfg_overrides)
                elif action == "chunk_push":
                    self._start_incremental_push(remote_name, target_branch)
                elif action == "switch_ssh":
                    if ssh_url and self._current_repo:
                        try:
                            engine.set_remote_url(self._current_repo, remote_name, ssh_url)
                            self._on_push_remote(force=False)
                        except Exception as e:
                            QMessageBox.critical(self, self.tr("Failed to Set Remote URL"), str(e))
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
            try:
                box.exec()
                clicked = box.clickedButton()
            finally:
                self._close_dialog_safely(box)

            if not self._is_alive():
                return

            if clicked == fetch_btn:
                cancel_event = threading.Event()
                fetch_dlg = BusyOperationDialog(
                    self.tr("Fetch & Retry"),
                    self.tr(f"Fetching from '{remote_name}' before retrying push..."),
                    cancel_event=cancel_event,
                    humor_enabled=self._is_humor_lines_enabled(),
                    parent=self,
                )

                def on_fetch_done(_):
                    self._finish_busy_dialog(fetch_dlg, accepted=True)
                    if not self._is_alive():
                        return
                    self._refresh_after_git_op()
                    self._on_push_remote(force=False)

                def on_fetch_failed(e):
                    self._finish_busy_dialog(fetch_dlg, accepted=False)
                    if not self._is_alive():
                        return
                    self._route_remote_error(e, remote_name, branch=branch, op="fetch")

                fetch_dlg.show()
                run_in_background(
                    engine.fetch,
                    self._current_repo,
                    remote_name,
                    on_finished=on_fetch_done,
                    on_failed=on_fetch_failed,
                    on_progress=self._safe_busy_progress(fetch_dlg),
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
            try:
                box.exec()
                clicked = box.clickedButton()
            finally:
                self._close_dialog_safely(box)

            if not self._is_alive():
                return

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
            t_val = getattr(exc, "timeout", 600.0)
            if op == "push":
                QMessageBox.critical(
                    self,
                    self.tr("Push Timed Out"),
                    self.tr(
                        f"The push operation timed out after {t_val:.0f}s.\n\n"
                        "This usually occurs when uploading very large files or packfiles "
                        "over a slow connection.\n\n"
                        "To resolve this:\n"
                        "• Track large files with Git LFS instead of regular git history\n"
                        "• Or try pushing in incremental batches"
                    ),
                )
            else:
                QMessageBox.critical(
                    self,
                    self.tr("Operation Timed Out"),
                    self.tr(f"The Git operation timed out after {t_val:.0f}s."),
                )
            return

        msg = exc.stderr if isinstance(exc, GitCommandError) and exc.stderr else str(exc)
        QMessageBox.critical(
            self,
            self.tr(f"{op.capitalize()} Failed"),
            self.tr(f"Git operation failed: {msg}"),
        )

    def _retry_push_with_config(
        self,
        remote_name: str,
        branch: str,
        extra_config: dict[str, str],
        on_success_callback=None,
        on_failure_callback=None,
    ) -> None:
        if not self._current_repo:
            return

        cancel_event = threading.Event()
        dlg = BusyOperationDialog(
            self.tr("Pushing with Resilient Network Settings"),
            self.tr(f"Retrying push to '{remote_name}' with optimized network parameters..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_success(_):
            self._finish_busy_dialog(dlg, accepted=True)
            if not self._is_alive():
                return
            self._refresh_after_git_op()
            if on_success_callback:
                on_success_callback()
            else:
                self._prompt_save_network_config(extra_config)

        def on_failure(e):
            self._finish_busy_dialog(dlg, accepted=False)
            if not self._is_alive():
                return
            if on_failure_callback:
                on_failure_callback(e)
            else:
                self._route_remote_error(e, remote_name, branch=branch, op="push")

        dlg.show()
        run_in_background(
            engine.push,
            self._current_repo,
            remote_name,
            branch,
            force=False,
            extra_config=extra_config,
            on_finished=on_success,
            on_failed=on_failure,
            on_progress=self._safe_busy_progress(dlg),
            cancel_event=cancel_event,
            op_name="Push (Resilient Config)",
        )

    def _start_incremental_push(self, remote_name: str, branch: str) -> None:
        if not self._current_repo:
            return

        cancel_event = threading.Event()
        dlg = BusyOperationDialog(
            self.tr("Pushing Commits in Batches"),
            self.tr(f"Pushing commit batches to '{remote_name}' to avoid transfer timeouts..."),
            cancel_event=cancel_event,
            humor_enabled=self._is_humor_lines_enabled(),
            parent=self,
        )

        def on_success(_):
            self._finish_busy_dialog(dlg, accepted=True)
            if not self._is_alive():
                return
            self._refresh_after_git_op()
            QMessageBox.information(
                self,
                self.tr("Incremental Push Complete"),
                self.tr(f"All commit batches successfully pushed to '{remote_name}/{branch}'!"),
            )

        def on_failure(e):
            self._finish_busy_dialog(dlg, accepted=False)
            if not self._is_alive():
                return
            self._route_remote_error(e, remote_name, branch=branch, op="push")

        dlg.show()
        run_in_background(
            engine.push_incremental_batches,
            self._current_repo,
            remote_name,
            branch,
            chunk_size=20,
            force=False,
            on_finished=on_success,
            on_failed=on_failure,
            on_progress=self._safe_busy_progress(dlg),
            cancel_event=cancel_event,
            op_name="Push (Incremental Batches)",
        )

    def _start_auto_heal_push(
        self, remote_name: str, branch: str, has_multiple: bool = False
    ) -> None:
        """Execute the progressive Auto-Heal pipeline with circuit breaker."""
        # Stage 1: Resilient Buffer (500MB) + low-speed immunity
        stage1_cfg = {
            "http.postBuffer": "524288000",
            "http.lowSpeedLimit": "0",
            "http.lowSpeedTime": "999999",
        }

        # Stage 2: Buffer + HTTP/1.1 Downgrade + Window Memory Limits
        stage2_cfg = {
            "http.postBuffer": "524288000",
            "http.version": "HTTP/1.1",
            "http.lowSpeedLimit": "0",
            "http.lowSpeedTime": "999999",
            "pack.windowMemory": "256m",
            "pack.threads": "1",
        }

        # Stage 3: Extreme 7-Zip Style Compression
        stage3_cfg = engine.EXTREME_COMPRESSION_CONFIG.copy()

        def on_stage1_failed(err):
            def on_stage2_failed(err2):
                def on_stage3_failed(err3):
                    if has_multiple:
                        self._start_incremental_push(remote_name, branch)
                    else:
                        self._route_remote_error(err3, remote_name, branch=branch, op="push")

                self._retry_push_with_config(
                    remote_name,
                    branch,
                    stage3_cfg,
                    on_success_callback=lambda: self._prompt_save_network_config(stage3_cfg),
                    on_failure_callback=on_stage3_failed,
                )

            self._retry_push_with_config(
                remote_name,
                branch,
                stage2_cfg,
                on_success_callback=lambda: self._prompt_save_network_config(stage2_cfg),
                on_failure_callback=on_stage2_failed,
            )

        self._retry_push_with_config(
            remote_name,
            branch,
            stage1_cfg,
            on_success_callback=lambda: self._prompt_save_network_config(stage1_cfg),
            on_failure_callback=on_stage1_failed,
        )

    def _prompt_save_network_config(self, config_dict: dict[str, str]) -> None:
        if not self._is_alive():
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(self.tr("Push Succeeded — Save Network Settings?"))

        cfg_summary = ", ".join(
            f"{k}={v}" for k, v in config_dict.items() if not k.startswith("pack.")
        )
        box.setText(
            self.tr(
                f"Push completed successfully with optimized parameters ({cfg_summary})!\n\n"
                "Would you like to keep these settings for future push operations?"
            )
        )
        repo_btn = box.addButton(self.tr("For this Repository"), QMessageBox.ButtonRole.ActionRole)
        global_btn = box.addButton(
            self.tr("Globally (All Repos)"), QMessageBox.ButtonRole.ActionRole
        )
        box.addButton(self.tr("Don't Save"), QMessageBox.ButtonRole.RejectRole)
        try:
            box.exec()
            clicked = box.clickedButton()
        finally:
            self._close_dialog_safely(box)

        if not self._is_alive():
            return
        if clicked == repo_btn and self._current_repo:
            for k, v in config_dict.items():
                engine.set_git_config(self._current_repo, k, v, scope="local")
        elif clicked == global_btn:
            for k, v in config_dict.items():
                engine.set_git_config(None, k, v, scope="global")

    def _on_close_repo(self) -> None:
        current_idx = self.tab_container.current_index()
        meta = self.tab_container.tab_metadata(current_idx)
        if meta and meta.closable:
            self.tab_container.remove_tab(current_idx)
            return

        if self._current_repo:
            self._current_repo = None
            self.restart_snapshot_timer()
            if self._watcher:
                self._watcher.stop()
                self._watcher = None
            self.changes_tab.set_repo(None)
            self.history_tab.set_repo(None)
            self.snapshots_panel.set_repo(None)
            self.watcher_mode_label.setVisible(False)
            self._sync_sparse_ui_visibility()
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

    @property
    def _repo_path(self) -> Path | None:
        """Returns the Path of the currently opened repository, or None."""
        return self._current_repo.path if self._current_repo else None

    def _set_tab_orientation(self, orient: Qt.Orientation | str) -> None:
        """Sets tab container orientation, propagates to widgets, and persists to settings."""
        if isinstance(orient, str):
            qt_orient = Qt.Horizontal if orient.lower() == "horizontal" else Qt.Vertical
        else:
            qt_orient = orient
        self.tab_container.set_orientation(qt_orient)
        orient_str = "horizontal" if qt_orient == Qt.Horizontal else "vertical"
        settings.set_setting(self._conn, "ui.tab_orientation", orient_str)

    def _on_toggle_tab_orientation(self) -> None:
        new_orient = (
            Qt.Horizontal if self.tab_container.orientation() == Qt.Vertical else Qt.Vertical
        )
        self._set_tab_orientation(new_orient)

    def restart_snapshot_timer(self) -> None:
        """Refreshes or stops the automatic snapshot timer based on active repository settings."""
        if getattr(self, "_is_closing", False):
            if hasattr(self, "_snapshot_timer"):
                self._snapshot_timer.stop()
            return
        if self._current_repo:
            try:
                from wrench.core import snapshots

                cfg = snapshots.get_snapshot_settings(self._current_repo, conn=self._conn)
                if cfg.trigger_on_timer and cfg.timer_interval_minutes > 0:
                    self._snapshot_timer.setInterval(int(cfg.timer_interval_minutes * 60 * 1000))
                    self._snapshot_timer.start()
                else:
                    self._snapshot_timer.stop()
            except Exception as exc:
                logger.debug("Failed to restart snapshot timer: %s", exc)
                self._snapshot_timer.stop()
        else:
            self._snapshot_timer.stop()

    def _exec_dialog(self, dlg: QDialog) -> int:
        """Thin mockable dialog execution seam (FLASH-4)."""
        if dlg.windowModality() == Qt.WindowModality.NonModal:
            loop = QEventLoop(dlg)
            dlg.finished.connect(loop.quit)
            dlg.destroyed.connect(loop.quit)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            loop.exec()
            return int(dlg.result()) if shiboken6.isValid(dlg) else int(QDialog.DialogCode.Rejected)
        return dlg.exec()

    def _disconnect_style_hints(self, *_) -> None:
        if not getattr(self, "_style_hints_connected", False):
            return
        hints = getattr(self, "_style_hints", None)
        if hints is not None and shiboken6.isValid(hints) and hasattr(hints, "colorSchemeChanged"):
            try:
                hints.colorSchemeChanged.disconnect(self._on_system_color_scheme_changed)
            except RuntimeError, TypeError:
                pass
        self._style_hints_connected = False

    def _disconnect_settings_registry(self, *_) -> None:
        if not getattr(self, "_registry_connected", False):
            return
        try:
            self._settings_registry.setting_changed.disconnect(self._on_registry_setting_changed)
        except RuntimeError, TypeError:
            pass
        self._registry_connected = False

    def focus_active_settings_dialog(self) -> None:
        """Raise and focus the active Preferences dialog if one is open."""
        dlg = getattr(self, "_active_settings_dialog", None)
        if dlg is not None and shiboken6.isValid(dlg) and dlg.isVisible():
            dlg.raise_()
            dlg.activateWindow()

    def open_settings_at_category(
        self,
        category: str,
        highlight_key: str | None = None,
        parent_dialog: QWidget | None = None,
    ) -> None:
        """Open Preferences directly at a named SettingsRegistry category."""
        active = getattr(self, "_active_settings_dialog", None)
        if active is not None and shiboken6.isValid(active) and active.isVisible():
            if hasattr(active, "select_category"):
                active.select_category(category, highlight_key=highlight_key)
            active.raise_()
            active.activateWindow()
            return

        from wrench.ui.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(main_window=self, parent=parent_dialog or self)
        if parent_dialog is not None:
            dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._active_settings_dialog = dlg
        try:
            dlg.select_category(category, highlight_key=highlight_key)
            self._exec_dialog(dlg)
        finally:
            self._close_dialog_safely(dlg)
            if self._active_settings_dialog is dlg:
                self._active_settings_dialog = None

    def _exit_for_restart(self) -> None:
        """Exit Qt event loop with RESTART_EXIT_CODE so wrench.app relaunches cleanly."""
        if os.environ.get("PYTEST_CURRENT_TEST"):
            logger.info("Test environment detected; skipping process restart exit.")
            return
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, lambda a=app: a.exit(RESTART_EXIT_CODE))

    def request_restart(self) -> bool:
        """Persist session state, close cleanly, and trigger app relaunch."""
        if not shiboken6.isValid(self) or getattr(self, "_is_closing", False):
            return False
        self._save_session_state()
        settings_dlg = getattr(self, "_active_settings_dialog", None)
        if isinstance(settings_dlg, QDialog) and shiboken6.isValid(settings_dlg):
            settings_dlg.close()
        self._active_settings_dialog = None
        if not self.close():
            return False
        self._restart_requested = True
        self._exit_for_restart()
        return True

    def _sync_sparse_ui_visibility(self) -> None:
        repo_str = str(self._current_repo.path) if self._current_repo else None
        feature_enabled = self._settings_registry.is_enabled(
            "monorepo.sparse_checkout_ui.enabled", repo_str
        )
        if hasattr(self, "act_sparse_checkout"):
            self.act_sparse_checkout.setVisible(feature_enabled)
            self.act_sparse_checkout.setEnabled(feature_enabled and self._current_repo is not None)

        if not hasattr(self, "sparse_status_btn"):
            return

        if not feature_enabled or not self._current_repo:
            self.sparse_status_btn.setVisible(False)
            return

        try:
            state = engine.get_sparse_checkout_state(self._current_repo.path)
        except Exception as exc:
            logger.debug("Could not inspect sparse state for status badge: %s", exc)
            self.sparse_status_btn.setVisible(False)
            return

        if not state.enabled:
            self.sparse_status_btn.setVisible(False)
            return

        n = len(state.directories)
        suffix = f" ({state.partial_filter})" if state.partial_filter else ""
        self.sparse_status_btn.setText(self.tr(f"Sparse: {n} dir{'s' if n != 1 else ''}{suffix}"))
        self.sparse_status_btn.setToolTip(
            self.tr("Click to manage sparse-checkout cone directories")
        )
        self._apply_status_bar_theme()
        self.sparse_status_btn.setVisible(True)

    def _run_sparse_checkout_dialog(self, repo_path: str | Path) -> int:
        dlg = SparseCheckoutDialog(
            repo_path,
            parent=self,
            settings_registry=self._settings_registry,
        )
        self._sparse_dialog = dlg
        watcher = getattr(self, "_watcher", None)
        suspend_state = {"count": 0}

        def _watcher_usable(w: Any) -> bool:
            return w is not None and (not isinstance(w, QObject) or shiboken6.isValid(w))

        def _suspend_watcher() -> None:
            if _watcher_usable(watcher) and callable(getattr(watcher, "suspend", None)):
                watcher.suspend()
                suspend_state["count"] += 1

        def _resume_watcher(_ok: bool = True) -> None:
            if suspend_state["count"] > 0:
                suspend_state["count"] -= 1
                if _watcher_usable(watcher) and callable(getattr(watcher, "resume", None)):
                    watcher.resume(grace_ms=150)

        def _on_warning(msg: str) -> None:
            clean = engine.redact_secrets(msg)
            if self.statusBar():
                self.statusBar().showMessage(clean, 8000)

        dlg.apply_started.connect(_suspend_watcher)
        dlg.apply_finished.connect(_resume_watcher)
        dlg.apply_warning.connect(_on_warning)

        try:
            result = self._exec_dialog(dlg)
            if result == QDialog.DialogCode.Accepted:
                self._refresh_after_git_op()
                if getattr(dlg, "last_warning", None) and self.statusBar():
                    self.statusBar().showMessage(
                        engine.redact_secrets(str(dlg.last_warning)),
                        8000,
                    )
            return result
        finally:
            while suspend_state["count"] > 0:
                suspend_state["count"] -= 1
                if _watcher_usable(watcher) and callable(getattr(watcher, "resume", None)):
                    watcher.resume(grace_ms=150)
            if self._sparse_dialog is dlg:
                self._sparse_dialog = None

    def _on_manage_sparse_checkout(self) -> None:
        repo_str = str(self._current_repo.path) if self._current_repo else None
        if not self._settings_registry.is_enabled("monorepo.sparse_checkout_ui.enabled", repo_str):
            return
        if not self._current_repo:
            QMessageBox.information(
                self,
                self.tr("No Repository Open"),
                self.tr("Please open a repository first to configure sparse-checkout."),
            )
            return

        self._run_sparse_checkout_dialog(self._current_repo.path)

    @Slot(str, object)
    @Slot(str, object, object)
    def _on_registry_setting_changed(self, key: str, value: Any, repo_path: Any = None) -> None:
        if not self._is_alive():
            return
        active_repo = str(self._current_repo.path) if self._current_repo else None
        if repo_path is not None and repo_path != active_repo:
            return

        spec = self._settings_registry.get_spec(key)
        eff_repo = active_repo if (spec and spec.scope == SettingScope.REPO_OVERRIDABLE) else None

        if key == "ui.theme_mode":
            if not getattr(self, "_applying_theme_setting", False):
                eff_val = str(self._settings_registry.get(key) or "system")
                self._set_theme(eff_val, persist=False)
        elif key == "ui.font_size_pt":
            self._apply_font_size_pt(self._settings_registry.get_int(key))
        elif key == "ui.avatars_gravatar":
            clear_author_avatar_cache()
            if hasattr(self, "history_tab") and shiboken6.isValid(self.history_tab):
                self.history_tab.graph_widget.invalidate_paint_caches()
                self.history_tab.detail_panel.refresh_avatar()
            if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
                self.changes_tab._update_account_btn()
        elif key == "ui.humor_lines":
            self._sync_humor_lines_action()
            if hasattr(self, "changes_tab") and shiboken6.isValid(self.changes_tab):
                self.changes_tab.refresh_humor_setting()
        elif key == "ui.activity_dock.max_lines":
            if hasattr(self, "_activity_dock") and shiboken6.isValid(self._activity_dock):
                self._activity_dock.set_max_lines(self._settings_registry.get_int(key))
        elif key == "remote.auto_fetch.enabled":
            self._sync_auto_fetch_action()
        elif key == "monorepo.sparse_checkout_ui.enabled":
            self._sync_sparse_ui_visibility()
            if (
                not self._settings_registry.is_enabled(key, active_repo)
                and self._sparse_dialog is not None
                and shiboken6.isValid(self._sparse_dialog)
            ):
                if getattr(self._sparse_dialog, "_settings_open", False):
                    self._sparse_dialog._pending_close_on_disable = True
                else:
                    self._sparse_dialog.reject()
        elif key == "rebase.interactive_ui.enabled":
            if (
                not self._settings_registry.is_enabled(key, active_repo)
                and self._interactive_rebase_dialog is not None
                and shiboken6.isValid(self._interactive_rebase_dialog)
            ):
                self._interactive_rebase_dialog._load_generation += 1
                self._interactive_rebase_dialog._run_generation += 1
                if getattr(self._interactive_rebase_dialog, "_settings_open", False):
                    self._interactive_rebase_dialog._pending_close_on_disable = True
                else:
                    self._interactive_rebase_dialog.reject()
        elif key == "maintenance.auto_commit_graph.enabled":
            if not self._settings_registry.is_enabled(key, eff_repo):
                self._commit_graph_generation += 1
        elif key == "ui.show_context_header_bar":
            enabled = self._settings_registry.is_enabled(key, eff_repo)
            if hasattr(self, "context_header_bar") and shiboken6.isValid(self.context_header_bar):
                self.context_header_bar.setVisible(enabled)

    @Slot(str, str)
    def _on_watcher_mode_changed(self, mode: str, reason: str) -> None:
        if not shiboken6.isValid(self) or not isinstance(mode, str):
            return
        if not hasattr(self, "watcher_mode_label"):
            return
        if mode == "git_dir_inotify":
            self.watcher_mode_label.setText(self.tr("Watcher: .git-only"))
            self.watcher_mode_label.setToolTip(
                reason or self.tr("Switched to adaptive .git-only metadata watcher")
            )
            self._apply_status_bar_theme()
            self.watcher_mode_label.setVisible(True)
        elif mode == "polling":
            self.watcher_mode_label.setText(self.tr("Watcher: polling"))
            self.watcher_mode_label.setToolTip(
                reason or self.tr("Polling metadata fallback active")
            )
            self._apply_status_bar_theme()
            self.watcher_mode_label.setVisible(True)
        else:
            self.watcher_mode_label.setVisible(False)
            self.watcher_mode_label.setToolTip("")

    def _maybe_write_commit_graph(self, repo_path: str | Path) -> None:
        if not self._is_alive():
            return
        repo_str = str(repo_path)
        if not self._settings_registry.is_enabled(
            "maintenance.auto_commit_graph.enabled", repo_str
        ):
            return
        self._commit_graph_generation += 1
        gen_id = self._commit_graph_generation
        dispatcher = _get_commit_graph_dispatcher()
        worker = _CommitGraphWorker(
            generation_id=gen_id,
            repo_path=Path(repo_str),
            settings_registry=self._settings_registry,
            window_ref=weakref.ref(self),
            dispatcher=dispatcher,
        )
        QThreadPool.globalInstance().start(worker)

    @Slot(int, object)
    def _on_commit_graph_finished(self, generation_id: int, stats: Any) -> None:
        if not self._is_alive() or generation_id != self._commit_graph_generation:
            return
        if stats is not None and getattr(stats, "written", False):
            logger.debug(
                "Background commit-graph updated (%d ms, %d bytes)",
                stats.duration_ms,
                stats.graph_file_size_bytes,
            )

    def _on_open_preferences(self) -> None:
        """Opens the Preferences / Settings dialog."""
        active = getattr(self, "_active_settings_dialog", None)
        if active is not None and shiboken6.isValid(active) and active.isVisible():
            active.raise_()
            active.activateWindow()
            return

        from wrench.ui.dialogs.settings_dialog import SettingsDialog

        dlg = SettingsDialog(main_window=self, parent=self)
        self._active_settings_dialog = dlg
        try:
            self._exec_dialog(dlg)
        finally:
            self._close_dialog_safely(dlg)
            if self._active_settings_dialog is dlg:
                self._active_settings_dialog = None

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
        try:
            dlg.exec()
        finally:
            self._close_dialog_safely(dlg)
        if self._is_alive():
            self._refresh_forge_tabs()

    @Slot(bool)
    @Slot(str)
    @Slot()
    def _on_link_forge(self, repo_path: str | bool = "") -> None:
        resolved_path = repo_path if isinstance(repo_path, str) else ""
        target_path = resolved_path or (str(self._current_repo.path) if self._current_repo else "")
        if not target_path:
            QMessageBox.information(
                self,
                self.tr("No Active Repository"),
                self.tr("Please open a repository first to link it to a forge account."),
            )
            return
        dlg = LinkRepoDialog(target_path, self, conn=self._conn)
        dlg.links_changed.connect(self._refresh_forge_tabs)
        try:
            dlg.exec()
        finally:
            self._close_dialog_safely(dlg)

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

    def _on_history_interactive_rebase(self, base_oid: str) -> None:
        if not self._current_repo:
            return
        repo_str = str(self._current_repo.path)
        if not self._settings_registry.is_enabled("rebase.interactive_ui.enabled", repo_str):
            return
        active_dlg = getattr(self, "_interactive_rebase_dialog", None)
        if active_dlg is not None and shiboken6.isValid(active_dlg) and active_dlg.isVisible():
            active_dlg.raise_()
            active_dlg.activateWindow()
            return
        self._run_interactive_rebase_dialog(self._current_repo, base_oid)

    def _run_interactive_rebase_dialog(self, repo: engine.RepoHandle, base_oid: str) -> int:
        dlg = InteractiveRebaseDialog(
            repo,
            base_oid,
            parent=self,
            settings_registry=self._settings_registry,
        )
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        self._interactive_rebase_dialog = dlg
        watcher = getattr(self, "_watcher", None)
        suspend_state = {"count": 0}
        completed_results: list[Any] = []

        def _watcher_usable(w: Any) -> bool:
            return w is not None and (not isinstance(w, QObject) or shiboken6.isValid(w))

        def _suspend_watcher() -> None:
            if _watcher_usable(watcher) and callable(getattr(watcher, "suspend", None)):
                watcher.suspend()
                suspend_state["count"] += 1

        def _resume_watcher(*_args: Any) -> None:
            if suspend_state["count"] > 0:
                suspend_state["count"] -= 1
                if _watcher_usable(watcher) and callable(getattr(watcher, "resume", None)):
                    watcher.resume(grace_ms=150)

        def _on_rebase_completed(res: Any) -> None:
            completed_results.append(res)
            _resume_watcher()

        dlg.rebase_started.connect(_suspend_watcher)
        dlg.rebase_completed.connect(_on_rebase_completed)
        dlg.rebase_failed.connect(_resume_watcher)

        try:
            result = self._exec_dialog(dlg)
            if result == QDialog.DialogCode.Accepted:
                self._refresh_after_git_op()
                res = (
                    completed_results[-1]
                    if completed_results
                    else getattr(dlg, "last_result", None)
                )
                status = getattr(res, "status", "complete") if res is not None else "complete"
                if status == "conflict":
                    n_conflicts = len(getattr(res, "conflicted_files", []))
                    msg = self.tr(
                        f"Interactive rebase encountered conflicts in {n_conflicts} file(s)"
                        " — resolve them in Changes."
                    )
                    self.status_label.setText(msg)
                    if self.statusBar():
                        self.statusBar().showMessage(msg, 8000)
                    idx = self.tab_container.find_tab("changes", "")
                    if idx is not None:
                        self.tab_container.set_current_index(idx)
                elif status == "paused":
                    msg = self.tr(
                        "Interactive rebase paused for edit — modify changes and click "
                        "Continue Rebase in Changes."
                    )
                    self.status_label.setText(msg)
                    if self.statusBar():
                        self.statusBar().showMessage(msg, 8000)
                    idx = self.tab_container.find_tab("changes", "")
                    if idx is not None:
                        self.tab_container.set_current_index(idx)
                else:
                    msg = self.tr("Interactive rebase completed successfully.")
                    self.status_label.setText(msg)
                    if self.statusBar():
                        self.statusBar().showMessage(msg, 5000)
            return result
        finally:
            while suspend_state["count"] > 0:
                suspend_state["count"] -= 1
                if _watcher_usable(watcher) and callable(getattr(watcher, "resume", None)):
                    watcher.resume(grace_ms=150)
            if self._interactive_rebase_dialog is dlg:
                self._interactive_rebase_dialog = None

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
        dlg = AboutDialog(parent=self)
        try:
            dlg.exec()
        finally:
            self._close_dialog_safely(dlg)

    def _on_report_bug(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl("https://github.com/uzair777-dev/Wrench/issues"))
