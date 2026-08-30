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
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
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
from wrench.storage import repo_registry, settings
from wrench.storage.db import get_connection
from wrench.ui.snapshots_panel import SnapshotsPanel
from wrench.ui.tabs.changes_tab import ChangesTab
from wrench.ui.tabs.history_tab import HistoryTab
from wrench.ui.tabs.tab_bar import TabContainer
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

        # Connect auto-save signals on tab changes
        self.tab_container.current_changed.connect(lambda *_: self._schedule_auto_save())
        self.tab_container.tabs_mutated.connect(lambda *_: self._schedule_auto_save())
        self.tab_container.orientation_changed.connect(lambda *_: self._schedule_auto_save())

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

        # Mark restoration complete and ensure no lingering auto-save timer
        self._is_restoring = False
        if hasattr(self, "_auto_save_timer"):
            self._auto_save_timer.stop()

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

            status = engine.get_status(self._current_repo)
            branch = status.branch_name or "detached"
            self.status_label.setText(self.tr(f"Opened: {Path(path).name} ({branch})"))

            # Restore cached draft/selections if available for this repo
            if path in self._repos_state:
                self.changes_tab.restore_repo_state(self._repos_state[path])

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
        try:
            engine.clone(clean_url, target_dest)
            repo_registry.add_repo(self._conn, target_dest, repo_name)
            self.changes_tab.load_repos(select_path=target_dest)
        except Exception as e:
            QMessageBox.critical(
                self,
                self.tr("Clone Failed"),
                self.tr(f"Could not clone repository: {e}"),
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
        else:
            # Placeholder for PR / Issues in Phase 4
            placeholder = QWidget(self)
            layout = QVBoxLayout(placeholder)
            layout.setAlignment(Qt.AlignCenter)
            label_text = f"{tab_type.replace('_', ' ').title()} coming in Phase 4"
            label = QLabel(self.tr(label_text), placeholder)
            layout.addWidget(label)
            self.tab_container.add_tab(
                widget=placeholder,
                label=tab_type.replace("_", " ").title(),
                tab_type=tab_type,
                closable=True,
            )

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
