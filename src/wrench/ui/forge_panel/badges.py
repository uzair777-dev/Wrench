"""Catppuccin Velvet Pastel status badges and CI icons for forge tabs."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel

from wrench.forge.models import CIStatus
from wrench.ui.theme import (
    CI_STATUS_CONFIG,
    FORGE_BADGE_COLORS,
    get_remote_badge_colors,
    is_dark_theme,
)


def paint_pr_state_badge(painter: QPainter, rect: QRect, state: str, is_dark: bool) -> None:
    """Efficient cell painting helper for QStyledItemDelegate with 0 QWidget allocations."""
    norm_state = state.lower()
    palette = FORGE_BADGE_COLORS["dark" if is_dark else "light"]
    fg_hex, bg_hex = palette.get(norm_state, palette["open"])

    badge_width = min(rect.width() - 8, 70)
    badge_height = min(rect.height() - 6, 22)
    x = rect.x() + (rect.width() - badge_width) // 2
    y = rect.y() + (rect.height() - badge_height) // 2
    badge_rect = QRect(x, y, badge_width, badge_height)

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)

    # Background pill
    painter.setBrush(QColor(bg_hex))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(badge_rect, 10, 10)

    # Text
    painter.setPen(QPen(QColor(fg_hex)))
    font = painter.font()
    font.setPointSize(9)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(badge_rect, Qt.AlignCenter, state.capitalize())

    painter.restore()


def paint_issue_state_badge(painter: QPainter, rect: QRect, state: str, is_dark: bool) -> None:
    """Cell painting helper for Issue state badges with 0 QWidget allocations."""
    paint_pr_state_badge(painter, rect, state, is_dark)


class PRStateBadge(QLabel):
    """Pill badge indicating Pull Request state."""

    def __init__(self, state: str = "open", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        norm = state.lower()
        is_dark = is_dark_theme(self.palette())
        palette = FORGE_BADGE_COLORS["dark" if is_dark else "light"]
        fg, bg = palette.get(norm, palette["open"])

        self.setText(state.capitalize())
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 10px; "
            f"padding: 2px 10px; font-weight: bold; font-size: 11px; }}"
        )


class IssueStateBadge(QLabel):
    """Pill badge indicating Issue state."""

    def __init__(self, state: str = "open", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_state(state)

    def set_state(self, state: str) -> None:
        norm = state.lower()
        is_dark = is_dark_theme(self.palette())
        palette = FORGE_BADGE_COLORS["dark" if is_dark else "light"]
        fg, bg = palette.get("open" if norm == "open" else "closed", palette["open"])

        self.setText(state.capitalize())
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 10px; "
            f"padding: 2px 10px; font-weight: bold; font-size: 11px; }}"
        )


class CIIconWidget(QLabel):
    """Compact accessible status indicator for CI runs."""

    def __init__(self, ci_status: CIStatus | None = None, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_status(ci_status)

    def set_status(self, ci_status: CIStatus | None) -> None:
        state = ci_status.state if ci_status else "unknown"
        icon, light_col, dark_col, default_desc = CI_STATUS_CONFIG.get(
            state, CI_STATUS_CONFIG["unknown"]
        )

        is_dark = is_dark_theme(self.palette())
        color = dark_col if is_dark else light_col

        self.setText(icon)
        desc = ci_status.description if ci_status and ci_status.description else default_desc
        self.setToolTip(desc)
        self.setStyleSheet(
            f"QLabel {{ color: {color}; font-size: 14px; font-weight: bold; padding: 2px; }}"
        )


class RemoteBadge(QLabel):
    """Subtle badge displaying the originating remote and provider."""

    def __init__(self, remote_name: str, provider: str, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.update_remote(remote_name, provider)

    def update_remote(self, remote_name: str, provider: str) -> None:
        is_dark = is_dark_theme(self.palette())
        fg, bg = get_remote_badge_colors(is_dark)

        self.setText(f"{remote_name} · {provider.capitalize()}")
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 11px; font-weight: 500; }}"
        )
