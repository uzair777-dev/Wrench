"""Diff viewer widget with hunk staging and read-only mode."""

import html
import logging

from PySide6.QtCore import QEvent, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from wrench.core import engine
from wrench.core.engine import Diff, RepoHandle
from wrench.storage.settings_registry import SettingsRegistry, peek_settings_registry
from wrench.ui.theme import (
    DIFF_STYLES,
    DIFF_TEXT_COLOR,
    SECONDARY_TEXT,
    get_banner_style,
    get_secondary_button_style,
    is_dark_theme,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_DIFF_LINES = 5000


class DiffWidget(QWidget):
    """Shows diff for a selected file with options to stage/unstage whole file or hunks."""

    file_staged = Signal(str, bool)  # path, is_staged
    hunk_staged = Signal(str, str)  # path, hunk_id
    full_diff_requested = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        settings_registry: SettingsRegistry | None = None,
    ):
        super().__init__(parent)
        self._repo: RepoHandle | None = None
        self._current_path: str | None = None
        self._staged: bool = False
        self._diff: Diff | None = None
        self._read_only: bool = False
        self._force_full_diff: bool = False
        self._refreshing_theme: bool = False
        self._settings_registry: SettingsRegistry | None = settings_registry

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

        # Inline non-modal large-diff truncation banner
        self.truncation_banner = QFrame(self)
        self.truncation_banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.truncation_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.truncation_banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        banner_layout.setSpacing(8)

        self.truncation_label = QLabel(self.truncation_banner)
        self.truncation_label.setWordWrap(True)
        banner_layout.addWidget(self.truncation_label, 1)

        self.load_full_diff_btn = QPushButton(self.tr("Load Full Diff"), self.truncation_banner)
        self.load_full_diff_btn.clicked.connect(self._on_load_full_diff_clicked)
        banner_layout.addWidget(self.load_full_diff_btn)

        layout.addWidget(self.truncation_banner)

        # Main text view
        self.editor = QTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setFont(QFont("Monospace", 10))
        self.editor.setLineWrapMode(QTextEdit.NoWrap)
        layout.addWidget(self.editor)

        self._apply_banner_theme(is_dark_theme(self))

    def set_settings_registry(self, registry: SettingsRegistry | None) -> None:
        self._settings_registry = registry

    def _effective_max_lines(self) -> int | None:
        return None if self._force_full_diff else DEFAULT_MAX_DIFF_LINES

    def _effective_max_bytes(self) -> int | None:
        if self._force_full_diff:
            return None
        reg = self._settings_registry or peek_settings_registry()
        repo_str = str(self._repo.path) if self._repo else None
        kb = 2048
        if reg is not None:
            val = reg.get_int("performance.max_diff_file_size_kb", repo_str)
            if val > 0:
                kb = val
        return max(1024, kb * 1024)

    def _apply_banner_theme(self, is_dark: bool) -> None:
        style = get_banner_style("warning", is_dark)
        self.truncation_banner.setStyleSheet(
            f"QFrame {{ background-color: {style['bg']}; border: 1px solid {style['border']}; "
            f"border-radius: 4px; }}"
        )
        self.truncation_label.setStyleSheet(
            f"color: {style['fg']}; font-weight: bold; border: none; background: transparent;"
        )
        if hasattr(self, "load_full_diff_btn"):
            self.load_full_diff_btn.setStyleSheet(get_secondary_button_style(is_dark, compact=True))

    def _on_load_full_diff_clicked(self) -> None:
        prev_diff = self._diff
        self._force_full_diff = True
        self.full_diff_requested.emit()
        if not self._read_only:
            self.refresh()
        elif self._diff is prev_diff and self._diff is not None:
            self._render_diff()

    def set_repo(self, repo: RepoHandle):
        self._repo = repo

    def set_file(self, path: str, *, staged: bool):
        self._read_only = False
        self._current_path = path
        self._staged = staged
        self._force_full_diff = False
        self.refresh()

    def set_diff_model(
        self,
        diff: Diff,
        *,
        title: str = "",
        read_only: bool = True,
        reset_force: bool = True,
    ):
        """Display an explicit Diff model directly (used for historical commits)."""
        self._diff = diff
        self._read_only = read_only
        self._current_path = diff.path
        if reset_force:
            self._force_full_diff = False
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
            self.truncation_banner.setVisible(False)
            return

        mode_str = "Staged" if self._staged else "Unstaged"
        self.title_label.setText(f"{mode_str} Diff: {self._current_path}")

        # Update file action button
        self.file_action_btn.setText("Unstage File" if self._staged else "Stage File")
        self.file_action_btn.setVisible(True)

        try:
            self._diff = engine.get_diff(
                self._repo,
                self._current_path,
                staged=self._staged,
                max_lines=self._effective_max_lines(),
                max_bytes=self._effective_max_bytes(),
            )
        except Exception as e:
            logger.exception("Failed to get diff for %s: %s", self._current_path, e)
            self.editor.setPlainText(f"Error loading diff:\n{e}")
            self.truncation_banner.setVisible(False)
            return

        self._render_diff()

    def changeEvent(self, event: QEvent) -> None:
        """Handles theme and palette changes immediately."""
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
        """Re-renders current diff and UI under the updated theme."""
        self._apply_banner_theme(is_dark_theme(self))
        if self._diff:
            self._render_diff()

    def _render_diff(self):
        if not self._diff:
            self.editor.clear()
            self.truncation_banner.setVisible(False)
            return

        is_dark = is_dark_theme(self)
        self._apply_banner_theme(is_dark)
        mode_key = "dark" if is_dark else "light"
        styles = DIFF_STYLES[mode_key]

        self.editor.setStyleSheet(styles["container"])
        hunk_style = styles["hunk"]
        add_style = styles["add"]
        del_style = styles["del"]
        ctx_style = styles["ctx"]

        sec_color = SECONDARY_TEXT["dark" if is_dark else "light"]
        if self._diff.is_binary:
            self.editor.setHtml(
                f"<p style='color: {sec_color}; padding: 10px;'>"
                "<i>Binary file diff not supported.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            self.truncation_banner.setVisible(False)
            return

        if not self._diff.hunks:
            self.editor.setHtml(
                f"<p style='color: {sec_color}; padding: 10px;'><i>No changes in this file.</i></p>"
            )
            self.hunk_combo.setVisible(False)
            self.stage_hunk_btn.setVisible(False)
            self.truncation_banner.setVisible(False)
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

        # Build colored diff HTML with viewport-safe line cap unless full diff forced
        text_color = DIFF_TEXT_COLOR["dark" if is_dark else "light"]
        pre_tag = (
            f"<pre style='font-family: monospace; font-size: 12px; line-height: 1.4; "
            f"margin: 0; padding: 6px; color: {text_color};'>"
        )
        in_mem_total = sum(len(h.lines) for h in self._diff.hunks)
        total_lines = max(getattr(self._diff, "total_lines", 0) or 0, in_mem_total)
        cap = None if self._force_full_diff else DEFAULT_MAX_DIFF_LINES
        use_compact_css = cap is None and in_mem_total > DEFAULT_MAX_DIFF_LINES

        if use_compact_css:
            html_lines = [
                "<html><head><style>"
                f".h{{{hunk_style}}}.a{{{add_style}}}.d{{{del_style}}}.c{{{ctx_style}}}"
                "</style></head><body>",
                pre_tag,
            ]
        else:
            html_lines = [pre_tag]

        rendered_lines = 0
        was_view_capped = False
        for hunk in self._diff.hunks:
            if cap is not None and rendered_lines >= cap:
                was_view_capped = True
                break
            hunk_hdr = (
                f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@"
            )
            if use_compact_css:
                html_lines.append(f"<span class='h'>{html.escape(hunk_hdr)}</span>\n")
            else:
                html_lines.append(f"<div style='{hunk_style}'>{html.escape(hunk_hdr)}</div>")
            for line in hunk.lines:
                if cap is not None and rendered_lines >= cap:
                    was_view_capped = True
                    break
                escaped = html.escape(f"{line.origin} {line.content}")
                if use_compact_css:
                    cls = "a" if line.origin == "+" else ("d" if line.origin == "-" else "c")
                    html_lines.append(f"<span class='{cls}'>{escaped}</span>\n")
                else:
                    if line.origin == "+":
                        html_lines.append(f"<div style='{add_style}'>{escaped}</div>")
                    elif line.origin == "-":
                        html_lines.append(f"<div style='{del_style}'>{escaped}</div>")
                    else:
                        html_lines.append(f"<div style='{ctx_style}'>{escaped}</div>")
                rendered_lines += 1

        if use_compact_css:
            html_lines.append("</pre></body></html>")
        else:
            html_lines.append("</pre>")

        self.editor.setUpdatesEnabled(False)
        try:
            self.editor.setHtml("".join(html_lines))
        finally:
            self.editor.setUpdatesEnabled(True)

        is_model_truncated = bool(getattr(self._diff, "is_truncated", False))
        show_banner = (not self._force_full_diff) and (is_model_truncated or was_view_capped)
        if show_banner:
            reason = getattr(self._diff, "truncated_reason", None)
            self.truncation_label.setText(
                reason
                or self.tr(
                    f"Showing first {rendered_lines:,} of {total_lines:,} lines "
                    "for smooth scrolling."
                )
            )
            self.truncation_banner.setVisible(True)
        else:
            self.truncation_banner.setVisible(False)

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
