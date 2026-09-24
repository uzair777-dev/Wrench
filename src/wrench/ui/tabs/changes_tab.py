"""Changes Tab Component (ui-planning.md §3, SRS FR-1.x, FR-2.1).

Provides:
- Flush/borderless repository dropdown selector with auto-recovery for missing repos
- Embedded branch indicator/switcher widget
- Merge conflict banner when conflicts are active
- Unified changed files list (staged + unstaged + untracked) with tri-state select-all
- Context menu for staging, unstaging, discarding, and copying paths
- Commit section with account icon, 72-char soft limit, description, amend toggle, and commit button
- Right column DiffView with binary file handling and empty states with programming quotes
"""

from __future__ import annotations

import logging
import random
import sqlite3
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import RepoHandle, RepoStatus
from wrench.core.exceptions import NothingToCommitError
from wrench.storage import forge_accounts, repo_registry
from wrench.ui.diff_view.diff_widget import DiffView
from wrench.ui.merge_tool.merge_dialog import MergeDialog
from wrench.ui.theme import (
    ACCENT_COLORS,
    CONFLICT_BANNER_STYLES,
    get_badge_colors,
    is_dark_theme,
)
from wrench.ui.widgets.branch_switcher import BranchSwitcherWidget

logger = logging.getLogger(__name__)

PROGRAMMING_QUOTES = [
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("Clean code always looks like it was written by someone who cares.", "Robert C. Martin"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Deleted code is debugged code.", "Jeff Sickel"),
]


class FileListItemWidget(QWidget):
    """Custom item widget for unified changed files list."""

    checked_changed = Signal(bool)

    def __init__(
        self,
        path: str,
        change_type: str,
        checked: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.path = path
        self.change_type = change_type

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # Checkbox
        self.checkbox = QCheckBox(self)
        self.checkbox.setChecked(checked)
        self.checkbox.toggled.connect(self.checked_changed.emit)
        layout.addWidget(self.checkbox)

        # Change type badge (M, A, D, R, ?, ⚠ C)
        self._change_type = change_type
        self.badge = QLabel(change_type, self)
        self.badge.setMinimumWidth(24)
        self.badge.setAlignment(Qt.AlignCenter)
        self._apply_badge_style(change_type)
        layout.addWidget(self.badge)

        # Path label (truncated if long)
        display_path = path
        if len(path) > 36:
            parts = path.split("/")
            if len(parts) > 2:
                display_path = f"…/{'/'.join(parts[-2:])}"
            else:
                display_path = f"…{path[-33:]}"

        self.label = QLabel(display_path, self)
        self.label.setToolTip(path)
        layout.addWidget(self.label, 1)

        self.setToolTip(f"{change_type}: {path}")

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-applies the badge style based on the active theme."""
        self._apply_badge_style()

    def _apply_badge_style(self, change_type: str | None = None) -> None:
        if change_type is not None:
            self._change_type = change_type
        ct = getattr(self, "_change_type", "M")
        is_dark = is_dark_theme(self)
        fg, bg = get_badge_colors(ct, is_dark=is_dark)
        self.badge.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; font-weight: bold; font-size: 11px; "
            f"border-radius: 3px; padding: 2px 4px; }}"
        )

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool, emit_signal: bool = False) -> None:
        if not emit_signal:
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(checked)
            self.checkbox.blockSignals(False)
        else:
            self.checkbox.setChecked(checked)


class SelectAllCheckBox(QCheckBox):
    """Tri-state checkbox for selecting/unselecting all changed files.

    Clicking when PartiallyChecked or Unchecked transitions to Checked (selects all).
    Clicking when Checked transitions to Unchecked (deselects all).
    """

    def nextCheckState(self) -> None:
        if self.checkState() == Qt.Checked:
            self.setCheckState(Qt.Unchecked)
        else:
            self.setCheckState(Qt.Checked)


class ChangedFilesList(QListWidget):
    """Custom QListWidget that toggles item checkbox on Space key press."""

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Space:
            item = self.currentItem()
            if item:
                w = self.itemWidget(item)
                if isinstance(w, FileListItemWidget):
                    w.set_checked(not w.is_checked(), emit_signal=True)
                    return
        super().keyPressEvent(event)


class ChangesTab(QWidget):
    """Main Changes tab container."""

    repo_changed = Signal(str)  # Emitted when active repo path changes
    state_changed = Signal()  # Emitted when per-repo selection, draft text, or splitter moves
    open_repo_dialog_requested = Signal()
    clone_repo_dialog_requested = Signal()
    resolve_conflicts_requested = Signal()
    forge_accounts_requested = Signal()
    link_repo_requested = Signal(str)

    def __init__(self, conn: sqlite3.Connection, parent: QWidget | None = None):
        super().__init__(parent)
        self._conn = conn
        self._repo: RepoHandle | None = None
        self._current_status: RepoStatus | None = None
        self._selected_file: str | None = None
        self._commit_drafts: dict[str, tuple[str, str]] = {}  # repo_path -> (msg, desc)
        self._previous_untracked_msg: str = ""

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setStyleSheet(
            "QSplitter::handle:horizontal { "
            "background-color: rgba(128, 128, 128, 0.25); width: 1px; } "
            "QSplitter::handle:horizontal:hover { background-color: palette(highlight); }"
        )
        main_layout.addWidget(self.splitter)

        # -------------------------------------------------------------
        # Left Column (Repo, Branch, Files, Commit)
        # -------------------------------------------------------------
        left_widget = QWidget(self)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)

        # Top: Repo dropdown & Forge button
        repo_bar = QHBoxLayout()
        repo_bar.setSpacing(4)

        self.repo_combo = QComboBox(self)
        self._update_repo_combo_theme()
        self.repo_combo.currentIndexChanged.connect(self._on_repo_combo_changed)
        repo_bar.addWidget(self.repo_combo, 1)

        self.forge_btn = QToolButton(self)
        self.forge_btn.setText("🌐")
        self.forge_btn.setToolTip(self.tr("Forge accounts and linked remotes"))
        self.forge_btn.setStyleSheet(
            "QToolButton { font-size: 13px; padding: 2px 5px; "
            "border: 1px solid rgba(128,128,128,0.2); border-radius: 3px; } "
            "QToolButton:hover { background-color: rgba(128,128,128,0.2); }"
        )
        self.forge_btn.clicked.connect(self._show_forge_menu)
        repo_bar.addWidget(self.forge_btn)

        left_layout.addLayout(repo_bar)

        # Branch switcher widget
        self.branch_switcher = BranchSwitcherWidget(self)
        self.branch_switcher.branch_switched.connect(self._on_branch_switched)
        self.branch_switcher.branch_operation_completed.connect(self.refresh)
        left_layout.addWidget(self.branch_switcher)

        # Conflict alert banner (hidden by default)
        self.conflict_banner = QFrame(self)
        conflict_layout = QHBoxLayout(self.conflict_banner)
        conflict_layout.setContentsMargins(6, 4, 6, 4)
        self.conflict_label = QLabel(self.tr("⚠️ Merge conflict in progress"), self.conflict_banner)
        conflict_layout.addWidget(self.conflict_label)
        self.conflict_btn = QPushButton(self.tr("Resolve…"), self.conflict_banner)
        self.conflict_btn.clicked.connect(self._on_conflict_btn_clicked)
        conflict_layout.addWidget(self.conflict_btn)
        self.conflict_banner.setVisible(False)
        self._update_conflict_banner_theme()
        left_layout.addWidget(self.conflict_banner)

        # Separator
        line = QFrame(self)
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        left_layout.addWidget(line)

        # Changed files header (Select-all checkbox + Count badge)
        files_header = QHBoxLayout()
        self.select_all_cb = SelectAllCheckBox(self)
        self.select_all_cb.setTristate(True)
        self.select_all_cb.setToolTip(self.tr("Select all / Deselect all"))
        self.select_all_cb.stateChanged.connect(self._on_select_all_toggled)
        files_header.addWidget(self.select_all_cb)

        self.files_count_label = QLabel(self.tr("0 changed files"), self)
        self.files_count_label.setStyleSheet("font-size: 11px; color: palette(placeholder-text);")
        files_header.addWidget(self.files_count_label)
        files_header.addStretch()
        left_layout.addLayout(files_header)

        # Unified changed files list
        self.files_list = ChangedFilesList(self)
        self.files_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.files_list.customContextMenuRequested.connect(self._show_file_context_menu)
        self.files_list.itemClicked.connect(self._on_file_item_clicked)
        left_layout.addWidget(self.files_list, 1)

        # Commit section
        commit_group = QGroupBox(self.tr("Commit"), self)
        commit_layout = QVBoxLayout(commit_group)
        commit_layout.setContentsMargins(6, 6, 6, 6)
        commit_layout.setSpacing(4)

        # Message row (Account Icon + Subject line)
        msg_row = QHBoxLayout()
        self.account_btn = QToolButton(commit_group)
        self.account_btn.setText("👤")
        self.account_btn.setToolTip(self.tr("Forge Account: Local / Unlinked"))
        self.account_btn.setAccessibleName(self.tr("Forge account picker"))
        self.account_btn.setStyleSheet(
            "QToolButton { border: none; font-size: 14px; padding: 2px 4px; border-radius: 12px; } "
            "QToolButton:hover { background-color: rgba(128, 128, 128, 0.2); }"
        )
        self.account_btn.clicked.connect(self._show_account_menu)
        msg_row.addWidget(self.account_btn)

        self.commit_msg_input = QLineEdit(commit_group)
        self.commit_msg_input.setPlaceholderText(self.tr("Summary (required)"))
        self.commit_msg_input.textChanged.connect(self._on_commit_text_changed)
        msg_row.addWidget(self.commit_msg_input, 1)
        commit_layout.addLayout(msg_row)

        # Description text edit
        self.commit_desc_input = QTextEdit(commit_group)
        self.commit_desc_input.setPlaceholderText(self.tr("Description (optional)"))
        self.commit_desc_input.setFixedHeight(60)
        self.commit_desc_input.textChanged.connect(self._on_commit_text_changed)
        commit_layout.addWidget(self.commit_desc_input)

        # Commit button row (Amend + Commit Button)
        btn_row = QHBoxLayout()
        self.amend_cb = QCheckBox(self.tr("Amend"), commit_group)
        self.amend_cb.toggled.connect(self._on_amend_toggled)
        btn_row.addWidget(self.amend_cb)

        btn_row.addStretch()

        self.commit_btn = QPushButton(self.tr("Commit"), commit_group)
        self._update_commit_btn_theme()
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self._on_commit_clicked)
        btn_row.addWidget(self.commit_btn)
        commit_layout.addLayout(btn_row)

        left_widget.setMinimumWidth(220)
        left_layout.addWidget(commit_group)
        self.splitter.addWidget(left_widget)

        # -------------------------------------------------------------
        # Right Column (Diff View + Empty States)
        # -------------------------------------------------------------
        right_widget = QWidget(self)
        right_widget.setMinimumWidth(300)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Diff View
        self.diff_view = DiffView(right_widget)
        right_layout.addWidget(self.diff_view)

        # Empty state widget for clean repo
        self.clean_state_widget = QWidget(right_widget)
        clean_layout = QVBoxLayout(self.clean_state_widget)
        clean_layout.setAlignment(Qt.AlignCenter)
        clean_layout.setSpacing(8)

        self.clean_title = QLabel(self.tr("No changes"), self.clean_state_widget)
        self.clean_title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: palette(placeholder-text);"
        )
        self.clean_title.setAlignment(Qt.AlignCenter)
        clean_layout.addWidget(self.clean_title)

        self.clean_quote = QLabel("", self.clean_state_widget)
        self.clean_quote.setStyleSheet(
            "font-size: 12px; font-style: italic; color: palette(placeholder-text);"
        )
        self.clean_quote.setAlignment(Qt.AlignCenter)
        self.clean_quote.setWordWrap(True)
        clean_layout.addWidget(self.clean_quote)

        self.clean_author = QLabel("", self.clean_state_widget)
        self.clean_author.setStyleSheet("font-size: 11px; color: palette(placeholder-text);")
        self.clean_author.setAlignment(Qt.AlignCenter)
        clean_layout.addWidget(self.clean_author)

        self.clean_state_widget.setVisible(False)
        right_layout.addWidget(self.clean_state_widget)

        self.splitter.addWidget(right_widget)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 6)
        self.splitter.splitterMoved.connect(lambda *_: self.state_changed.emit())

        # Setup shortcut: Ctrl+Enter to commit
        commit_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        commit_shortcut.activated.connect(self._on_commit_shortcut)

    def load_repos(self, select_path: str | None = None) -> None:
        """Populates the repository dropdown from registry."""
        self.repo_combo.blockSignals(True)
        self.repo_combo.clear()

        repos = repo_registry.list_repos(self._conn)
        if not repos:
            self.repo_combo.addItem(self.tr("No repositories"))
            self.repo_combo.setEnabled(False)
            self.repo_combo.blockSignals(False)
            self._show_zero_repos_state()
            return

        self.repo_combo.setEnabled(True)
        target_idx = 0
        for i, r in enumerate(repos):
            display = r.display_name
            if r.is_missing:
                display = f"⚠️ {display} ({self.tr('missing')})"
            self.repo_combo.addItem(display, r.path)
            if select_path and r.path == select_path:
                target_idx = i

        self.repo_combo.setCurrentIndex(target_idx)
        self.repo_combo.blockSignals(False)

        selected_path = self.repo_combo.currentData()
        if selected_path:
            self._open_repo_by_path(selected_path)

    def set_repo(self, repo: RepoHandle | None) -> None:
        self._repo = repo
        self.branch_switcher.set_repo(repo)
        self.diff_view.set_repo(repo)
        self.refresh()

    def _open_repo_by_path(self, path: str) -> None:
        # Save current repo state (draft text, selections) before switching
        if self._repo:
            current_p = str(self._repo.path)
            self._commit_drafts[current_p] = self.get_current_repo_state()

        # Check if missing
        if not Path(path).exists():
            reply = QMessageBox.warning(
                self,
                self.tr("Repository Missing"),
                self.tr(
                    f"The repository at '{path}' was moved or deleted.\n"
                    f"Would you like to locate it or remove it from Wrench?"
                ),
                QMessageBox.Open | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Open:
                new_dir = QFileDialog.getExistingDirectory(self, self.tr("Locate Repository"))
                if new_dir:
                    repo_registry.relocate_repo(self._conn, path, new_dir)
                    self.load_repos(select_path=new_dir)
                    return
            elif reply == QMessageBox.Discard:
                repo_registry.remove_repo(self._conn, path)
                self.load_repos()
                return
            return

        try:
            repo = engine.open_repo(path)
            repo_registry.touch_repo(self._conn, path)
            self.set_repo(repo)

            # Restore draft message and selections for this repo if one existed
            if path in self._commit_drafts:
                cached = self._commit_drafts[path]
                if isinstance(cached, dict):
                    self.restore_repo_state(cached)
                elif isinstance(cached, tuple):
                    msg, desc = cached
                    self.commit_msg_input.setText(msg)
                    self.commit_desc_input.setPlainText(desc)
            else:
                self.commit_msg_input.blockSignals(True)
                self.commit_desc_input.blockSignals(True)
                self.commit_msg_input.clear()
                self.commit_desc_input.clear()
                self.commit_msg_input.blockSignals(False)
                self.commit_desc_input.blockSignals(False)

            self.repo_changed.emit(path)
        except Exception as e:
            logger.error("Failed to open repo at %s: %s", path, e)
            QMessageBox.critical(
                self,
                self.tr("Open Repository Error"),
                self.tr(f"Could not open repository at '{path}': {e}"),
            )

    def _on_repo_combo_changed(self, index: int) -> None:
        path = self.repo_combo.currentData()
        if path:
            self._open_repo_by_path(path)

    def _show_forge_menu(self) -> None:
        menu = QMenu(self)
        if self._repo:
            repo_path = str(self._repo.path)
            try:
                row = self._conn.execute(
                    "SELECT id FROM repos WHERE path = ?", (repo_path,)
                ).fetchone()
                if row:
                    links = forge_accounts.list_links_for_repo(self._conn, row[0])
                    if links:
                        for link in links:
                            acc = forge_accounts.get_account_full(self._conn, link.forge_account_id)
                            label = acc.label if acc else "Account"
                            slug = f"{link.owner_slug}/{link.repo_slug}"
                            action = menu.addAction(f"🔗 {link.remote_name}: {label} ({slug})")
                            action.setEnabled(False)
                        menu.addSeparator()
            except Exception as e:
                logger.debug("Failed querying forge links for menu: %s", e)

        act_link = menu.addAction(self.tr("Link Repository to Forge…"))
        act_link.triggered.connect(
            lambda: self.link_repo_requested.emit(str(self._repo.path) if self._repo else "")
        )

        act_accounts = menu.addAction(self.tr("Manage Forge Accounts…"))
        act_accounts.triggered.connect(self.forge_accounts_requested.emit)

        menu.exec(self.forge_btn.mapToGlobal(QPoint(0, self.forge_btn.height())))

    def _on_branch_switched(self, branch_name: str) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Refreshes the file list, branch display, and diff view."""
        if not self._repo:
            self._show_zero_repos_state()
            return

        try:
            self._current_status = engine.get_status(self._repo)
            self.branch_switcher.refresh()
            self._update_conflict_banner()
            self._populate_files_list()
            self._update_commit_button()

            # Check MERGE_MSG prefill
            if self._current_status and self._current_status.merge_in_progress:
                if not self.commit_msg_input.text().strip():
                    merge_msg_file = Path(self._repo.path) / ".git" / "MERGE_MSG"
                    if merge_msg_file.exists():
                        try:
                            content = merge_msg_file.read_text(
                                encoding="utf-8", errors="replace"
                            ).strip()
                            if content:
                                lines = content.split("\n", 1)
                                self.commit_msg_input.setText(lines[0].strip())
                                if len(lines) > 1:
                                    self.commit_desc_input.setPlainText(lines[1].strip())
                        except Exception as e:
                            logger.debug("Failed to read MERGE_MSG: %s", e)
        except Exception as e:
            logger.error("Failed to refresh status: %s", e)

    def _update_conflict_banner(self) -> None:
        if not self._current_status:
            self.conflict_banner.setVisible(False)
            return

        if self._current_status.has_conflicts:
            self.conflict_banner.setVisible(True)
            self.conflict_label.setText(
                self.tr("⚠️ Merge conflict in progress — resolve conflicts before committing")
            )
            self.conflict_btn.setText(self.tr("Resolve Conflicts…"))
            self.conflict_btn.setVisible(True)
        elif self._current_status.merge_in_progress:
            self.conflict_banner.setVisible(True)
            self.conflict_label.setText(
                self.tr("Merge in progress — all conflicts resolved. Commit to conclude merge.")
            )
            self.conflict_btn.setVisible(False)
        elif self._current_status.rebase_in_progress:
            self.conflict_banner.setVisible(True)
            self.conflict_label.setText(
                self.tr("Rebase in progress — all conflicts resolved. Continue rebase.")
            )
            self.conflict_btn.setText(self.tr("Continue Rebase"))
            self.conflict_btn.setVisible(True)
        else:
            self.conflict_banner.setVisible(False)

    def _update_repo_combo_theme(self) -> None:
        """Updates repo combo styling based on active theme."""
        if not hasattr(self, "repo_combo"):
            return
        if is_dark_theme(self):
            # In dark mode: exactly untouched original stylesheet
            self.repo_combo.setStyleSheet(
                "QComboBox { border: none; font-weight: bold; font-size: 13px; "
                "padding: 4px; background: transparent; color: palette(window-text); } "
                "QComboBox:hover { background-color: rgba(128, 128, 128, 0.1); "
                "border-radius: 3px; } "
                "QComboBox::drop-down { border: none; width: 16px; } "
                "QComboBox QAbstractItemView { "
                "background-color: palette(base); color: palette(text); "
                "selection-background-color: palette(highlight); "
                "selection-color: palette(highlighted-text); "
                "border: 1px solid rgba(128, 128, 128, 0.25); border-radius: 4px; padding: 2px; }"
            )
        else:
            # In light mode: dark text (#4c4f69) so repository name is never white/invisible
            self.repo_combo.setStyleSheet(
                "QComboBox { border: none; font-weight: bold; font-size: 13px; "
                "padding: 4px; background: transparent; color: #4c4f69; } "
                "QComboBox:hover { background-color: rgba(0, 0, 0, 0.06); border-radius: 3px; } "
                "QComboBox::drop-down { border: none; width: 16px; } "
                "QComboBox QAbstractItemView { "
                "background-color: #ffffff; color: #4c4f69; "
                "selection-background-color: #1e66f5; "
                "selection-color: #ffffff; "
                "border: 1px solid rgba(76, 79, 105, 0.2); border-radius: 4px; padding: 2px; }"
            )

    def _update_commit_btn_theme(self) -> None:
        """Updates commit button styling based on active theme."""
        if not hasattr(self, "commit_btn"):
            return
        if is_dark_theme(self):
            # In dark mode: untouched native Qt styling (no stylesheet)
            self.commit_btn.setStyleSheet("")
        else:
            # In light mode: sapphire primary button with white text (not washed-out grey)
            self.commit_btn.setStyleSheet(
                "QPushButton { background-color: #1e66f5; color: #ffffff; font-weight: bold; "
                "font-size: 12px; padding: 5px 12px; border: none; border-radius: 4px; } "
                "QPushButton:hover { background-color: #1857d4; color: #ffffff; } "
                "QPushButton:pressed { background-color: #154bb8; color: #ffffff; } "
                "QPushButton:disabled { background-color: #e6e9ef; color: #7c7f93; "
                "font-weight: bold; font-size: 12px; padding: 5px 12px; "
                "border: 1px solid rgba(76, 79, 105, 0.2); border-radius: 4px; }"
            )

    def _update_conflict_banner_theme(self) -> None:
        """Updates the conflict banner styling according to current theme."""
        if not hasattr(self, "conflict_banner") or not hasattr(self, "conflict_label"):
            return
        is_dark = is_dark_theme(self)
        mode_key = "dark" if is_dark else "light"
        styles = CONFLICT_BANNER_STYLES[mode_key]
        self.conflict_banner.setStyleSheet(f"QFrame {{ {styles['frame']} }}")
        self.conflict_label.setStyleSheet(styles["label"])

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if getattr(self, "_refreshing_theme", False):
            return
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self._refreshing_theme = True
            try:
                self.refresh_theme()
            finally:
                self._refreshing_theme = False

    def refresh_theme(self) -> None:
        """Refreshes all theme-dependent elements in ChangesTab."""
        self._update_repo_combo_theme()
        self._update_commit_btn_theme()
        self._update_conflict_banner_theme()
        if hasattr(self, "branch_switcher"):
            self.branch_switcher._update_display()
        if hasattr(self, "files_list"):
            for i in range(self.files_list.count()):
                item = self.files_list.item(i)
                w = self.files_list.itemWidget(item)
                if isinstance(w, FileListItemWidget):
                    w.refresh_theme()
        if hasattr(self, "diff_view"):
            self.diff_view.refresh_theme()
        # Re-apply palette-based styles on secondary labels
        if hasattr(self, "files_count_label"):
            self.files_count_label.setStyleSheet(
                "font-size: 11px; color: palette(placeholder-text);"
            )
        if hasattr(self, "clean_title"):
            self.clean_title.setStyleSheet(
                "font-size: 16px; font-weight: bold; color: palette(placeholder-text);"
            )
        if hasattr(self, "clean_quote"):
            self.clean_quote.setStyleSheet(
                "font-size: 12px; font-style: italic; color: palette(placeholder-text);"
            )
        if hasattr(self, "clean_author"):
            self.clean_author.setStyleSheet("font-size: 11px; color: palette(placeholder-text);")

    def _on_conflict_btn_clicked(self) -> None:
        if not self._current_status:
            return
        if self._current_status.rebase_in_progress and not self._current_status.has_conflicts:
            self._continue_rebase()
        else:
            self._resolve_conflicts()

    def _continue_rebase(self) -> None:
        if not self._repo:
            return
        try:
            res = engine.rebase_continue(self._repo)
            if res.status == "conflict":
                QMessageBox.warning(
                    self,
                    self.tr("Rebase Conflict"),
                    self.tr(
                        "More conflicts occurred while continuing rebase. Please resolve them."
                    ),
                )
            self.refresh()
        except Exception as e:
            logger.error("Failed to continue rebase: %s", e)
            QMessageBox.critical(self, self.tr("Rebase Error"), str(e))

    def _resolve_conflicts(self, target_path: str | None = None) -> None:
        if not self._repo:
            return
        mode = (
            "rebase"
            if (self._current_status and self._current_status.rebase_in_progress)
            else "merge"
        )

        if target_path:
            dialog = MergeDialog(self._repo, target_path, mode=mode, parent=self)
            if dialog.exec():
                self.refresh()
            return

        conflicts: list[str] = []
        try:
            r = self._repo.pygit2_repo
            r.index.read()
            if r.index.conflicts is not None:
                for entry_tuple in r.index.conflicts:
                    for entry in entry_tuple:
                        if entry is not None and entry.path not in conflicts:
                            conflicts.append(entry.path)
        except Exception as e:
            logger.debug("Could not read conflicts: %s", e)

        if not conflicts:
            QMessageBox.information(
                self,
                self.tr("No Conflicts"),
                self.tr("No unresolved conflicts were found in the index."),
            )
            return

        for p in conflicts:
            dialog = MergeDialog(self._repo, p, mode=mode, parent=self)
            if not dialog.exec():
                break
        self.refresh()

    def _populate_files_list(self) -> None:
        if not self._current_status:
            return

        # Keep existing checked state map: path -> checked
        checked_map = {}
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            w = self.files_list.itemWidget(item)
            if isinstance(w, FileListItemWidget):
                checked_map[w.path] = w.is_checked()

        self.files_list.clear()

        # Build list of all changed items (staged, unstaged, untracked)
        items: list[tuple[str, str]] = []  # (path, change_type)

        # Stage / Unstaged / Untracked files
        for f in self._current_status.staged:
            items.append((f.path, f.status_code))
        for f in self._current_status.unstaged:
            if not any(f.path == p for p, _ in items):
                items.append((f.path, f.status_code))
        for filepath in self._current_status.untracked:
            if not any(filepath == p for p, _ in items):
                items.append((filepath, "?"))

        total_files = len(items)
        self.files_count_label.setText(
            self.tr(f"{total_files} changed file{'s' if total_files != 1 else ''}")
        )

        if total_files == 0:
            self._show_clean_state()
            return

        self.clean_state_widget.setVisible(False)
        self.diff_view.setVisible(True)

        for path, code in sorted(items, key=lambda x: x[0]):
            # Default to checked if newly detected, else respect previous checkbox state
            is_chk = checked_map.get(path, True)
            widget = FileListItemWidget(path, code, checked=is_chk)
            widget.checked_changed.connect(self._on_item_checked_changed)

            item = QListWidgetItem(self.files_list)
            item.setSizeHint(widget.sizeHint())
            item.setData(Qt.UserRole, path)
            self.files_list.addItem(item)
            self.files_list.setItemWidget(item, widget)

        self._update_select_all_state()

        # Reselect previous file or first file
        if self._selected_file:
            for i in range(self.files_list.count()):
                item = self.files_list.item(i)
                if item.data(Qt.UserRole) == self._selected_file:
                    self.files_list.setCurrentItem(item)
                    self._show_file_diff(self._selected_file)
                    return

        if self.files_list.count() > 0:
            first_item = self.files_list.item(0)
            self.files_list.setCurrentItem(first_item)
            self._show_file_diff(first_item.data(Qt.UserRole))

    def _show_clean_state(self) -> None:
        self.diff_view.setVisible(False)
        self.clean_state_widget.setVisible(True)
        quote, author = random.choice(PROGRAMMING_QUOTES)
        self.clean_quote.setText(f'"{quote}"')
        self.clean_author.setText(f"— {author}")

    def _show_zero_repos_state(self) -> None:
        self.files_list.clear()
        self.files_count_label.setText(self.tr("No repository open"))
        self._show_clean_state()
        self.clean_title.setText(self.tr("No repository open"))
        self.clean_quote.setText(self.tr("Open or clone a repository to get started."))
        self.clean_author.setText("")

    def _show_file_diff(self, path: str) -> None:
        if not self._repo:
            return
        self._selected_file = path
        self.diff_view.set_file(path, staged=False)

    def _on_file_item_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if path:
            self._show_file_diff(path)
            self.state_changed.emit()

    def _on_item_checked_changed(self) -> None:
        self._update_select_all_state()
        self._update_commit_button()
        self.state_changed.emit()

    def _update_select_all_state(self) -> None:
        total = self.files_list.count()
        if total == 0:
            self.select_all_cb.blockSignals(True)
            self.select_all_cb.setCheckState(Qt.Unchecked)
            self.select_all_cb.blockSignals(False)
            return

        checked_count = sum(
            1
            for i in range(total)
            if (w := self.files_list.itemWidget(self.files_list.item(i)))
            and isinstance(w, FileListItemWidget)
            and w.is_checked()
        )

        self.select_all_cb.blockSignals(True)
        if checked_count == total:
            self.select_all_cb.setCheckState(Qt.Checked)
        elif checked_count == 0:
            self.select_all_cb.setCheckState(Qt.Unchecked)
        else:
            self.select_all_cb.setCheckState(Qt.PartiallyChecked)
        self.select_all_cb.blockSignals(False)

    def _on_select_all_toggled(self, state: int) -> None:
        target_checked = state == Qt.Checked or state == 2 or self.select_all_cb.isChecked()
        for i in range(self.files_list.count()):
            item = self.files_list.item(i)
            w = self.files_list.itemWidget(item)
            if isinstance(w, FileListItemWidget):
                w.set_checked(target_checked, emit_signal=False)
        self._update_select_all_state()
        self._update_commit_button()
        self.state_changed.emit()

    def _on_commit_text_changed(self) -> None:
        # 72-char soft limit visual indication
        text_len = len(self.commit_msg_input.text())
        if text_len > 72:
            mode = "dark" if is_dark_theme(self) else "light"
            warning_color = ACCENT_COLORS[mode]["warning"]
            self.commit_msg_input.setStyleSheet(
                f"QLineEdit {{ border: 1px solid {warning_color}; }}"
            )
        else:
            self.commit_msg_input.setStyleSheet("")
        self._update_commit_button()
        self.state_changed.emit()

    def _on_amend_toggled(self, checked: bool) -> None:
        if not self._repo:
            return
        if checked:
            try:
                log = engine.get_log(self._repo, limit=1)
                if log:
                    last_commit = log[0]
                    self._previous_untracked_msg = self.commit_msg_input.text()
                    lines = last_commit.message.split("\n", 1)
                    self.commit_msg_input.setText(lines[0])
                    if len(lines) > 1:
                        self.commit_desc_input.setPlainText(lines[1].strip())
            except Exception as e:
                logger.error("Failed to load last commit for amend: %s", e)
        else:
            if self._previous_untracked_msg:
                self.commit_msg_input.setText(self._previous_untracked_msg)
        self._update_commit_button()
        self.state_changed.emit()

    def _update_commit_button(self) -> None:
        if not self._repo:
            self.commit_btn.setEnabled(False)
            self.commit_btn.setText(self.tr("Commit"))
            return

        has_msg = bool(self.commit_msg_input.text().strip())
        checked_count = sum(
            1
            for i in range(self.files_list.count())
            if (w := self.files_list.itemWidget(self.files_list.item(i)))
            and isinstance(w, FileListItemWidget)
            and w.is_checked()
        )

        branch_name = self._current_status.branch_name if self._current_status else "main"
        is_detached = self._current_status.is_detached_head if self._current_status else False
        is_unborn = not (self._current_status.head_sha if self._current_status else False)

        if self.amend_cb.isChecked():
            btn_text = self.tr(f"Amend commit on {branch_name}")
        elif is_detached:
            btn_text = self.tr("Commit on detached HEAD")
        elif is_unborn:
            btn_text = self.tr("Create initial commit")
        else:
            btn_text = self.tr(f"Commit to {branch_name}")

        self.commit_btn.setText(btn_text)
        can_commit = has_msg and (checked_count > 0 or self.amend_cb.isChecked())
        self.commit_btn.setEnabled(can_commit)

        if not can_commit:
            if not has_msg:
                self.commit_btn.setToolTip(self.tr("Enter a commit summary to commit"))
            else:
                self.commit_btn.setToolTip(self.tr("Select at least one file to commit"))
        else:
            self.commit_btn.setToolTip("")

    def _on_commit_shortcut(self) -> None:
        if self.commit_btn.isEnabled():
            self._on_commit_clicked()

    def _on_commit_clicked(self) -> None:
        if not self._repo or not self.commit_btn.isEnabled():
            return

        summary = self.commit_msg_input.text().strip()
        desc = self.commit_desc_input.toPlainText().strip()
        full_msg = f"{summary}\n\n{desc}".strip() if desc else summary
        is_amend = self.amend_cb.isChecked()

        # 1. Process contention & lock guard check
        from wrench.core.recovery.classifier import diagnose_error
        from wrench.core.recovery.process_guard import acquire_repo_guard
        from wrench.ui.recovery.busy_dialog import BusyDialog
        from wrench.ui.recovery.recovery_dialog import RecoveryDialog

        guard = acquire_repo_guard(self._repo.path, timeout=1.5)
        if guard.status == "busy":
            busy_dlg = BusyDialog(self._repo.path, guard, parent=self)
            if busy_dlg.exec() != BusyDialog.Accepted:
                return

        try:
            staged_paths = (
                {f.path for f in self._current_status.staged} if self._current_status else set()
            )

            # Stage newly selected files and unstage deselected files
            for i in range(self.files_list.count()):
                w = self.files_list.itemWidget(self.files_list.item(i))
                if isinstance(w, FileListItemWidget):
                    if w.is_checked():
                        # Only stage if not already staged/partially staged to preserve hunk staging
                        if w.path not in staged_paths:
                            engine.stage_file(self._repo, w.path)
                    else:
                        # If unchecked but staged, unstage it
                        if w.path in staged_paths:
                            engine.unstage_file(self._repo, w.path)

            engine.commit(self._repo, full_msg, amend=is_amend)

            # Clear inputs upon successful commit
            self.commit_msg_input.clear()
            self.commit_desc_input.clear()
            self.amend_cb.setChecked(False)

            self.refresh()
        except NothingToCommitError:
            logger.info("Commit requested with nothing to commit.")
            QMessageBox.information(
                self,
                self.tr("Nothing to Commit"),
                self.tr(
                    "Your working tree is clean. There are no staged or modified files to commit."
                ),
            )
            self.commit_msg_input.clear()
            self.commit_desc_input.clear()
            self.amend_cb.setChecked(False)
            self.refresh()
        except Exception as e:
            logger.error("Commit failed: %s", e)
            report = diagnose_error(
                e,
                repo_path=self._repo.path,
                stderr=getattr(e, "stderr", None) or str(e),
                stdout=getattr(e, "stdout", None),
                command=["git", "commit", "-m", full_msg],
            )
            recovery_dlg = RecoveryDialog(
                report,
                repo_path=self._repo.path,
                context={"message": full_msg, "lock_path": getattr(guard, "lock_path", None)},
                parent=self,
            )

            def _on_recovery_done(action_id: str) -> None:
                if action_id in ("commit_no_verify", "auto_format_and_retry"):
                    self.commit_msg_input.clear()
                    self.commit_desc_input.clear()
                    self.amend_cb.setChecked(False)
                self.refresh()

            recovery_dlg.action_completed.connect(_on_recovery_done)
            recovery_dlg.exec()

    def _show_file_context_menu(self, pos: QPoint) -> None:
        item = self.files_list.itemAt(pos)
        if not item or not self._repo:
            return

        path = item.data(Qt.UserRole)
        menu = QMenu(self)

        # Check if file has conflict
        has_conflict = False
        try:
            r = self._repo.pygit2_repo
            r.index.read()
            if r.index.conflicts is not None:
                for ancestor, ours, theirs in r.index.conflicts:
                    ep = (
                        (ours.path if ours else None)
                        or (theirs.path if theirs else None)
                        or (ancestor.path if ancestor else None)
                    )
                    if ep == path:
                        has_conflict = True
                        break
        except Exception:
            pass

        if has_conflict:
            act_resolve = menu.addAction(self.tr("Resolve Conflict in 3-Way Tool…"))
            act_resolve.triggered.connect(lambda: self._resolve_conflicts(path))
            menu.addSeparator()

        act_stage = menu.addAction(self.tr("Stage File"))
        act_stage.triggered.connect(lambda: self._stage_single_file(path))

        act_unstage = menu.addAction(self.tr("Unstage File"))
        act_unstage.triggered.connect(lambda: self._unstage_single_file(path))

        act_discard = menu.addAction(self.tr("Discard Changes…"))
        act_discard.triggered.connect(lambda: self._discard_single_file(path))

        menu.addSeparator()

        act_copy_rel = menu.addAction(self.tr("Copy Relative Path"))
        act_copy_rel.triggered.connect(lambda: QApplication.clipboard().setText(path))

        act_copy_abs = menu.addAction(self.tr("Copy Absolute Path"))
        abs_path = str(self._repo.path / path)
        act_copy_abs.triggered.connect(lambda: QApplication.clipboard().setText(abs_path))

        menu.exec(self.files_list.mapToGlobal(pos))

    def _stage_single_file(self, path: str) -> None:
        if self._repo:
            engine.stage_file(self._repo, path)
            self.refresh()

    def _unstage_single_file(self, path: str) -> None:
        if self._repo:
            engine.unstage_file(self._repo, path)
            self.refresh()

    def _discard_single_file(self, path: str) -> None:
        if not self._repo:
            return
        reply = QMessageBox.warning(
            self,
            self.tr("Discard Changes"),
            self.tr(
                f"Are you sure you want to discard changes in '{path}'?\nThis cannot be undone."
            ),
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                engine.discard_file(self._repo, path)
                self.refresh()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    self.tr("Discard Failed"),
                    self.tr(f"Could not discard changes: {e}"),
                )

    def _show_account_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(self.tr("No linked forge account")).setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.tr("Add Forge Account…"))
        menu.exec(self.account_btn.mapToGlobal(QPoint(0, self.account_btn.height())))

    def has_unsaved_commit_text(self) -> bool:
        """Returns True if user has typed text into commit summary or description."""
        return bool(
            self.commit_msg_input.text().strip() or self.commit_desc_input.toPlainText().strip()
        )

    def get_current_repo_state(self) -> dict:
        """Exports current active repo's UI state (selected file, checked files, commit drafts)."""
        checked_paths: list[str] = []
        for i in range(self.files_list.count()):
            w = self.files_list.itemWidget(self.files_list.item(i))
            if isinstance(w, FileListItemWidget) and w.is_checked():
                checked_paths.append(w.path)

        return {
            "selected_file": self._selected_file,
            "checked_files": checked_paths,
            "commit_summary": self.commit_msg_input.text(),
            "commit_desc": self.commit_desc_input.toPlainText(),
            "is_amend": self.amend_cb.isChecked(),
        }

    def restore_repo_state(self, state: dict) -> None:
        """Restores commit drafts and file selections for the active repo."""
        if not isinstance(state, dict):
            return

        summary = state.get("commit_summary", "")
        desc = state.get("commit_desc", "")
        is_amend = bool(state.get("is_amend", False))

        self.commit_msg_input.blockSignals(True)
        self.commit_desc_input.blockSignals(True)
        self.amend_cb.blockSignals(True)

        self.commit_msg_input.setText(summary)
        self.commit_desc_input.setPlainText(desc)
        self.amend_cb.setChecked(is_amend)

        self.commit_msg_input.blockSignals(False)
        self.commit_desc_input.blockSignals(False)
        self.amend_cb.blockSignals(False)

        self._on_commit_text_changed()

        checked_files = set(state.get("checked_files", []))
        if checked_files:
            for i in range(self.files_list.count()):
                item = self.files_list.item(i)
                w = self.files_list.itemWidget(item)
                if isinstance(w, FileListItemWidget):
                    w.set_checked(w.path in checked_files)
            self._update_select_all_state()
            self._update_commit_button()

        selected_file = state.get("selected_file")
        if selected_file:
            self._show_file_diff(selected_file)

    def save_splitter_state(self) -> str:
        """Exports splitter position as hex string."""
        return self.splitter.saveState().toHex().data().decode("utf-8")

    def restore_splitter_state(self, hex_str: str) -> None:
        """Restores splitter position from hex string."""
        if hex_str:
            try:
                byte_array = QByteArray.fromHex(hex_str.encode("utf-8"))
                self.splitter.restoreState(byte_array)
            except Exception as e:
                logger.warning("Could not restore splitter state: %s", e)
