"""Segmented 4-Cell Top Context Bar & Collapsible Git Terminal Drawer (FR-11.9).

Provides:
- Cell 1 (RepoContextCell): Fast repository selector with repo icon & dropdown arrow
- Cell 2 (BranchContextCell): Branch selector with ahead/behind badge
- Cell 3 (SyncActionCell): Smart remote sync button morphing fetch/pull/push/sync
- Cell 4 (QuickActionsStrip): Right-aligned toolbar for undo/pull/push/stash/pop/terminal/palette
- GitTerminalDrawer: Collapsible 180px bottom panel with interactive git subcommand CLI
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from wrench.core.models import BranchSyncStatus
from wrench.ui.icons import get_icon, get_pixmap
from wrench.ui.theme import (
    CONTEXT_BAR_BG_DARK,
    CONTEXT_BAR_BG_LIGHT,
    CONTEXT_BAR_BORDER_DARK,
    CONTEXT_BAR_BORDER_LIGHT,
    CONTEXT_BAR_SUBTITLE_DARK,
    CONTEXT_BAR_SUBTITLE_LIGHT,
    CONTEXT_BAR_TITLE_DARK,
    CONTEXT_BAR_TITLE_LIGHT,
    CONTEXT_BTN_BG_DARK,
    CONTEXT_BTN_BG_LIGHT,
    ICON_COLOR_LATTE,
    ICON_COLOR_MOCHA,
    is_dark_theme,
)


class RepoContextCell(QFrame):
    """Cell 1: Current repository indicator and fast switcher trigger."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(180)
        self._repo_name = "No repository opened"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(22, 22)
        layout.addWidget(self.icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.subtitle_label = QLabel(self.tr("Current repository"), self)
        self.subtitle_label.setStyleSheet("font-size: 10px; font-weight: normal;")
        text_layout.addWidget(self.subtitle_label)

        self.title_label = QLabel(self.tr("No repository ▾"), self)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.repo_name_lbl = self.title_label
        text_layout.addWidget(self.title_label)

        layout.addLayout(text_layout)
        layout.addStretch(1)
        self._refresh_styles()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_repo_name(self, name: str | None) -> None:
        self._repo_name = name or self.tr("No repository")
        self.title_label.setText(f"{self._repo_name} ▾")

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        sub_col = CONTEXT_BAR_SUBTITLE_DARK if is_dark else CONTEXT_BAR_SUBTITLE_LIGHT
        title_col = CONTEXT_BAR_TITLE_DARK if is_dark else CONTEXT_BAR_TITLE_LIGHT
        self.subtitle_label.setStyleSheet(f"font-size: 10px; color: {sub_col};")
        self.title_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {title_col};")
        icon_col = ICON_COLOR_MOCHA if is_dark else ICON_COLOR_LATTE
        self.icon_label.setPixmap(get_pixmap("repo", color=icon_col, size=20))


class BranchContextCell(QFrame):
    """Cell 2: Current branch indicator with sync badge and checkout trigger."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumWidth(200)
        self._branch_name = "—"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(22, 22)
        layout.addWidget(self.icon_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.subtitle_label = QLabel(self.tr("Current branch"), self)
        self.subtitle_label.setStyleSheet("font-size: 10px; font-weight: normal;")
        text_layout.addWidget(self.subtitle_label)

        title_box = QHBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(6)

        self.title_label = QLabel(self.tr("— ▾"), self)
        self.title_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.branch_btn = self.title_label
        title_box.addWidget(self.title_label)

        self.badge_label = QLabel(self)
        self.badge_label.setVisible(False)
        title_box.addWidget(self.badge_label)
        title_box.addStretch(1)

        text_layout.addLayout(title_box)
        layout.addLayout(text_layout)
        layout.addStretch(1)
        self._refresh_styles()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_branch_sync(self, status: BranchSyncStatus) -> None:
        self._branch_name = status.branch_name
        self.title_label.setText(f"{self._branch_name} ▾")

        parts = []
        if status.ahead > 0:
            parts.append(f"{status.ahead}↑")
        if status.behind > 0:
            parts.append(f"{status.behind}↓")

        if parts:
            badge_text = " ".join(parts)
            self.badge_label.setText(f" {badge_text} ")
            self.badge_label.setStyleSheet(
                "background-color: palette(button); color: palette(highlighted-text); "
                "font-size: 10px; font-weight: bold; border-radius: 4px; padding: 1px 4px;"
            )
            self.badge_label.setVisible(True)
        else:
            self.badge_label.setVisible(False)

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        sub_col = CONTEXT_BAR_SUBTITLE_DARK if is_dark else CONTEXT_BAR_SUBTITLE_LIGHT
        title_col = CONTEXT_BAR_TITLE_DARK if is_dark else CONTEXT_BAR_TITLE_LIGHT
        self.subtitle_label.setStyleSheet(f"font-size: 10px; color: {sub_col};")
        self.title_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {title_col};")
        icon_col = ICON_COLOR_MOCHA if is_dark else ICON_COLOR_LATTE
        self.icon_label.setPixmap(get_pixmap("branch", color=icon_col, size=20))


class SyncActionCell(QFrame):
    """Cell 3: Smart dynamic remote sync action button."""

    sync_requested = Signal(str)  # 'fetch' | 'pull' | 'push' | 'sync' | 'publish'

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(220)
        self._action_kind = "fetch"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(10)

        self.btn = QPushButton(self)
        self.btn.setFixedHeight(34)
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._on_button_clicked)
        self.sync_btn = self.btn
        self.fetch_btn = self.btn

        btn_layout = QVBoxLayout(self.btn)
        btn_layout.setContentsMargins(10, 2, 10, 2)
        btn_layout.setSpacing(0)

        self.title_label = QLabel(self.tr("Fetch origin"), self.btn)
        self.title_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        self.btn.text = lambda: self.title_label.text()  # type: ignore[method-assign]
        btn_layout.addWidget(self.title_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.subtitle_label = QLabel(self.tr("Check for remote changes"), self.btn)
        self.subtitle_label.setStyleSheet("font-size: 10px;")
        btn_layout.addWidget(self.subtitle_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self.btn)
        self._refresh_styles()

    def set_sync_status(self, status: BranchSyncStatus) -> None:
        if status.is_detached:
            self._action_kind = "detached"
            self.title_label.setText(self.tr("Detached HEAD"))
            self.subtitle_label.setText(self.tr("Checkout branch to sync"))
            self.btn.setEnabled(False)
            self.btn.setIcon(get_icon("warning", size=16))
        elif status.upstream_name is None:
            self._action_kind = "publish"
            self.title_label.setText(self.tr("Publish branch"))
            self.subtitle_label.setText(self.tr("Push branch to origin"))
            self.btn.setEnabled(True)
            self.btn.setIcon(get_icon("cloud", size=16))
        elif status.ahead > 0 and status.behind > 0:
            self._action_kind = "sync"
            self.title_label.setText(self.tr(f"Sync branch ({status.ahead}↑ {status.behind}↓)"))
            self.subtitle_label.setText(self.tr("Pull & push remote changes"))
            self.btn.setEnabled(True)
            self.btn.setIcon(get_icon("merge", size=16))
        elif status.behind > 0:
            self._action_kind = "pull"
            self.title_label.setText(self.tr(f"Pull origin ({status.behind}↓)"))
            self.subtitle_label.setText(self.tr(f"{status.behind} commit(s) on origin"))
            self.btn.setEnabled(True)
            self.btn.setIcon(get_icon("pull", size=16))
        elif status.ahead > 0:
            self._action_kind = "push"
            self.title_label.setText(self.tr(f"Push origin ({status.ahead}↑)"))
            self.subtitle_label.setText(self.tr(f"{status.ahead} commit(s) ready"))
            self.btn.setEnabled(True)
            self.btn.setIcon(get_icon("push", size=16))
        else:
            self._action_kind = "fetch"
            self.title_label.setText(self.tr("Fetch origin"))
            self.subtitle_label.setText(self.tr("Last fetched just now"))
            self.btn.setEnabled(True)
            self.btn.setIcon(get_icon("fetch", size=16))

    @Slot()
    def _on_button_clicked(self) -> None:
        self.sync_requested.emit(self._action_kind)

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        border_col = CONTEXT_BAR_BORDER_DARK if is_dark else CONTEXT_BAR_BORDER_LIGHT
        bg_col = CONTEXT_BTN_BG_DARK if is_dark else CONTEXT_BTN_BG_LIGHT
        self.btn.setStyleSheet(
            f"QPushButton {{ background-color: {bg_col}; border: 1px solid {border_col}; "
            f"border-radius: 6px; }} QPushButton:hover {{ background-color: palette(button); }}"
        )


class QuickActionsStrip(QWidget):
    """Cell 4: Right-aligned quick action buttons."""

    undo_clicked = Signal()
    pull_clicked = Signal()
    push_clicked = Signal()
    stash_clicked = Signal()
    pop_clicked = Signal()
    terminal_toggled = Signal()
    palette_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 12, 4)
        layout.setSpacing(6)

        def _make_btn(icon_name: str, tooltip: str, slot: Callable[[], None]) -> QToolButton:
            btn = QToolButton(self)
            btn.setIcon(get_icon(icon_name, size=16))
            btn.setToolTip(tooltip)
            btn.setFixedSize(32, 32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
            return btn

        self.btn_undo = _make_btn(
            "undo", self.tr("Undo last action (Ctrl+Z)"), self.undo_clicked.emit
        )
        self.btn_pull = _make_btn(
            "pull", self.tr("Pull from upstream (Ctrl+Shift+L)"), self.pull_clicked.emit
        )
        self.btn_push = _make_btn(
            "push", self.tr("Push to upstream (Ctrl+Shift+U)"), self.push_clicked.emit
        )
        self.btn_stash = _make_btn(
            "stash", self.tr("Stash all changes (Ctrl+Shift+S)"), self.stash_clicked.emit
        )
        self.btn_pop = _make_btn("pop", self.tr("Pop latest stash"), self.pop_clicked.emit)
        self.btn_terminal = _make_btn(
            "terminal", self.tr("Toggle Git Terminal (` / Ctrl+`)"), self.terminal_toggled.emit
        )
        self.btn_palette = _make_btn(
            "search", self.tr("Command Palette (Ctrl+K)"), self.palette_clicked.emit
        )

        self.undo_btn = self.btn_undo
        self.terminal_btn = self.btn_terminal

        self._refresh_styles()

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        border_col = CONTEXT_BAR_BORDER_DARK if is_dark else CONTEXT_BAR_BORDER_LIGHT
        bg_col = CONTEXT_BTN_BG_DARK if is_dark else CONTEXT_BTN_BG_LIGHT
        for btn in (
            self.btn_undo,
            self.btn_pull,
            self.btn_push,
            self.btn_stash,
            self.btn_pop,
            self.btn_terminal,
            self.btn_palette,
        ):
            btn.setStyleSheet(
                f"QToolButton {{ background-color: {bg_col}; border: 1px solid {border_col}; "
                f"border-radius: 6px; padding: 2px; }} "
                f"QToolButton:hover {{ background-color: palette(button); border-color: palette(highlight); }}"
            )


class ContextHeaderBar(QFrame):
    """Segmented 4-Cell Top Context Header Bar (FR-11.9)."""

    repo_selector_clicked = Signal()
    branch_selector_clicked = Signal()
    sync_requested = Signal(str)
    fetch_requested = Signal()
    sync_clicked = Signal()
    fetch_clicked = Signal()
    undo_clicked = Signal()
    undo_requested = Signal()
    pull_requested = Signal()
    push_requested = Signal()
    stash_requested = Signal()
    pop_requested = Signal()
    terminal_toggled = Signal()
    terminal_clicked = Signal()
    command_palette_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(48)
        self.setObjectName("ContextHeaderBar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Cell 1: Repo
        self.cell_repo = RepoContextCell(self)
        self.cell_repo.clicked.connect(self.repo_selector_clicked.emit)
        layout.addWidget(self.cell_repo)

        # Divider 1
        layout.addWidget(self._create_divider())

        # Cell 2: Branch
        self.cell_branch = BranchContextCell(self)
        self.cell_branch.clicked.connect(self.branch_selector_clicked.emit)
        layout.addWidget(self.cell_branch)

        # Divider 2
        layout.addWidget(self._create_divider())

        # Cell 3: Sync
        self.cell_sync = SyncActionCell(self)
        self.cell_sync.sync_requested.connect(self._on_sync_action)
        layout.addWidget(self.cell_sync)

        layout.addStretch(1)

        # Cell 4: Quick Actions
        self.cell_actions = QuickActionsStrip(self)
        self.cell_actions.undo_clicked.connect(self.undo_requested.emit)
        self.cell_actions.undo_clicked.connect(self.undo_clicked.emit)
        self.cell_actions.pull_clicked.connect(self.pull_requested.emit)
        self.cell_actions.push_clicked.connect(self.push_requested.emit)
        self.cell_actions.stash_clicked.connect(self.stash_requested.emit)
        self.cell_actions.pop_clicked.connect(self.pop_requested.emit)
        self.cell_actions.terminal_toggled.connect(self.terminal_toggled.emit)
        self.cell_actions.terminal_toggled.connect(self.terminal_clicked.emit)
        self.cell_actions.palette_clicked.connect(self.command_palette_requested.emit)
        layout.addWidget(self.cell_actions)

        self._refresh_styles()

    def _on_sync_action(self, kind: str) -> None:
        self.sync_requested.emit(kind)
        if kind == "fetch":
            self.fetch_requested.emit()
            self.fetch_clicked.emit()
        else:
            self.sync_clicked.emit()

    def _create_divider(self) -> QFrame:
        div = QFrame(self)
        div.setFrameShape(QFrame.Shape.VLine)
        div.setFrameShadow(QFrame.Shadow.Plain)
        div.setFixedWidth(1)
        return div

    @property
    def repo_cell(self) -> RepoContextCell:
        return self.cell_repo

    @property
    def branch_cell(self) -> BranchContextCell:
        return self.cell_branch

    @property
    def sync_cell(self) -> SyncActionCell:
        return self.cell_sync

    @property
    def quick_actions(self) -> QuickActionsStrip:
        return self.cell_actions

    def set_repo_info(self, name: str | None, path: str | None = None) -> None:
        self.update_repo(name)

    def set_branch_sync_status(self, status: BranchSyncStatus) -> None:
        self.update_sync_status(status)

    def update_repo(
        self,
        repo: Any = None,
        branch_name: str | None = None,
        is_detached: bool = False,
    ) -> None:
        if repo is None:
            self.cell_repo.set_repo_name(None)
            return
        if hasattr(repo, "name"):
            name = repo.name
        elif hasattr(repo, "path"):
            name = Path(repo.path).name
        elif isinstance(repo, (str, Path)):
            name = Path(repo).name
        else:
            name = str(repo)
        self.cell_repo.set_repo_name(name)
        if branch_name is not None:
            self.cell_branch.set_branch_sync(
                BranchSyncStatus(
                    branch_name=branch_name,
                    upstream_name=None,
                    ahead=0,
                    behind=0,
                    is_detached=is_detached,
                )
            )

    def update_sync_status(
        self,
        status_or_ahead: BranchSyncStatus | int = 0,
        behind: int = 0,
        fetching: bool = False,
    ) -> None:
        if isinstance(status_or_ahead, BranchSyncStatus):
            self.cell_branch.set_branch_sync(status_or_ahead)
            self.cell_sync.set_sync_status(status_or_ahead)
        else:
            status = BranchSyncStatus(
                branch_name=self.cell_branch.branch_btn.text() or "main",
                upstream_name=None,
                ahead=int(status_or_ahead),
                behind=behind,
                is_detached=False,
            )
            self.cell_sync.set_sync_status(status)

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        bg = CONTEXT_BAR_BG_DARK if is_dark else CONTEXT_BAR_BG_LIGHT
        border = CONTEXT_BAR_BORDER_DARK if is_dark else CONTEXT_BAR_BORDER_LIGHT
        self.setStyleSheet(
            f"#ContextHeaderBar {{ background-color: {bg}; border-top: 1px solid {border}; "
            f"border-bottom: 1px solid {border}; }}"
        )
        self.cell_repo._refresh_styles()
        self.cell_branch._refresh_styles()
        self.cell_sync._refresh_styles()
        self.cell_actions._refresh_styles()


class GitTerminalDrawer(QFrame):
    """Collapsible 180px bottom panel showing executed git CLI logs and quick input."""

    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(180)
        self.setObjectName("GitTerminalDrawer")
        self.closed.connect(lambda: self.setVisible(False))
        self._command_runner: Callable[[list[str]], tuple[int, str, str, float]] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(6)

        # Header toolbar
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.title_lbl = QLabel(self.tr("Git Terminal & Command Log"), self)
        self.title_lbl.setStyleSheet("font-size: 11px; font-weight: bold;")
        header.addWidget(self.title_lbl)
        header.addStretch(1)

        self.clear_btn = QToolButton(self)
        self.clear_btn.setText(self.tr("Clear"))
        self.clear_btn.setToolTip(self.tr("Clear log output"))
        self.clear_btn.clicked.connect(self.clear_log)
        header.addWidget(self.clear_btn)

        self.close_btn = QToolButton(self)
        self.close_btn.setIcon(get_icon("close", size=14))
        self.close_btn.setToolTip(self.tr("Close terminal drawer"))
        self.close_btn.clicked.connect(self.closed.emit)
        header.addWidget(self.close_btn)

        layout.addLayout(header)

        # Read-only output log
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(self.log_view, 1)

        # Quick command input line
        input_box = QHBoxLayout()
        input_box.setContentsMargins(0, 0, 0, 0)
        input_box.setSpacing(6)

        self.prompt_lbl = QLabel("$ git", self)
        self.prompt_lbl.setStyleSheet("font-family: monospace; font-weight: bold; font-size: 12px;")
        input_box.addWidget(self.prompt_lbl)

        self.cmd_input = QLineEdit(self)
        self.cmd_input.setPlaceholderText(
            self.tr("status, diff, branch, log, fetch… (Enter to run)")
        )
        self.cmd_input.returnPressed.connect(self._on_execute_command)
        input_box.addWidget(self.cmd_input, 1)

        layout.addLayout(input_box)
        self._refresh_styles()

    @property
    def is_expanded(self) -> bool:
        return self.isVisible()

    def toggle(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self.cmd_input.setFocus()

    def toggle_drawer(self) -> None:
        self.toggle()

    def set_command_runner(
        self, runner: Callable[[list[str]], tuple[int, str, str, float]] | None
    ) -> None:
        self._command_runner = runner

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)
        sb = self.log_view.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    @Slot()
    def clear_log(self) -> None:
        self.log_view.clear()

    @Slot()
    def _on_execute_command(self) -> None:
        raw_cmd = self.cmd_input.text().strip()
        if not raw_cmd:
            return
        self.cmd_input.clear()

        # Parse args using shlex
        try:
            tokens = shlex.split(raw_cmd)
        except ValueError as exc:
            self.append_log(f"[error] Failed to parse command: {exc}")
            return

        # Strip accidental leading 'git'
        if tokens and tokens[0] == "git":
            tokens = tokens[1:]

        if not tokens:
            return

        ts = datetime.now().strftime("%H:%M:%S")
        self.append_log(f"[{ts}] $ git {' '.join(tokens)}")

        if self._command_runner:
            returncode, stdout, stderr, duration_ms = self._command_runner(tokens)
            if stdout:
                self.append_log(stdout.rstrip())
            if stderr:
                self.append_log(f"[stderr] {stderr.rstrip()}")
            status_text = "succeeded" if returncode == 0 else f"failed (code {returncode})"
            self.append_log(f"[{ts}] -> {status_text} in {duration_ms:.1f}ms\n")
        else:
            self.append_log("[error] No active Git command runner available.\n")

    def _refresh_styles(self) -> None:
        is_dark = is_dark_theme(self)
        bg = CONTEXT_BAR_BG_DARK if is_dark else CONTEXT_BAR_BG_LIGHT
        border = CONTEXT_BAR_BORDER_DARK if is_dark else CONTEXT_BAR_BORDER_LIGHT
        self.setStyleSheet(
            f"#GitTerminalDrawer {{ background-color: {bg}; border-top: 1px solid {border}; }}"
        )
