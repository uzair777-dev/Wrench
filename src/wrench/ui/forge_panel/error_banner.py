"""Persistent inline error banner with tailored recovery actions for forge tabs."""

import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
)

from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.ui.theme import get_banner_style, is_dark_theme


class ForgeErrorBanner(QFrame):
    """Inline actionable banner displayed at the top of forge tabs."""

    action_requested = Signal(
        str
    )  # 'reenter_token' | 'edit_account' | 'retry' | 'network_settings'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVisible(False)
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_tick)
        self._retry_epoch: float = 0.0

        self._init_ui()

    def _init_ui(self) -> None:
        self.setFrameShape(QFrame.StyledPanel)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        self.icon_label = QLabel("⚠", self)
        self.icon_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(self.icon_label)

        self.message_label = QLabel(self)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.message_label, 1)

        self.action_btn = QPushButton(self)
        self.action_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; "
            "font-weight: bold; border-radius: 4px; }"
        )
        self.action_btn.clicked.connect(self._on_action_clicked)
        layout.addWidget(self.action_btn)

        self.close_btn = QToolButton(self)
        self.close_btn.setText("×")
        self.close_btn.setToolTip("Dismiss")
        self.close_btn.setStyleSheet(
            "QToolButton { border: none; font-size: 14px; font-weight: bold; }"
        )
        self.close_btn.clicked.connect(self.hide_banner)
        layout.addWidget(self.close_btn)

    def show_error(self, exc: Exception) -> None:
        is_dark = is_dark_theme(self.palette())
        self._countdown_timer.stop()

        if isinstance(exc, ForgeAuthenticationError):
            style = get_banner_style("error", is_dark)
            self.message_label.setText(str(exc))
            self.action_btn.setText("Re-enter Token…")
            self.action_btn.setProperty("action", "reenter_token")
            self.action_btn.setVisible(True)

        elif isinstance(exc, ForgeInsufficientScopeError):
            style = get_banner_style("warning", is_dark)
            msg = f"{exc} ({exc.scope_hint})" if exc.scope_hint else str(exc)
            self.message_label.setText(msg)
            self.action_btn.setText("Edit Account…")
            self.action_btn.setProperty("action", "edit_account")
            self.action_btn.setVisible(True)

        elif isinstance(exc, ForgeRateLimitedError):
            style = get_banner_style("warning", is_dark)
            self._retry_epoch = time.time() + exc.retry_after_seconds
            self._update_rate_limit_text()
            self._countdown_timer.start()
            self.action_btn.setVisible(False)

        elif isinstance(exc, ForgeUnreachableError):
            style = get_banner_style("info", is_dark)
            self.message_label.setText(str(exc))
            self.action_btn.setText("Network Settings…")
            self.action_btn.setProperty("action", "network_settings")
            self.action_btn.setVisible(True)

        else:
            style = get_banner_style("error", is_dark)
            self.message_label.setText(str(exc)[:300])
            self.action_btn.setText("Retry")
            self.action_btn.setProperty("action", "retry")
            self.action_btn.setVisible(True)

        bg, border, fg = style["bg"], style["border"], style["fg"]

        self.setStyleSheet(
            f"ForgeErrorBanner {{ background-color: {bg}; border: 1px solid {border}; "
            f"border-radius: 6px; }} QLabel {{ color: {fg}; }}"
        )
        self.setVisible(True)

    def _update_rate_limit_text(self) -> None:
        remaining = max(0, int(self._retry_epoch - time.time()))
        self.message_label.setText(f"API Rate limited by provider — retry in {remaining}s")
        if remaining <= 0:
            self._countdown_timer.stop()
            self.action_btn.setText("Retry Now")
            self.action_btn.setProperty("action", "retry")
            self.action_btn.setVisible(True)

    def _on_tick(self) -> None:
        self._update_rate_limit_text()

    def _on_action_clicked(self) -> None:
        act = self.action_btn.property("action")
        if act:
            self.action_requested.emit(str(act))

    def hide_banner(self) -> None:
        self._countdown_timer.stop()
        self.setVisible(False)
