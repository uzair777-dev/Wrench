"""Edge-to-Edge ChangesView and ZeroChangesLaunchpadWidget (FR-11.10, ui-planning.md §6.29.4).

Provides:
- ZeroChangesLaunchpadWidget: A polished empty state widget with 4 action cards
  for remote sync, terminal access, file manager browsing, and commit history navigation.
- Re-exports ChangesTab as ChangesView for unified imports.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from wrench.ui import icons
from wrench.ui.quotes import CLEAN_STATE_QUOTES, random_quote
from wrench.ui.theme import (
    DEFAULT_ICON_COLOR,
    DIFF_ADD_BAR,
    LAUNCHPAD_CARD_BG_DARK,
    LAUNCHPAD_CARD_BG_LIGHT,
    LAUNCHPAD_CARD_BORDER_DARK,
    LAUNCHPAD_CARD_BORDER_LIGHT,
    LAUNCHPAD_KBD_BG_DARK,
    LAUNCHPAD_KBD_BG_LIGHT,
    LAUNCHPAD_KBD_TEXT_DARK,
    LAUNCHPAD_KBD_TEXT_LIGHT,
    LAUNCHPAD_SUBTITLE_DARK,
    LAUNCHPAD_SUBTITLE_LIGHT,
    LAUNCHPAD_TITLE_DARK,
    LAUNCHPAD_TITLE_LIGHT,
    SECONDARY_TEXT,
    get_secondary_button_style,
    is_dark_theme,
)

logger = logging.getLogger(__name__)


def __getattr__(name: str) -> Any:
    if name in ("ChangesTab", "ChangesView"):
        from wrench.ui.tabs.changes_tab import ChangesTab

        return ChangesTab
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


class _LaunchpadActionCard(QFrame):
    """Bordered action card with SVG icon, descriptive text, and action button."""

    action_clicked = Signal()

    def __init__(
        self,
        icon_name: str,
        title: str,
        subtitle: str,
        button_text: str,
        shortcut_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._title_text = title
        self._subtitle_text = subtitle
        self._button_text = button_text
        self._shortcut_text = shortcut_text

        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)

        # Icon
        self._icon_lbl = QLabel(self)
        self._icon_lbl.setFixedSize(32, 32)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_lbl)

        # Text column
        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)

        self._title_lbl = QLabel(title, self)
        self._title_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        text_col.addWidget(self._title_lbl)

        self._sub_lbl = QLabel(subtitle, self)
        self._sub_lbl.setStyleSheet("font-size: 11px;")
        self._sub_lbl.setWordWrap(True)
        text_col.addWidget(self._sub_lbl)

        if shortcut_text:
            self._shortcut_lbl = QLabel(shortcut_text, self)
            self._shortcut_lbl.setStyleSheet("font-size: 10px; font-family: monospace;")
            text_col.addWidget(self._shortcut_lbl)
        else:
            self._shortcut_lbl = None

        layout.addLayout(text_col, 1)

        # Action Button
        self.btn = QPushButton(button_text, self)
        self.btn.setFixedHeight(30)
        self.btn.clicked.connect(self.action_clicked.emit)
        layout.addWidget(self.btn)

        self._apply_theme()

    def mousePressEvent(self, event: Any) -> None:
        self.action_clicked.emit()
        if event is not None:
            super().mousePressEvent(event)

    def set_content(self, title: str, subtitle: str, button_text: str) -> None:
        self._title_text = title
        self._subtitle_text = subtitle
        self._button_text = button_text
        self._title_lbl.setText(title)
        self._sub_lbl.setText(subtitle)
        self.btn.setText(button_text)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if getattr(self, "_applying_theme", False):
            return
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ThemeChange,
        ):
            self._apply_theme()

    def _apply_theme(self) -> None:
        if getattr(self, "_applying_theme", False):
            return
        self._applying_theme = True
        try:
            dark = is_dark_theme(self)
            card_bg = LAUNCHPAD_CARD_BG_DARK if dark else LAUNCHPAD_CARD_BG_LIGHT
            card_border = LAUNCHPAD_CARD_BORDER_DARK if dark else LAUNCHPAD_CARD_BORDER_LIGHT
            title_color = LAUNCHPAD_TITLE_DARK if dark else LAUNCHPAD_TITLE_LIGHT
            sub_color = LAUNCHPAD_SUBTITLE_DARK if dark else LAUNCHPAD_SUBTITLE_LIGHT
            icon_color = DEFAULT_ICON_COLOR if dark else title_color

            self.setStyleSheet(
                f"QFrame {{ background-color: {card_bg}; border: 1px solid {card_border}; "
                f"border-radius: 8px; }}"
            )
            self._title_lbl.setStyleSheet(
                f"font-size: 13px; font-weight: bold; color: {title_color}; background: transparent; border: none;"
            )
            self._sub_lbl.setStyleSheet(
                f"font-size: 11px; color: {sub_color}; background: transparent; border: none;"
            )
            if self._shortcut_lbl:
                kbd_bg = LAUNCHPAD_KBD_BG_DARK if dark else LAUNCHPAD_KBD_BG_LIGHT
                kbd_fg = LAUNCHPAD_KBD_TEXT_DARK if dark else LAUNCHPAD_KBD_TEXT_LIGHT
                self._shortcut_lbl.setStyleSheet(
                    f"font-size: 10px; font-family: monospace; color: {kbd_fg}; "
                    f"background-color: {kbd_bg}; padding: 2px 6px; border-radius: 4px; border: none;"
                )

            self._icon_lbl.setPixmap(icons.get_pixmap(self._icon_name, color=icon_color, size=24))
            self._icon_lbl.setStyleSheet("background: transparent; border: none;")

            btn_style = get_secondary_button_style(dark)
            self.btn.setStyleSheet(btn_style)
        finally:
            self._applying_theme = False


class ZeroChangesLaunchpadWidget(QWidget):
    """Clean working tree launchpad shown in ChangesView when total_changes == 0."""

    sync_clicked = Signal()
    terminal_clicked = Signal()
    file_manager_clicked = Signal()
    history_clicked = Signal()

    new_branch_clicked = file_manager_clicked
    view_history_clicked = history_clicked
    open_terminal_clicked = terminal_clicked
    refresh_clicked = sync_clicked

    @property
    def cards(self) -> list[_LaunchpadActionCard]:
        return [self.sync_card, self.terminal_card, self.file_manager_card, self.history_card]

    @property
    def quote_lbl(self) -> QLabel:
        return self._quote_lbl

    command_palette_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 24, 20, 24)
        outer_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget(scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Header with large check icon
        self._header_icon = QLabel(content)
        self._header_icon.setFixedSize(48, 48)
        self._header_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._header_icon, 0, Qt.AlignmentFlag.AlignCenter)

        self._title_lbl = QLabel(self.tr("No local changes"), content)
        self._title_lbl.setStyleSheet("font-size: 20px; font-weight: bold;")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_lbl)

        self._subtitle_lbl = QLabel(
            self.tr(
                "There are no uncommitted changes in this repository. "
                "Here are some friendly suggestions for what to do next:"
            ),
            content,
        )
        self._subtitle_lbl.setStyleSheet("font-size: 12px;")
        self._subtitle_lbl.setWordWrap(True)
        self._subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_lbl.setMaximumWidth(520)
        layout.addWidget(self._subtitle_lbl)

        # 2. Four Action Cards
        cards_container = QWidget(content)
        cards_container.setMaximumWidth(540)
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 8, 0, 8)
        cards_layout.setSpacing(10)

        # Card 1: Remote Sync
        self.sync_card = _LaunchpadActionCard(
            "cloud",
            self.tr("Remote Synchronization"),
            self.tr("Check for remote changes or synchronize branch commits with remote"),
            self.tr("Fetch origin"),
            shortcut_text="Ctrl+Shift+T",
            parent=cards_container,
        )
        self.sync_card.action_clicked.connect(self.sync_clicked.emit)
        cards_layout.addWidget(self.sync_card)

        # Card 2: Terminal / External Editor
        self.terminal_card = _LaunchpadActionCard(
            "terminal",
            self.tr("Open Embedded Terminal"),
            self.tr("Run git CLI commands directly inside the embedded drawer"),
            self.tr("Open Terminal"),
            shortcut_text="Ctrl+`",
            parent=cards_container,
        )
        self.terminal_card.action_clicked.connect(self.terminal_clicked.emit)
        cards_layout.addWidget(self.terminal_card)

        # Card 3: File Manager
        self.file_manager_card = _LaunchpadActionCard(
            "folder",
            self.tr("Show in File Manager"),
            self.tr("Browse repository root and working tree files in desktop file manager"),
            self.tr("Show in Files"),
            shortcut_text="Ctrl+Shift+O",
            parent=cards_container,
        )
        self.file_manager_card.action_clicked.connect(self.file_manager_clicked.emit)
        cards_layout.addWidget(self.file_manager_card)

        # Card 4: History / Command Palette
        self.history_card = _LaunchpadActionCard(
            "branch",
            self.tr("Commit Graph & History"),
            self.tr("Inspect the full multi-branch commit graph and topological history"),
            self.tr("View History"),
            shortcut_text="Ctrl+2",
            parent=cards_container,
        )
        self.history_card.action_clicked.connect(self.history_clicked.emit)
        cards_layout.addWidget(self.history_card)

        layout.addWidget(cards_container, 0, Qt.AlignmentFlag.AlignCenter)

        # 3. Rotating Quote Footer
        self._quote_lbl = QLabel(content)
        self._quote_lbl.setStyleSheet("font-size: 11px; font-style: italic;")
        self._quote_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._quote_lbl.setWordWrap(True)
        self._quote_lbl.setMaximumWidth(480)
        layout.addWidget(self._quote_lbl)

        self._quote_author_lbl = QLabel(content)
        self._quote_author_lbl.setStyleSheet("font-size: 10px; font-weight: bold;")
        self._quote_author_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._quote_author_lbl)

        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        self.refresh_quote()
        self._apply_theme()

    def update_sync_status(self, ahead: int, behind: int, upstream: str | None = None) -> None:
        """Dynamically updates the remote sync action card based on branch sync state."""
        if behind > 0 and ahead == 0:
            self.sync_card.set_content(
                self.tr("Incoming Commits Waiting"),
                self.tr(f"{behind} commit(s) waiting on remote tracking branch."),
                self.tr(f"Pull ({behind}↓)"),
            )
        elif ahead > 0 and behind == 0:
            self.sync_card.set_content(
                self.tr("Local Commits Ready"),
                self.tr(f"{ahead} local commit(s) ready to push to remote."),
                self.tr(f"Push ({ahead}↑)"),
            )
        elif ahead > 0 and behind > 0:
            self.sync_card.set_content(
                self.tr("Branch Diverged"),
                self.tr(f"Local has diverged: {ahead} ahead, {behind} behind."),
                self.tr(f"Sync ({ahead}↑ {behind}↓)"),
            )
        else:
            self.sync_card.set_content(
                self.tr("Remote Synchronization"),
                self.tr("All commits up to date with remote tracking branch."),
                self.tr("Fetch origin"),
            )

    def refresh_quote(self) -> None:
        """Picks a random quote for the footer."""
        try:
            quote, author = random_quote(CLEAN_STATE_QUOTES)
            self._quote_lbl.setText(f'"{quote}"')
            self._quote_author_lbl.setText(f"— {author}")
        except Exception as exc:
            logger.debug("Failed picking random quote: %s", exc)
            self._quote_lbl.setText('"Talk is cheap. Show me the code."')
            self._quote_author_lbl.setText("— Linus Torvalds")

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if getattr(self, "_applying_theme", False):
            return
        if event.type() in (
            QEvent.Type.PaletteChange,
            QEvent.Type.ThemeChange,
        ):
            self._apply_theme()

    def _apply_theme(self) -> None:
        if getattr(self, "_applying_theme", False):
            return
        self._applying_theme = True
        try:
            dark = is_dark_theme(self)
            title_color = LAUNCHPAD_TITLE_DARK if dark else LAUNCHPAD_TITLE_LIGHT
            sub_color = LAUNCHPAD_SUBTITLE_DARK if dark else LAUNCHPAD_SUBTITLE_LIGHT
            quote_color = SECONDARY_TEXT["dark" if dark else "light"]

            self._title_lbl.setStyleSheet(
                f"font-size: 20px; font-weight: bold; color: {title_color};"
            )
            self._subtitle_lbl.setStyleSheet(f"font-size: 12px; color: {sub_color};")
            self._quote_lbl.setStyleSheet(
                f"font-size: 11px; font-style: italic; color: {quote_color};"
            )
            self._quote_author_lbl.setStyleSheet(
                f"font-size: 10px; font-weight: bold; color: {quote_color};"
            )

            check_color = DIFF_ADD_BAR
            self._header_icon.setPixmap(icons.get_pixmap("check", color=check_color, size=40))
        finally:
            self._applying_theme = False
