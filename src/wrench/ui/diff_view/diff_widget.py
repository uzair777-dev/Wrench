"""Diff viewer widget with hunk staging and read-only mode."""

import html
import logging

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Diff, RepoHandle
from wrench.ui.theme import DIFF_STYLES, is_dark_theme

logger = logging.getLogger(__name__)


class DiffWidget(QWidget):
    """Shows diff for a selected file with options to stage/unstage whole file or hunks."""

    file_staged = Signal(str, bool)  # path, is_staged
    hunk_staged = Signal(str, str)  # path, hunk_id

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_path: str | None = None
        self._staged: bool = False
        self._diff: Diff | None = None
        self._read_only: bool = False

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header toolbar
        self.toolbar = QWidget(self)
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(4, 4, 4, 4)

        self.title_label = QLabel("No file selected", self)
        self.title_label.setStyleSheet("font-weight: bold;")
        tb_layout.addWidget(self.title_label)

        tb_layout.addStretch()

        self.hunk_combo = QComboBox(self)
        self.hunk_combo.setVisible(False)
        tb_layout.addWidget(self.hunk_combo)

        self.stage_hunk_btn = QPushButton("Stage Hunk", self)
        self.stage_hunk_btn.setVisible(False)
        self.stage_hunk_btn.clicked.connect(self._on_stage_hunk_clicked)
        tb_layout.addWidget(self.stage_hunk_btn)

        self.file_action_btn = QPushButton("Stage File", self)
        self.file_action_btn.setVisible(False)
        self.file_action_btn.clicked.connect(self._on_file_action_clicked)
        tb_layout.addWidget(self.file_action_btn)

        layout.addWidget(self.toolbar)

        # Main text view
        self.editor = QTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setFont(QFont("Monospace", 10))
        self.editor.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self.editor)

    def set_repo(self, repo: RepoHandle):
        self._repo = repo

    def set_file(self, path: str, *, staged: bool):
        self._read_only = False
        self._current_path = path
        self._staged = staged
        self.refresh()

    def set_diff_model(self, diff: Diff, *, title: str = "", read_only: bool = True):
        """Display an explicit Diff model directly (used for historical commits)."""
        self._diff = diff
        self._read_only = read_only
        self._current_path = diff.path
        self.title_label.setText(title or f"Diff: {diff.path}")
        self.hunk_combo.setVisible(False)
        self.stage_hunk_btn.setVisible(False)
        self.file_action_btn.setVisible(False)
        self._render_diff()

    def hunk_count(self) -> int:
        return len(self._diff.hunks) if self._diff else 0

    def refresh(self):
        if self._read_only and self._diff:
            self._render_diff()
            return

        if not self._repo or not self._current_path:
            self.title_label.setText("No file selected")
            self.editor.clear()
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            self.file_action_btn.setVisible(False)
            return

        mode_str = "Staged" if self._staged else "Unstaged"
        self.title_label.setText(f"{mode_str} Diff: {self._current_path}")

        # Update file action button
        self.file_action_btn.setText("Unstage File" if self._staged else "Stage File")
        self.file_action_btn.setVisible(True)

        try:
            self._diff = engine.get_diff(self._repo, self._current_path, staged=self._staged)
        except Exception as e:
            logger.exception("Failed to get diff for %s: %s", self._current_path, e)
            self.editor.setPlainText(f"Error loading diff:\n{e}")
            return

        self._render_diff()

    def changeEvent(self, event: QEvent) -> None:
        """Handles theme and palette changes immediately."""
        super().changeEvent(event)
        if event.type() in (
            QEvent.PaletteChange,
            QEvent.ApplicationPaletteChange,
            QEvent.ThemeChange,
            QEvent.StyleChange,
        ):
            self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-renders current diff and UI under the updated theme."""
        if self._diff:
            self._render_diff()

    def _render_diff(self):
        if not self._diff:
            self.editor.clear()
            return

        is_dark = is_dark_theme(self)
        mode_key = "dark" if is_dark else "light"
        styles = DIFF_STYLES[mode_key]

        self.editor.setStyleSheet(styles["container"])
        hunk_style = styles["hunk"]
        add_style = styles["add"]
        del_style = styles["del"]
        ctx_style = styles["ctx"]

        if self._diff.is_binary:
            self.editor.setHtml(
                "<p style='color: #888888; padding: 10px;'>"
                "<i>Binary file diff not supported.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            return

        if not self._diff.hunks:
            self.editor.setHtml(
                "<p style='color: #888888; padding: 10px;'><i>No changes in this file.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            return

        # Populate hunks combo only if interactive
        if not self._read_only:
            self.hunk_combo.blockSignals(True)
            self.hunk_combo.clear()
            for i, hunk in enumerate(self._diff.hunks, start=1):
                hunk_info = f"-{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count}"
                label = f"Hunk {i} (@@ {hunk_info} @@)"
                self.hunk_combo.addItem(label, hunk.id)
            self.hunk_combo.blockSignals(False)

            self.hunk_combo.setVisible(True)
            self.stage_hunk_btn.setText("Unstage Hunk" if self._staged else "Stage Hunk")
            self.stage_hunk_btn.setVisible(True)

        # Build colored diff HTML
        text_color = "#cdd6f4" if is_dark else "#4c4f69"
        pre_tag = (
            f"<pre style='font-family: monospace; font-size: 12px; line-height: 1.4; "
            f"margin: 0; padding: 6px; color: {text_color};'>"
        )
        html_lines = [pre_tag]
        for hunk in self._diff.hunks:
            hunk_hdr = (
                f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@"
            )
            html_lines.append(f"<div style='{hunk_style}'>{html.escape(hunk_hdr)}</div>")
            for line in hunk.lines:
                escaped = html.escape(f"{line.origin} {line.content}")
                if line.origin == "+":
                    html_lines.append(f"<div style='{add_style}'>{escaped}</div>")
                elif line.origin == "-":
                    html_lines.append(f"<div style='{del_style}'>{escaped}</div>")
                else:
                    html_lines.append(f"<div style='{ctx_style}'>{escaped}</div>")

        html_lines.append("</pre>")
        self.editor.setHtml("".join(html_lines))

    def _on_stage_hunk_clicked(self):
        if self._read_only or not self._repo or not self._current_path or not self._diff:
            return
        idx = self.hunk_combo.currentIndex()
        if idx < 0 or idx >= len(self._diff.hunks):
            return
        hunk_id = self._diff.hunks[idx].id
        try:
            if not self._staged:
                engine.stage_hunk(self._repo, self._current_path, hunk_id)
            self.refresh()
            self.hunk_staged.emit(self._current_path, hunk_id)
        except Exception as e:
            logger.exception("Failed to stage hunk %s: %s", hunk_id, e)

    def _on_file_action_clicked(self):
        if self._read_only or not self._repo or not self._current_path:
            return
        try:
            if self._staged:
                engine.unstage_file(self._repo, self._current_path)
            else:
                engine.stage_file(self._repo, self._current_path)
            self.refresh()
            self.file_staged.emit(self._current_path, not self._staged)
        except Exception as e:
            logger.exception("Failed to stage/unstage file %s: %s", self._current_path, e)


DiffView = DiffWidget
