"""FR-2.3: Commit Detail Panel with file list, stats, and embedded DiffWidget."""

import logging

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Commit, FileStat, RepoHandle
from wrench.ui.diff_view.diff_widget import DiffWidget
from wrench.ui.theme import (
    COMMIT_STAT_COLORS,
    get_badge_colors,
    get_signature_badge_qss,
    is_dark_theme,
)
from wrench.ui.widgets.avatar import AvatarWidget, resolve_author_avatar_url

logger = logging.getLogger(__name__)


class CommitDetailPanel(QWidget):
    """Bottom split panel showing metadata, modified files, and read-only diff for a commit."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_commit: Commit | None = None
        self._file_stats: list[FileStat] = []
        self._conn = None
        self._refreshing_theme: bool = False
        self._cached_remote_urls: list[str] | None = None
        self._remote_urls_cached_for: int | None = None

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # Header section (Metadata + Copy SHA)
        header_widget = QWidget(self)
        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 4, 4, 4)
        header_layout.setSpacing(4)

        # Row 1: Author & Verification
        row1_layout = QHBoxLayout()
        row1_layout.setContentsMargins(0, 0, 0, 0)
        row1_layout.setSpacing(8)

        self.avatar_widget = AvatarWidget(size=32, parent=self)
        self.avatar_widget.setVisible(False)
        row1_layout.addWidget(self.avatar_widget)

        author_vbox = QVBoxLayout()
        author_vbox.setContentsMargins(0, 0, 0, 0)
        author_vbox.setSpacing(1)

        self.author_name_label = QLabel("-", self)
        font_author = QFont()
        font_author.setBold(True)
        font_author.setPointSize(10)
        self.author_name_label.setFont(font_author)
        author_vbox.addWidget(self.author_name_label)

        self.author_date_label = QLabel("-", self)
        self.author_date_label.setStyleSheet("color: palette(placeholder-text); font-size: 11px;")
        author_vbox.addWidget(self.author_date_label)

        row1_layout.addLayout(author_vbox)
        row1_layout.addStretch()

        self.signature_badge = QLabel(self)
        self.signature_badge.setFixedHeight(22)
        self.signature_badge.setVisible(False)
        row1_layout.addWidget(self.signature_badge)

        header_layout.addLayout(row1_layout)

        # Row 2: Commit ID & Copy SHA Action
        row2_layout = QHBoxLayout()
        row2_layout.setContentsMargins(0, 2, 0, 0)
        row2_layout.setSpacing(8)

        self.sha_label = QLabel("SHA: -", self)
        self.sha_label.setFont(QFont("Monospace", 9))
        self.sha_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row2_layout.addWidget(self.sha_label)

        self.copy_sha_btn = QPushButton("Copy SHA", self)
        self.copy_sha_btn.setFixedHeight(22)
        self.copy_sha_btn.clicked.connect(self._copy_sha)
        row2_layout.addWidget(self.copy_sha_btn)

        row2_layout.addStretch()
        header_layout.addLayout(row2_layout)

        self.message_edit = QTextEdit(self)
        self.message_edit.setReadOnly(True)
        self.message_edit.setPlaceholderText("Commit message...")
        self.message_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.message_edit.document().documentLayout().documentSizeChanged.connect(
            self._adjust_message_edit_height
        )
        header_layout.addWidget(self.message_edit)

        main_layout.addWidget(header_widget)

        # Splitter: File list on left, DiffWidget on right
        self.splitter = QSplitter(Qt.Horizontal, self)

        # File list table
        self.files_table = QTableWidget(self)
        self.files_table.setMinimumHeight(85)
        self.files_table.setColumnCount(3)
        self.files_table.setHorizontalHeaderLabels(["Status", "File", "+/-"])
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.files_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.files_table.setSelectionMode(QTableWidget.SingleSelection)
        self.files_table.itemSelectionChanged.connect(self._on_file_selected)
        self.splitter.addWidget(self.files_table)

        # DiffWidget
        self.diff_widget = DiffWidget(self)
        self.diff_widget.setMinimumHeight(150)
        self.diff_widget.full_diff_requested.connect(self._on_full_diff_requested)
        self.splitter.addWidget(self.diff_widget)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        main_layout.addWidget(self.splitter)

    def set_compact_vertical_layout(self, enabled: bool) -> None:
        """Switch internal files/diff splitter between horizontal and vertical orientation.

        When enabled=True (3-column mode), files table stacks on top of diff viewer
        vertically, allowing the panel to be much narrower (min 280px).
        """
        if enabled:
            self.splitter.setOrientation(Qt.Orientation.Vertical)
            self.splitter.setSizes([90, 320])
            self.splitter.setStretchFactor(0, 0)
            self.splitter.setStretchFactor(1, 1)
            self.setMinimumWidth(280)
        else:
            self.splitter.setOrientation(Qt.Orientation.Horizontal)
            self.splitter.setSizes([120, 320])
            self.splitter.setStretchFactor(0, 1)
            self.splitter.setStretchFactor(1, 2)
            self.setMinimumWidth(0)

    def _adjust_message_edit_height(self, *_) -> None:
        """Dynamically adjusts message box height to fit wrapped text with bounded upper cap."""
        if not hasattr(self, "message_edit"):
            return
        doc = self.message_edit.document()
        content_h = int(doc.size().height()) + 14
        panel_h = self.height()
        max_allowed = max(80, min(140, int(panel_h * 0.28))) if panel_h > 200 else 130
        target_h = max(34, min(content_h, max_allowed))
        self.message_edit.setFixedHeight(target_h)
        if content_h > max_allowed:
            self.message_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.message_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._adjust_message_edit_height()

    def closeEvent(self, event) -> None:
        if hasattr(self, "avatar_widget"):
            self.avatar_widget.close()
        if hasattr(self, "diff_widget"):
            self.diff_widget.close()
        super().closeEvent(event)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if getattr(self, "_refreshing_theme", False):
            return
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
        ):
            self._refreshing_theme = True
            try:
                self.refresh_theme()
            finally:
                self._refreshing_theme = False

    def refresh_theme(self) -> None:
        """Refreshes diff widget, table item styling, avatar, and header labels on theme change."""
        self.diff_widget.refresh_theme()
        if hasattr(self, "avatar_widget"):
            self.avatar_widget._refresh()
        if hasattr(self, "author_date_label"):
            self.author_date_label.setStyleSheet("color: palette(placeholder-text);")
        if self._file_stats:
            self._populate_files_table()

    def _clear_files_table(self) -> None:
        """Detach and schedule deletion of all cell widgets before clearing rows."""
        for row in range(self.files_table.rowCount()):
            for col in range(self.files_table.columnCount()):
                widget = self.files_table.cellWidget(row, col)
                if widget is not None:
                    self.files_table.removeCellWidget(row, col)
                    widget.setParent(None)
                    widget.deleteLater()
        self.files_table.clearContents()
        self.files_table.setRowCount(0)

    def _populate_files_table(self):
        is_dark = is_dark_theme(self)
        mode = "dark" if is_dark else "light"
        add_col = COMMIT_STAT_COLORS[mode]["add"]
        del_col = COMMIT_STAT_COLORS[mode]["del"]

        self.files_table.blockSignals(True)
        self._clear_files_table()
        self.files_table.setRowCount(len(self._file_stats))
        for row, stat in enumerate(self._file_stats):
            code = stat.change_type.capitalize()[:1]
            status_item = QTableWidgetItem(code)
            status_item.setTextAlignment(Qt.AlignCenter)
            fg, _ = get_badge_colors(code, is_dark=is_dark)
            status_item.setForeground(QColor(fg))
            status_font = status_item.font()
            status_font.setBold(True)
            status_item.setFont(status_font)
            self.files_table.setItem(row, 0, status_item)

            file_item = QTableWidgetItem(stat.path)
            self.files_table.setItem(row, 1, file_item)

            stat_widget = QWidget(self.files_table)
            stat_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            stat_layout = QHBoxLayout(stat_widget)
            stat_layout.setContentsMargins(4, 1, 4, 1)
            stat_layout.setSpacing(6)
            stat_layout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            add_lbl = QLabel(f"+{stat.additions}", stat_widget)
            add_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            add_lbl.setStyleSheet(f"color: {add_col}; font-weight: bold; font-size: 11px;")
            stat_layout.addWidget(add_lbl)

            del_lbl = QLabel(f"-{stat.deletions}", stat_widget)
            del_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            del_lbl.setStyleSheet(f"color: {del_col}; font-weight: bold; font-size: 11px;")
            stat_layout.addWidget(del_lbl)

            self.files_table.setCellWidget(row, 2, stat_widget)
        self.files_table.blockSignals(False)

        if self.splitter.orientation() == Qt.Orientation.Vertical:
            n_files = len(self._file_stats)
            files_h = min(180, max(56, 26 + n_files * 24 + 10))
            total_h = self.splitter.height()
            if total_h < 200:
                total_h = 500
            diff_h = max(200, total_h - files_h)
            self.splitter.setSizes([files_h, diff_h])

    def set_repo(self, repo: RepoHandle | None):
        prev_path = getattr(self._repo, "path", None)
        next_path = getattr(repo, "path", None)
        self._repo = repo
        self._cached_remote_urls = None
        self._remote_urls_cached_for = None
        if repo is None or prev_path != next_path:
            self._file_stats = []
            self._clear_files_table()
        self.diff_widget.set_repo(repo)

    def _resolve_commit_avatar_url(self, commit: Commit) -> str | None:
        conn = getattr(self, "_conn", None)
        close_conn = False
        if not conn:
            try:
                from wrench.storage import db

                conn = db.get_connection()
                close_conn = True
            except Exception:
                conn = None

        try:
            remote_urls = None
            if self._repo:
                repo_ident = id(self._repo)
                if self._remote_urls_cached_for != repo_ident:
                    try:
                        self._cached_remote_urls = [
                            r.url
                            for r in engine.list_remotes(self._repo, db_conn=conn)
                            if hasattr(r, "url") and isinstance(r.url, str)
                        ]
                    except Exception:
                        self._cached_remote_urls = None
                    self._remote_urls_cached_for = repo_ident
                remote_urls = self._cached_remote_urls

            return resolve_author_avatar_url(
                commit.author_name,
                commit.author_email,
                remote_urls=remote_urls,
                db_conn=conn,
            )
        finally:
            if close_conn and conn:
                conn.close()

    def refresh_avatar(self) -> None:
        """Re-resolves and refreshes the active commit avatar (e.g., Gravatar toggle)."""
        if not self._current_commit or not self._repo:
            return
        url = self._resolve_commit_avatar_url(self._current_commit)
        self.avatar_widget.setVisible(True)
        self.avatar_widget.set_avatar(
            url, self._current_commit.author_name or self._current_commit.author_email
        )

    def set_commit(self, commit: Commit | None):
        self._current_commit = commit
        if not commit or not self._repo:
            self.avatar_widget.setVisible(False)
            self.signature_badge.setVisible(False)
            self.author_name_label.setText("-")
            self.sha_label.setText("SHA: -")
            self.sha_label.setToolTip("")
            self.author_date_label.setText("-")
            self.author_date_label.setToolTip("")
            self.message_edit.clear()
            self._adjust_message_edit_height()
            self._clear_files_table()
            self.diff_widget.set_diff_model(
                engine.Diff(path="", is_binary=False, hunks=[]), title="No commit selected"
            )
            return

        url = self._resolve_commit_avatar_url(commit)

        self.avatar_widget.setVisible(True)
        self.avatar_widget.set_avatar(url, commit.author_name or commit.author_email)

        # Verify signature (VP-18, FR-2.9, FR-2.10)
        try:
            sigs = engine.verify_commit_signatures(self._repo, [commit.sha])
            sig = sigs.get(commit.sha)
            is_dark = is_dark_theme(self)
            if sig and sig.state == "verified":
                self.signature_badge.setText(self.tr("✓ Verified"))
                self.signature_badge.setToolTip(
                    self.tr(
                        f"Cryptographically verified signature\n"
                        f"Signer: {sig.signer or 'Unknown'}\n"
                        f"Key ID: {sig.key_fingerprint or 'N/A'}\n"
                        f"Type: {sig.key_type or 'N/A'}"
                    )
                )
                self.signature_badge.setStyleSheet(get_signature_badge_qss("verified", is_dark))
                self.signature_badge.setVisible(True)
            elif sig and sig.state == "unverified_key":
                self.signature_badge.setText(self.tr("? Unverified Key"))
                self.signature_badge.setToolTip(
                    self.tr(
                        f"Valid signature with unverified/unknown public key\n"
                        f"Signer: {sig.signer or 'Unknown'}\n"
                        f"Key ID: {sig.key_fingerprint or 'N/A'}"
                    )
                )
                self.signature_badge.setStyleSheet(
                    get_signature_badge_qss("unverified_key", is_dark)
                )
                self.signature_badge.setVisible(True)
            elif sig and sig.state == "bad":
                self.signature_badge.setText(self.tr("✕ Bad Signature"))
                self.signature_badge.setToolTip(
                    self.tr(f"Signature verification failed!\n{sig.validity_details or ''}")
                )
                self.signature_badge.setStyleSheet(get_signature_badge_qss("bad", is_dark))
                self.signature_badge.setVisible(True)
            else:
                self.signature_badge.setText(self.tr("Unsigned"))
                self.signature_badge.setToolTip(
                    self.tr("This commit does not contain a cryptographic GPG or SSH signature.")
                )
                self.signature_badge.setStyleSheet(get_signature_badge_qss("unsigned", is_dark))
                self.signature_badge.setVisible(True)
        except Exception as e:
            logger.debug("Signature check error: %s", e)
            is_dark = is_dark_theme(self)
            self.signature_badge.setText(self.tr("Unsigned"))
            self.signature_badge.setToolTip(
                self.tr("This commit does not contain a cryptographic GPG or SSH signature.")
            )
            self.signature_badge.setStyleSheet(get_signature_badge_qss("unsigned", is_dark))
            self.signature_badge.setVisible(True)

        full_sha = commit.sha
        short_sha = commit.sha[:8]
        self.sha_label.setText(f"SHA: {short_sha}")
        self.sha_label.setToolTip(f"Full SHA: {full_sha}")

        auth_name = commit.author_name or "Unknown"
        auth_email = commit.author_email or ""
        auth_date = (
            commit.author_date[:19].replace("T", " ") if commit.author_date else "Unknown Date"
        )
        self.author_name_label.setText(auth_name)
        if auth_email:
            self.author_date_label.setText(f"<{auth_email}> • {auth_date}")
        else:
            self.author_date_label.setText(auth_date)
        self.author_date_label.setToolTip(f"Author: {auth_name} <{auth_email}>\nDate: {auth_date}")
        self.message_edit.setPlainText(commit.message)
        self._adjust_message_edit_height()

        # Load file stats
        try:
            self._file_stats = engine.get_commit_file_stats(self._repo, commit.sha)
        except Exception as e:
            logger.exception("Failed to load file stats for %s: %s", commit.sha, e)
            self._file_stats = []

        self._populate_files_table()

        if self._file_stats:
            self.files_table.selectRow(0)
            self._load_file_diff(self._file_stats[0].path)
        else:
            self.diff_widget.set_diff_model(
                engine.Diff(path="", is_binary=False, hunks=[]), title="No file changes"
            )

    def _copy_sha(self):
        if self._current_commit:
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(self._current_commit.sha)

    def _on_file_selected(self):
        selected_rows = self.files_table.selectionModel().selectedRows()
        if not selected_rows or not self._current_commit or not self._repo:
            return
        row = selected_rows[0].row()
        if 0 <= row < len(self._file_stats):
            path = self._file_stats[row].path
            self._load_file_diff(path)

    def _on_full_diff_requested(self) -> None:
        if not self._repo or not self._current_commit:
            return
        current_path = self.diff_widget._current_path
        if current_path:
            self._load_file_diff(current_path, full=True)

    def _load_file_diff(self, path: str, *, full: bool = False):
        if not self._repo or not self._current_commit:
            return
        try:
            max_lines = None if full else self.diff_widget._effective_max_lines()
            max_bytes = None if full else self.diff_widget._effective_max_bytes()
            diff = engine.get_commit_diff(
                self._repo,
                self._current_commit.sha,
                path=path,
                max_lines=max_lines,
                max_bytes=max_bytes,
            )
            self.diff_widget.set_diff_model(
                diff,
                title=f"Commit Diff: {path}",
                read_only=True,
                reset_force=not full,
            )
        except Exception as e:
            logger.exception("Failed to load commit diff for %s: %s", path, e)
