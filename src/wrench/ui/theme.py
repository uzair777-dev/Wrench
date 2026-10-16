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
    elif widget_or_palette is not None and hasattr(widget_or_palette, "palette"):
        p = widget_or_palette.palette
        pal = p() if callable(p) else p
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


# --- Graph Lanes (Catppuccin Velvet Pastel 10-Lane DAG) ---

GRAPH_LANES = {
    "light": [
        "#1e66f5",  # 0: Sapphire
        "#e64553",  # 1: Maroon
        "#2d7d20",  # 2: Green
        "#d95700",  # 3: Peach
        "#8839ef",  # 4: Mauve
        "#179299",  # 5: Teal
        "#b2535d",  # 6: Flamingo
        "#157388",  # 7: Sapphire/Sky
        "#d20f39",  # 8: Red
        "#0375a3",  # 9: Sky
    ],
    "dark": [
        "#89b4fa",  # 0: Pastel Sky
        "#eba0ac",  # 1: Pastel Maroon
        "#a6e3a1",  # 2: Pastel Green
        "#fab387",  # 3: Pastel Peach
        "#cba6f7",  # 4: Pastel Mauve
        "#94e2d5",  # 5: Pastel Teal
        "#f2cdcd",  # 6: Pastel Flamingo
        "#89dceb",  # 7: Pastel Sapphire
        "#f38ba8",  # 8: Pastel Red
        "#74c7ec",  # 9: Pastel Sky
    ],
}
# Backward compatibility alias
GRAPH_COLORS = GRAPH_LANES["dark"]


def get_graph_lane_color(index: int, is_dark: bool) -> str:
    """Returns the hex color string for a graph lane index."""
    lanes = GRAPH_LANES["dark" if is_dark else "light"]
    return lanes[index % len(lanes)]


def get_graph_lane_qcolor(index: int, is_dark: bool) -> QColor:
    """Returns a QColor object for a graph lane index."""
    return QColor(get_graph_lane_color(index, is_dark))


# --- Ref Badge Colors (HEAD, Tag, Branch) ---

REF_BADGE_COLORS = {
    "light": {
        "head": "#8839ef",  # Mauve (purple)
        "tag": "#fe640b",  # Peach (orange)
        "branch": "#1e66f5",  # Sapphire (blue)
    },
    "dark": {
        "head": "#cba6f7",  # Mauve
        "tag": "#fab387",  # Peach
        "branch": "#89b4fa",  # Sapphire
    },
}


def get_ref_badge_color(kind: str, is_dark: bool) -> str:
    """Returns the hex color string for a ref badge kind."""
    palette = REF_BADGE_COLORS["dark" if is_dark else "light"]
    return palette.get(kind, palette["branch"])


def get_ref_badge_qcolor(kind: str, is_dark: bool) -> QColor:
    """Returns a QColor for a ref badge kind."""
    return QColor(get_ref_badge_color(kind, is_dark))


# --- Semantic Banners (Error, Warning, Info, Success) ---

BANNER_STYLES = {
    "light": {
        "error": {"bg": "#fee2e2", "border": "#ef4444", "fg": "#991b1b"},
        "warning": {"bg": "#fef3c7", "border": "#f59e0b", "fg": "#92400e"},
        "info": {"bg": "#f1f5f9", "border": "#64748b", "fg": "#334155"},
        "success": {"bg": "#dcfce7", "border": "#22c55e", "fg": "#15803d"},
    },
    "dark": {
        "error": {"bg": "#3a1c24", "border": "#f38ba8", "fg": "#f38ba8"},
        "warning": {"bg": "#38281a", "border": "#fab387", "fg": "#fab387"},
        "info": {"bg": "#252638", "border": "#89b4fa", "fg": "#cdd6f4"},
        "success": {"bg": "#1e3827", "border": "#a6e3a1", "fg": "#a6e3a1"},
    },
}


def get_banner_style(level: str, is_dark: bool) -> dict[str, str]:
    """Returns {'bg': hex, 'border': hex, 'fg': hex} for a banner level."""
    mode = "dark" if is_dark else "light"
    return BANNER_STYLES[mode].get(level, BANNER_STYLES[mode]["error"])


# --- Forge Badges & CI Config (Migrated from badges.py) ---

FORGE_BADGE_COLORS = {
    "light": {
        "open": ("#2a5c20", "#dcfce7"),  # Dark green on pastel green
        "merged": ("#582d8c", "#f3e8ff"),  # Dark purple on pastel purple
        "closed": ("#8c1d28", "#fee2e2"),  # Dark red on pastel red
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

REMOTE_BADGE_COLORS = {
    "light": {"fg": "#1e40af", "bg": "#dbeafe"},
    "dark": {"fg": "#89b4fa", "bg": "#1e2942"},
}


def get_remote_badge_colors(is_dark: bool) -> tuple[str, str]:
    """Returns (fg_hex, bg_hex) for remote source badges."""
    colors = REMOTE_BADGE_COLORS["dark" if is_dark else "light"]
    return colors["fg"], colors["bg"]


# --- Popover Styles (Migrated from info_popover.py) ---

INFO_POPOVER_STYLES = {
    "light": {
        "bg": "#eff1f5",
        "border": "#ccd0da",
        "text": "#4c4f69",
        "link": "#1e66f5",
        "tool": "#7c7f93",
    },
    "dark": {
        "bg": "#313244",
        "border": "#45475a",
        "text": "#cdd6f4",
        "link": "#89b4fa",
        "tool": "#a6adc8",
    },
}


def get_info_popover_style(is_dark: bool) -> str:
    """Returns the QSS stylesheet for InfoPopover."""
    mode = "dark" if is_dark else "light"
    p = INFO_POPOVER_STYLES[mode]
    return (
        f"InfoPopover {{ background-color: {p['bg']}; border: 1px solid {p['border']}; "
        f"border-radius: 8px; }} QLabel {{ color: {p['text']}; font-size: 12px; }} "
        f"a {{ color: {p['link']}; text-decoration: underline; }} "
        f"QToolButton {{ color: {p['tool']}; }}"
    )


# --- Merge Tool & Action Colors ---

MERGE_MODE_COLORS = {
    "light": {"rebase": "#df8e1d", "merge": "#1e66f5"},
    "dark": {"rebase": "#fab387", "merge": "#89b4fa"},
}


def get_merge_mode_color(mode: str, is_dark: bool) -> str:
    """Returns the hex color string for rebase or merge mode labels."""
    m = "dark" if is_dark else "light"
    return MERGE_MODE_COLORS[m].get(mode, MERGE_MODE_COLORS[m]["merge"])


SUCCESS_BUTTON_STYLES = {
    "light": (
        "QPushButton { font-weight: bold; background-color: #40a02b; color: #ffffff; "
        "padding: 6px 12px; border: none; border-radius: 4px; } "
        "QPushButton:hover { background-color: #348423; }"
    ),
    "dark": (
        "QPushButton { font-weight: bold; background-color: #a6e3a1; color: #11111b; "
        "padding: 6px 12px; border: none; border-radius: 4px; } "
        "QPushButton:hover { background-color: #94d38f; }"
    ),
}

PRIMARY_BUTTON_STYLES = {
    "light": (
        "QPushButton { background-color: #1e66f5; color: #ffffff; font-weight: bold; "
        "font-size: 12px; padding: 5px 12px; border: none; border-radius: 4px; } "
        "QPushButton:hover { background-color: #1857d4; color: #ffffff; } "
        "QPushButton:pressed { background-color: #154bb8; color: #ffffff; } "
        "QPushButton:disabled { background-color: #e6e9ef; color: #7c7f93; "
        "font-weight: bold; font-size: 12px; padding: 5px 12px; "
        "border: 1px solid rgba(76, 79, 105, 0.2); border-radius: 4px; }"
    ),
    "dark": "",
}

FORGE_LINK_STYLES = {
    "light": {
        "frame": (
            "background-color: rgba(59, 130, 246, 0.1); "
            "border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 4px;"
        ),
        "label": "color: #1e40af; font-size: 11px;",
    },
    "dark": {
        "frame": (
            "background-color: rgba(59, 130, 246, 0.15); "
            "border: 1px solid rgba(59, 130, 246, 0.4); border-radius: 4px;"
        ),
        "label": "color: #93c5fd; font-size: 11px;",
    },
}

DIFF_TEXT_COLOR = {
    "light": "#4c4f69",
    "dark": "#cdd6f4",
}


# --- Remotes Reachability Colors ---

REMOTES_STATUS_COLORS = {
    "reachable": {"light": "#2da44e", "dark": "#a6e3a1"},
    "unreachable": {"light": "#cf222e", "dark": "#f38ba8"},
    "unknown": {"light": "#6e7781", "dark": "#9399b2"},
}


def get_remote_status_color(is_reachable: bool | None, is_dark: bool) -> QColor:
    """Returns QColor for remote reachability status indicator."""
    mode = "dark" if is_dark else "light"
    if is_reachable is True:
        key = "reachable"
    elif is_reachable is False:
        key = "unreachable"
    else:
        key = "unknown"
    return QColor(REMOTES_STATUS_COLORS[key][mode])
