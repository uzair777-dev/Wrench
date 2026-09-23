"""Theme definitions and color management for Wrench.

Implements the Catppuccin Velvet Pastel design system:
- Light Mode: Catppuccin Latte Pastel
- Dark Mode: Catppuccin Mocha Velvet Pastel
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# --- Theme Detection ---


def is_dark_theme(widget_or_palette: QWidget | QPalette | None = None) -> bool:
    """Detects whether the active application/window theme is dark.

    Uses palette luminance calculation — the only reliable method when the
    app uses custom palettes (colorScheme() returns the *desktop* scheme,
    not the app's custom palette, which produces wrong results on KDE/GNOME).
    """
    if isinstance(widget_or_palette, QPalette):
        pal = widget_or_palette
    elif widget_or_palette is not None:
        pal = widget_or_palette.palette()
    else:
        pal = QApplication.palette()
    win_color = pal.color(QPalette.Window)
    base_color = pal.color(QPalette.Base)
    avg_lightness = (win_color.lightnessF() + base_color.lightnessF()) / 2.0
    return avg_lightness < 0.5


# --- Secondary / Accent Colors (Catppuccin Velvet Pastel) ---

SECONDARY_TEXT = {
    "light": "#7c7f93",  # Subtext0 — muted slate for secondary labels
    "dark": "#9399b2",  # Overlay2 — soft lavender-gray for secondary labels
}

ACCENT_COLORS = {
    "light": {
        "warning": "#df8e1d",  # Catppuccin Yellow (Latte)
        "detached": "#df8e1d",  # Detached HEAD indicator
    },
    "dark": {
        "warning": "#f9e2af",  # Catppuccin Yellow (Mocha)
        "detached": "#f9e2af",  # Detached HEAD indicator
    },
}


# --- Pastel Palettes ---


def create_pastel_light_palette() -> QPalette:
    """Creates the Catppuccin Latte Pastel palette."""
    pal = QPalette()
    # Base backgrounds
    pal.setColor(QPalette.Window, QColor("#eff1f5"))  # Warm pastel mist
    pal.setColor(QPalette.WindowText, QColor("#4c4f69"))  # Soft charcoal slate
    pal.setColor(QPalette.Base, QColor("#ffffff"))  # Card / editor base
    pal.setColor(QPalette.AlternateBase, QColor("#e6e9ef"))  # Subtle row tint
    pal.setColor(QPalette.ToolTipBase, QColor("#eff1f5"))
    pal.setColor(QPalette.ToolTipText, QColor("#4c4f69"))
    pal.setColor(QPalette.Text, QColor("#4c4f69"))
    pal.setColor(QPalette.Button, QColor("#e6e9ef"))
    pal.setColor(QPalette.ButtonText, QColor("#4c4f69"))
    pal.setColor(QPalette.BrightText, QColor("#d20f39"))
    pal.setColor(QPalette.Link, QColor("#1e66f5"))  # Sapphire
    pal.setColor(QPalette.Highlight, QColor("#1e66f5"))  # Sapphire blue
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor("#9ca0b0"))
    return pal


def create_pastel_dark_palette() -> QPalette:
    """Creates the Catppuccin Mocha Velvet Pastel palette."""
    pal = QPalette()
    # Base backgrounds - deeper, darker tones for enhanced contrast
    pal.setColor(QPalette.Window, QColor("#181825"))  # Midnight slate canvas (Mantle)
    pal.setColor(QPalette.WindowText, QColor("#cdd6f4"))  # Frosted soft white
    pal.setColor(QPalette.Base, QColor("#11111b"))  # Deep crust base (Crust)
    pal.setColor(QPalette.AlternateBase, QColor("#1e1e2e"))  # Surface row tint
    pal.setColor(QPalette.ToolTipBase, QColor("#181825"))
    pal.setColor(QPalette.ToolTipText, QColor("#cdd6f4"))
    pal.setColor(QPalette.Text, QColor("#cdd6f4"))
    pal.setColor(QPalette.Button, QColor("#252638"))
    pal.setColor(QPalette.ButtonText, QColor("#cdd6f4"))
    pal.setColor(QPalette.BrightText, QColor("#f38ba8"))
    pal.setColor(QPalette.Link, QColor("#89b4fa"))  # Pastel sky
    pal.setColor(QPalette.Highlight, QColor("#89b4fa"))  # Pastel sky blue
    pal.setColor(QPalette.HighlightedText, QColor("#11111b"))
    pal.setColor(QPalette.PlaceholderText, QColor("#6c7086"))
    return pal


def apply_theme(app: QApplication, mode: str) -> None:
    """Applies a theme mode ('auto', 'light', 'dark') to the application."""
    if mode == "light":
        palette = create_pastel_light_palette()
    elif mode == "dark":
        palette = create_pastel_dark_palette()
    else:  # 'auto' / system
        palette = app.style().standardPalette()

    app.setPalette(palette)
    for top_widget in QApplication.topLevelWidgets():
        top_widget.setPalette(palette)
        for child in top_widget.findChildren(QWidget):
            child.setPalette(palette)
    logger.info("Applied theme mode: %s", mode)


# --- Diff Styling Constants (Catppuccin Velvet Pastel) ---

DIFF_STYLES = {
    "light": {
        "container": (
            "QTextEdit { background-color: #ffffff; color: #4c4f69; "
            "border: 1px solid rgba(76, 79, 105, 0.18); border-radius: 4px; }"
        ),
        "add": (
            "color: #216e39; background-color: #dcefd8; "
            "border-left: 3px solid #40a02b; padding: 1px 6px;"
        ),
        "del": (
            "color: #a8233e; background-color: #fcd7db; "
            "border-left: 3px solid #d20f39; padding: 1px 6px;"
        ),
        "hunk": (
            "color: #1e66f5; font-weight: bold; background-color: #e6e9f8; "
            "border: 1px solid #ccd0da; padding: 2px 6px; margin-top: 6px; border-radius: 2px;"
        ),
        "ctx": "color: #4c4f69; padding: 1px 6px;",
    },
    "dark": {
        "container": (
            "QTextEdit { background-color: #11111b; color: #cdd6f4; "
            "border: 1px solid rgba(205, 214, 244, 0.15); border-radius: 4px; }"
        ),
        "add": (
            "color: #a6e3a1; background-color: #1e3527; "
            "border-left: 3px solid #a6e3a1; padding: 1px 6px;"
        ),
        "del": (
            "color: #f38ba8; background-color: #3b1d28; "
            "border-left: 3px solid #f38ba8; padding: 1px 6px;"
        ),
        "hunk": (
            "color: #89b4fa; font-weight: bold; background-color: #1e2640; "
            "border: 1px solid #313244; padding: 2px 6px; margin-top: 6px; border-radius: 2px;"
        ),
        "ctx": "color: #bac2de; padding: 1px 6px;",
    },
}

# --- Status Badges (Catppuccin Velvet Pastel) ---

BADGE_STYLES = {
    "light": {
        "M": ("#1e66f5", "#e0e7ff"),  # Modified: Sapphire on soft blue
        "A": ("#40a02b", "#dcfce7"),  # Added: Mint on soft green
        "D": ("#d20f39", "#fee2e2"),  # Deleted: Red on soft pink
        "R": ("#8839ef", "#f3e8ff"),  # Renamed: Mauve on soft purple
        "?": ("#7c7f93", "#e6e9ef"),  # Untracked: Slate on soft gray
        "⚠ C": ("#c2410c", "#ffedd5"),  # Conflict: Terracotta on soft amber
    },
    "dark": {
        "M": ("#89b4fa", "#1e2942"),  # Modified: Pastel sky on dark blue
        "A": ("#a6e3a1", "#1b3526"),  # Added: Pastel mint on dark green
        "D": ("#f38ba8", "#3b1c28"),  # Deleted: Pastel flamingo on dark red
        "R": ("#cba6f7", "#2c1e3d"),  # Renamed: Pastel mauve on dark purple
        "?": ("#9399b2", "#282a3a"),  # Untracked: Pastel slate on dark slate
        "⚠ C": ("#fab387", "#3d261e"),  # Conflict: Pastel peach on dark amber
    },
}


def get_badge_colors(change_type: str, is_dark: bool) -> tuple[str, str]:
    """Returns (foreground_color, background_color) for a status badge."""
    mode_key = "dark" if is_dark else "light"
    default_colors = ("#9399b2", "#282a3a") if is_dark else ("#7c7f93", "#e6e9ef")
    return BADGE_STYLES[mode_key].get(change_type, default_colors)


# --- Conflict Alert Banner Styling ---

CONFLICT_BANNER_STYLES = {
    "light": {
        "frame": (
            "background-color: #ffe8eb; border: 1px solid #d20f39; "
            "border-radius: 4px; padding: 4px;"
        ),
        "label": "color: #8c142c; font-weight: bold; font-size: 11px;",
    },
    "dark": {
        "frame": (
            "background-color: #341c26; border: 1px solid #f38ba8; "
            "border-radius: 4px; padding: 4px;"
        ),
        "label": "color: #f5c2e7; font-weight: bold; font-size: 11px;",
    },
}

# --- Commit Stats Colors ---

COMMIT_STAT_COLORS = {
    "light": {
        "add": "#216e39",  # Rich moss green
        "del": "#a8233e",  # Rich berry red
    },
    "dark": {
        "add": "#a6e3a1",  # Luminous mint
        "del": "#f38ba8",  # Luminous flamingo
    },
}
