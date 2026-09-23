"""Catppuccin Velvet Pastel status badges and CI icons for forge tabs."""

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel

from wrench.forge.models import CIStatus
from wrench.ui.theme import is_dark_theme

# Catppuccin Velvet Pastel palettes for forge state pills
FORGE_BADGE_COLORS = {
    "light": {
        "open": ("#2a5c20", "#dcfce7"),  # Dark green text on pastel green pill
        "merged": ("#582d8c", "#f3e8ff"),  # Dark purple text on pastel purple pill
        "closed": ("#8c1d28", "#fee2e2"),  # Dark red text on pastel red pill
        "mirror": ("#1e40af", "#dbeafe"),  # Deep blue on pastel blue
    },
    "dark": {
        "open": ("#a6e3a1", "#1e3827"),  # Mint on dark forest green
        "merged": ("#cba6f7", "#322046"),  # Mauve on dark purple
        "closed": ("#f38ba8", "#3e1e28"),  # Flamingo on dark red
        "mirror": ("#89b4fa", "#1e2942"),  # Sky on dark slate
    },
}

CI_STATUS_CONFIG = {
    "success": ("✔", "#40a02b", "#a6e3a1", "CI: Success — all checks passed"),
    "failure": ("✖", "#d20f39", "#f38ba8", "CI: Failure — checks failed"),
    "pending": ("●", "#1e66f5", "#89b4fa", "CI: Pending — checks in progress"),
    "unknown": ("○", "#7c7f93", "#9399b2", "CI: No checks reported / unknown"),
}


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
        fg = "#89b4fa" if is_dark else "#1e40af"
        bg = "#1e2942" if is_dark else "#dbeafe"

        self.setText(f"{remote_name} · {provider.capitalize()}")
        self.setStyleSheet(
            f"QLabel {{ color: {fg}; background-color: {bg}; border-radius: 4px; "
            f"padding: 2px 8px; font-size: 11px; font-weight: 500; }}"
        )
