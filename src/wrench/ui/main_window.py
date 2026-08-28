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

import logging
import sqlite3
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
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

from wrench.core import engine
from wrench.core.engine import RepoHandle
from wrench.storage import repo_registry, settings
from wrench.storage.db import get_connection
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
        self.tab_container.add_tab(
            widget=self.changes_tab,
            label=self.tr("Changes"),
            tab_type="changes",
            closable=True,
            is_pinned=True,
        )

        # 2. History tab (Index 1, closable)
        self.history_tab = HistoryTab(self)
        self.tab_container.add_tab(
            widget=self.history_tab,
            label=self.tr("History"),
            tab_type="history",
            closable=True,
        )

        # Connect add category tab request from (+) menu
        self.tab_container.add_category_tab_requested.connect(self._on_add_category_tab)

        # Menu bar
        self._create_menu_bar()

        # Status bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel(self.tr("Ready"), self.status_bar)
        self.status_bar.addWidget(self.status_label)

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
        """Restores window geometry, tab orientation, and active repository."""
        # Tab orientation
        saved_orientation = settings.get_setting(self._conn, "ui.tab_orientation")
        if saved_orientation == "horizontal":
            self.tab_container.set_orientation(Qt.Horizontal)
        else:
            self.tab_container.set_orientation(Qt.Vertical)

        # Geometry
        saved_geom = settings.get_setting(self._conn, "ui.window_geometry")
        if saved_geom:
            try:
                byte_array = QByteArray.fromHex(saved_geom.encode("utf-8"))
                self.restoreGeometry(byte_array)
            except Exception as e:
                logger.warning("Could not restore window geometry: %s", e)

        # Ensure window is visible on a valid screen
        screen = QGuiApplication.screenAt(self.pos())
        if not screen:
            self.resize(1200, 800)
            if QGuiApplication.primaryScreen():
                center = QGuiApplication.primaryScreen().availableGeometry().center()
                self.move(center.x() - 600, center.y() - 400)

        # Load repositories in ChangesTab
        self.changes_tab.load_repos()

    def _save_settings(self) -> None:
        """Persists window geometry and tab configuration."""
        try:
            geom_hex = self.saveGeometry().toHex().data().decode("utf-8")
            settings.set_setting(self._conn, "ui.window_geometry", geom_hex)

            orient_str = (
                "horizontal" if self.tab_container.orientation() == Qt.Horizontal else "vertical"
            )
            settings.set_setting(self._conn, "ui.tab_orientation", orient_str)
        except Exception as e:
            logger.warning("Failed to save UI settings: %s", e)

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

        # Save settings and stop watcher
        self._save_settings()
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

            # Start inotify watcher
            self._watcher = RepoWatcher(
                path,
                on_change=self.changes_tab.refresh,
                parent=self,
            )
            self._watcher.status_changed.connect(self.history_tab.refresh)
            self._watcher.start()

            status = engine.get_status(self._current_repo)
            branch = status.branch_name or "detached"
            self.status_label.setText(self.tr(f"Opened: {Path(path).name} ({branch})"))
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
        QMessageBox.information(
            self,
            self.tr("3-Way Merge Tool"),
            self.tr("The 3-Way Merge Tool will be integrated in Phase 2."),
        )

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
