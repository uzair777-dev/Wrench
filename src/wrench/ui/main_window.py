"""Main application window."""

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine, identity, lock_recovery
from wrench.core.engine import RepoHandle, RepoStatus
from wrench.core.exceptions import IdentityRequiredError
from wrench.storage import repo_registry
from wrench.storage.db import get_connection
from wrench.ui.diff_view.diff_widget import DiffView
from wrench.ui.sidebar.repo_list import RepoSidebar
from wrench.ui.workers import run_in_background
from wrench.watcher.inotify_watcher import RepoWatcher


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Wrench")
        self.resize(1100, 700)

        self._conn = conn if conn is not None else get_connection()
        self._current_repo: RepoHandle | None = None
        self._watcher: RepoWatcher | None = None

        self._init_ui()

    def closeEvent(self, event):
        if self._watcher:
            self._watcher.stop()
            self._watcher = None
        super().closeEvent(event)

    def _init_ui(self):
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 3-pane layout: Sidebar | Changes & Commit | Diff View
        splitter = QSplitter(Qt.Horizontal, self)
        main_layout.addWidget(splitter)

        # 1. Left pane: Repo sidebar
        self.sidebar = RepoSidebar(self._conn, self)
        self.sidebar.repo_selected.connect(self._on_repo_selected)
        self.sidebar.add_repo_requested.connect(self._on_add_repo_dialog)
        splitter.addWidget(self.sidebar)

        # 2. Middle pane: Working copy & Staging & Commit
        middle_widget = QWidget(self)
        middle_layout = QVBoxLayout(middle_widget)

        # Branch header
        branch_layout = QHBoxLayout()
        branch_layout.addWidget(QLabel("Branch:", self))
        self.branch_combo = QComboBox(self)
        self.branch_combo.currentTextChanged.connect(self._on_branch_changed)
        branch_layout.addWidget(self.branch_combo)

        self.new_branch_btn = QPushButton("+", self)
        self.new_branch_btn.setToolTip("Create Branch")
        self.new_branch_btn.clicked.connect(self._on_create_branch)
        branch_layout.addWidget(self.new_branch_btn)
        middle_layout.addLayout(branch_layout)

        # Staged files list
        staged_group = QGroupBox("Staged Changes", self)
        staged_layout = QVBoxLayout(staged_group)
        self.staged_list = QListWidget(self)
        self.staged_list.itemClicked.connect(self._on_staged_item_clicked)
        staged_layout.addWidget(self.staged_list)
        middle_layout.addWidget(staged_group)

        # Unstaged files list
        unstaged_group = QGroupBox("Unstaged Changes", self)
        unstaged_layout = QVBoxLayout(unstaged_group)
        self.unstaged_list = QListWidget(self)
        self.unstaged_list.itemClicked.connect(self._on_unstaged_item_clicked)
        unstaged_layout.addWidget(self.unstaged_list)
        middle_layout.addWidget(unstaged_group)

        # Commit box
        commit_group = QGroupBox("Commit", self)
        commit_layout = QVBoxLayout(commit_group)
        self.commit_box = QTextEdit(self)
        self.commit_box.setPlaceholderText("Commit message...")
        self.commit_box.setMaximumHeight(80)
        commit_layout.addWidget(self.commit_box)

        self.commit_btn = QPushButton("Commit", self)
        self.commit_btn.clicked.connect(self._on_commit_clicked)
        commit_layout.addWidget(self.commit_btn)
        middle_layout.addWidget(commit_group)

        splitter.addWidget(middle_widget)

        # 3. Right pane: Diff View
        self.diff_view = DiffView(self)
        self.diff_view.hunk_staged.connect(lambda: self.refresh_status())
        self.diff_view.file_staged.connect(lambda: self.refresh_status())
        splitter.addWidget(self.diff_view)

        splitter.setSizes([200, 300, 600])

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _on_add_repo_dialog(self):
        path = QFileDialog.getExistingDirectory(self, "Open Git Repository")
        if path:
            p = Path(path)
            try:
                engine.open_repo(p)
                repo_registry.add_repo(self._conn, str(p))
                self.sidebar.refresh()
                self._open_repo_path(str(p))
            except Exception as e:
                QMessageBox.warning(self, "Invalid Repository", str(e))

    def _on_repo_selected(self, path_str: str):
        self._open_repo_path(path_str)

    def _open_repo_path(self, path_str: str):
        path = Path(path_str)
        if not path.exists():
            QMessageBox.warning(
                self, "Missing Directory", f"Repository path does not exist:\n{path}"
            )
            return

        try:
            lock_recovery.check_lock(path)
        except lock_recovery.StaleLockDetectedError as e:
            reply = QMessageBox.question(
                self,
                "Stale Git Lock Detected",
                f"A stale lock file was detected at:\n{e.lock_path}\n\nClear it now?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                lock_recovery.remove_lock(path)

        try:
            identity.check_identity(path)
        except IdentityRequiredError:
            name, ok1 = QInputDialog.getText(self, "Git Identity Required", "Enter your user.name:")
            if ok1 and name:
                email, ok2 = QInputDialog.getText(
                    self, "Git Identity Required", "Enter your user.email:"
                )
                if ok2 and email:
                    identity.set_identity(path, name, email)

        try:
            self._current_repo = engine.open_repo(path)
            self.diff_view.set_repo(self._current_repo)

            # Start watcher
            if self._watcher:
                self._watcher.stop()
            self._watcher = RepoWatcher(path, self)
            self._watcher.status_changed.connect(self.refresh_status)
            self._watcher.start()

            self._populate_branches()
            self.refresh_status()
            self.status_bar.showMessage(f"Opened repository: {path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error Opening Repo", str(e))

    def _populate_branches(self):
        if not self._current_repo:
            return
        self.branch_combo.blockSignals(True)
        self.branch_combo.clear()
        branches = engine.list_branches(self._current_repo)
        for b in branches:
            self.branch_combo.addItem(b)

        status = engine.get_status(self._current_repo)
        if status.current_branch:
            idx = self.branch_combo.findText(status.current_branch)
            if idx >= 0:
                self.branch_combo.setCurrentIndex(idx)
        self.branch_combo.blockSignals(False)

    def _on_branch_changed(self, branch_name: str):
        if not self._current_repo or not branch_name:
            return
        try:
            engine.switch_branch(self._current_repo, branch_name)
            self.refresh_status()
        except Exception as e:
            QMessageBox.warning(self, "Branch Switch Failed", str(e))

    def _on_create_branch(self):
        if not self._current_repo:
            return
        name, ok = QInputDialog.getText(self, "Create Branch", "Branch name:")
        if ok and name:
            try:
                engine.create_branch(self._current_repo, name.strip())
                self._populate_branches()
                engine.switch_branch(self._current_repo, name.strip())
                self.refresh_status()
            except Exception as e:
                QMessageBox.warning(self, "Create Branch Failed", str(e))

    def refresh_status(self):
        if not self._current_repo:
            return

        def _fetch_status():
            return engine.get_status(self._current_repo)

        def _on_done(status: RepoStatus):
            self.staged_list.clear()
            for f in status.staged:
                self.staged_list.addItem(f"{f.change_type}: {f.path}")

            self.unstaged_list.clear()
            for f in status.unstaged:
                self.unstaged_list.addItem(f"{f.change_type}: {f.path}")
            for u in status.untracked:
                self.unstaged_list.addItem(f"untracked: {u}")

        run_in_background(_fetch_status, on_finished=_on_done)

    def _on_staged_item_clicked(self, item: QListWidgetItem):
        if not self._current_repo:
            return
        text = item.text()
        path = text.split(": ", 1)[-1]
        self.diff_view.set_file(path, staged=True)

    def _on_unstaged_item_clicked(self, item: QListWidgetItem):
        if not self._current_repo:
            return
        text = item.text()
        path = text.split(": ", 1)[-1]
        self.diff_view.set_file(path, staged=False)

    def _on_commit_clicked(self):
        if not self._current_repo:
            return
        msg = self.commit_box.toPlainText().strip()
        if not msg:
            QMessageBox.warning(self, "Empty Commit", "Please enter a commit message.")
            return

        if self.staged_list.count() == 0:
            QMessageBox.warning(
                self,
                "Nothing Staged",
                "No changes are staged for commit.\n\n"
                "Please stage the files or hunks you want to commit first.",
            )
            return

        def _do_commit():
            return engine.commit(self._current_repo, msg)

        def _on_success(sha):
            self.commit_box.clear()
            self.refresh_status()
            self.status_bar.showMessage(f"Committed {sha[:8]}")

        def _on_error(err):
            QMessageBox.critical(self, "Commit Failed", str(err))

        run_in_background(_do_commit, on_finished=_on_success, on_failed=_on_error)
