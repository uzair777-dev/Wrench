"""FR-2.1: High-performance syntax-highlighted diff viewer with hunk staging."""

import html
import logging

from PySide6.QtCore import Signal
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

logger = logging.getLogger(__name__)


class DiffView(QWidget):
    hunk_staged = Signal(str, str)  # (path, hunk_id)
    file_staged = Signal(str, bool)  # (path, staged)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_path: str | None = None
        self._staged: bool = False
        self._diff: Diff | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header toolbar
        header = QHBoxLayout()
        self.title_label = QLabel("No file selected", self)
        self.title_label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(self.title_label)

        header.addStretch()

        self.hunk_combo = QComboBox(self)
        self.hunk_combo.setVisible(False)
        header.addWidget(self.hunk_combo)

        self.stage_hunk_btn = QPushButton("Stage Hunk", self)
        self.stage_hunk_btn.setVisible(False)
        self.stage_hunk_btn.clicked.connect(self._on_stage_hunk_clicked)
        header.addWidget(self.stage_hunk_btn)

        self.file_action_btn = QPushButton("Stage File", self)
        self.file_action_btn.setVisible(False)
        self.file_action_btn.clicked.connect(self._on_file_action_clicked)
        header.addWidget(self.file_action_btn)

        layout.addLayout(header)

        # Main Diff Editor
        self.editor = QTextEdit(self)
        self.editor.setReadOnly(True)
        font = QFont("monospace", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(font)
        layout.addWidget(self.editor)

    def set_repo(self, repo: RepoHandle):
        self._repo = repo

    def set_file(self, path: str, *, staged: bool):
        self._current_path = path
        self._staged = staged
        self.refresh()

    def hunk_count(self) -> int:
        return len(self._diff.hunks) if self._diff else 0

    def refresh(self):
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

        if self._diff.is_binary:
            self.editor.setHtml(
                "<p style='color: #888; padding: 10px;'>"
                "<i>Binary file diff not supported.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            return

        if not self._diff.hunks:
            self.editor.setHtml(
                "<p style='color: #888; padding: 10px;'>" "<i>No changes in this file.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            return

        # Populate hunks combo
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
        pre_tag = (
            "<pre style='font-family: monospace; font-size: 12px; line-height: 1.4; "
            "margin: 0; padding: 6px;'>"
        )
        html_lines = [pre_tag]
        for hunk in self._diff.hunks:
            hunk_hdr = (
                f"@@ -{hunk.old_start},{hunk.old_count} " f"+{hunk.new_start},{hunk.new_count} @@"
            )
            hunk_style = (
                "color: #0288d1; font-weight: bold; background: #e1f5fe; "
                "padding: 2px 4px; margin-top: 6px;"
            )
            html_lines.append(f"<div style='{hunk_style}'>{html.escape(hunk_hdr)}</div>")
            for line in hunk.lines:
                escaped = html.escape(f"{line.origin} {line.content}")
                if line.origin == "+":
                    style = "color: #2e7d32; background-color: #e8f5e9; padding: 1px 4px;"
                    html_lines.append(f"<div style='{style}'>{escaped}</div>")
                elif line.origin == "-":
                    style = "color: #c62828; background-color: #ffebee; padding: 1px 4px;"
                    html_lines.append(f"<div style='{style}'>{escaped}</div>")
                else:
                    html_lines.append(f"<div style='padding: 1px 4px;'>{escaped}</div>")

        html_lines.append("</pre>")
        self.editor.setHtml("".join(html_lines))

    def _on_stage_hunk_clicked(self):
        if not self._repo or not self._current_path or not self._diff:
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
        if not self._repo or not self._current_path:
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
