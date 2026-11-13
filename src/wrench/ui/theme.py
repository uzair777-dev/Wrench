"""Theme definitions and color management for Wrench.

Implements the Catppuccin Velvet Pastel design system:
- Light Mode: Catppuccin Latte Pastel
- Dark Mode: Catppuccin Mocha Velvet Pastel
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QMainWindow, QWidget

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
    elif isinstance(widget_or_palette, QWidget) and widget_or_palette.testAttribute(
        Qt.WidgetAttribute.WA_SetPalette
    ):
        pal = widget_or_palette.palette()
    elif (
        widget_or_palette is not None
        and hasattr(widget_or_palette, "palette")
        and not isinstance(widget_or_palette, QWidget)
    ):
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
    "light": "#5c5f77",  # Subtext1 — high-contrast slate (5.5:1 against window)
    "dark": "#a6adc8",  # Subtext0 — soft lavender-gray (7.9:1 against window)
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


# --- Icon Color Tokens (FR-11.8) ---
DEFAULT_ICON_COLOR = "#cdd6f4"
ICON_COLOR_MOCHA = "#cdd6f4"
ICON_COLOR_LATTE = "#4c4f69"

# --- Context Header Bar Tokens (FR-11.9) ---
CONTEXT_BAR_BG_DARK = "#11111b"
CONTEXT_BAR_BG_LIGHT = "#dce0e8"
CONTEXT_BAR_BORDER_DARK = "#313244"
CONTEXT_BAR_BORDER_LIGHT = "#ccd0da"
CONTEXT_BAR_SUBTITLE_DARK = "#a6adc8"
CONTEXT_BAR_SUBTITLE_LIGHT = "#6c6f85"
CONTEXT_BAR_TITLE_DARK = "#cdd6f4"
CONTEXT_BAR_TITLE_LIGHT = "#4c4f69"
CONTEXT_BTN_BG_DARK = "#181825"
CONTEXT_BTN_BG_LIGHT = "#e6e9ef"

# --- Launchpad & Diff Gutter Tokens (FR-11.10) ---
LAUNCHPAD_CARD_BG_DARK = "#181825"
LAUNCHPAD_CARD_BG_LIGHT = "#e6e9ef"
LAUNCHPAD_CARD_BORDER_DARK = "#313244"
LAUNCHPAD_CARD_BORDER_LIGHT = "#ccd0da"
LAUNCHPAD_TITLE_DARK = "#cdd6f4"
LAUNCHPAD_TITLE_LIGHT = "#4c4f69"
LAUNCHPAD_SUBTITLE_DARK = "#a6adc8"
LAUNCHPAD_SUBTITLE_LIGHT = "#6c6f85"
LAUNCHPAD_KBD_BG_DARK = "#11111b"
LAUNCHPAD_KBD_BG_LIGHT = "#dce0e8"
LAUNCHPAD_KBD_TEXT_DARK = "#bac2de"
LAUNCHPAD_KBD_TEXT_LIGHT = "#4c4f69"
DIFF_GUTTER_BG_DARK = "#181825"
DIFF_GUTTER_BG_LIGHT = "#e6e9ef"
DIFF_GUTTER_TEXT_DARK = "#6c7086"
DIFF_GUTTER_TEXT_LIGHT = "#9ca0b0"
DIFF_ADD_BAR = "#a6e3a1"
DIFF_DEL_BAR = "#f38ba8"

# --- History View & Neon Lane Tokens (FR-3.17) ---
SIDEBAR_BG_DARK = "#181825"
SIDEBAR_BG_LIGHT = "#e6e9ef"
INSPECTOR_BG_DARK = "#181825"
INSPECTOR_BG_LIGHT = "#e6e9ef"
GRAPH_CANVAS_BG_DARK = "#1e1e2e"
GRAPH_CANVAS_BG_LIGHT = "#eff1f5"
NEON_LANES_DARK = (
    "#89b4fa",
    "#94e2d5",
    "#cba6f7",
    "#f5c2e7",
    "#f38ba8",
    "#fab387",
    "#f9e2af",
    "#a6e3a1",
    "#74c7ec",
    "#b4befe",
)

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
    pal.setColor(QPalette.PlaceholderText, QColor(SECONDARY_TEXT["light"]))
    pal.setColor(QPalette.Mid, QColor("#ccd0da"))  # Surface0 — subtle card/bevel borders
    pal.setColor(QPalette.Midlight, QColor("#bcc0cc"))  # Surface1
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
    pal.setColor(QPalette.PlaceholderText, QColor(SECONDARY_TEXT["dark"]))
    pal.setColor(QPalette.Mid, QColor("#45475a"))  # Surface1 — subtle card/bevel borders
    pal.setColor(QPalette.Midlight, QColor("#585b70"))  # Surface2
    return pal


def build_catppuccin_palette(theme_name: str = "mocha") -> QPalette:
    """Builds a strict 4-Tier Catppuccin QPalette setting all 18 ColorRoles (FR-11.7).

    // LO, i tuned every single role here so Qt native widgets never bleed 3D gray
    """
    pal = QPalette()
    norm = normalize_theme_mode(theme_name, target="legacy")
    is_dark = norm in ("dark", "mocha", "system", "auto")

    if is_dark:
        # Tier 1 Mantle Window
        pal.setColor(QPalette.ColorRole.Window, QColor("#181825"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#cdd6f4"))
        # Tier 2 Base Canvas
        pal.setColor(QPalette.ColorRole.Base, QColor("#1e1e2e"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#181825"))
        # Tier 0 Crust Deep Chrome
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#11111b"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#cdd6f4"))
        pal.setColor(QPalette.ColorRole.Dark, QColor("#11111b"))
        pal.setColor(QPalette.ColorRole.Shadow, QColor("#11111b"))
        # Text & Controls
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6c7086"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#cdd6f4"))
        # Tier 3 Surface0 Controls
        pal.setColor(QPalette.ColorRole.Button, QColor("#313244"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#cdd6f4"))
        pal.setColor(QPalette.ColorRole.BrightText, QColor("#f38ba8"))
        pal.setColor(QPalette.ColorRole.Link, QColor("#89b4fa"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#313244"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#89b4fa"))
        pal.setColor(QPalette.ColorRole.Mid, QColor("#45475a"))
        pal.setColor(QPalette.ColorRole.Midlight, QColor("#585b70"))
    else:
        # Tier 1 Mantle Window
        pal.setColor(QPalette.ColorRole.Window, QColor("#e6e9ef"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#4c4f69"))
        # Tier 2 Base Canvas
        pal.setColor(QPalette.ColorRole.Base, QColor("#eff1f5"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#e6e9ef"))
        # Tier 0 Crust Deep Chrome
        pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#dce0e8"))
        pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#4c4f69"))
        pal.setColor(QPalette.ColorRole.Dark, QColor("#dce0e8"))
        pal.setColor(QPalette.ColorRole.Shadow, QColor("#dce0e8"))
        # Text & Controls
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9ca0b0"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#4c4f69"))
        # Tier 3 Surface0 Controls
        pal.setColor(QPalette.ColorRole.Button, QColor("#ccd0da"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#4c4f69"))
        pal.setColor(QPalette.ColorRole.BrightText, QColor("#d20f39"))
        pal.setColor(QPalette.ColorRole.Link, QColor("#1e66f5"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#ccd0da"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#1e66f5"))
        pal.setColor(QPalette.ColorRole.Mid, QColor("#bcc0cc"))
        pal.setColor(QPalette.ColorRole.Midlight, QColor("#acb0be"))
    return pal


def get_global_catppuccin_qss(theme_name: str = "mocha") -> str:
    """Return the global 4-Tier Catppuccin QSS stylesheet (ui-planning.md §6.29.1)."""
    norm = normalize_theme_mode(theme_name, target="legacy")
    is_dark = norm in ("dark", "mocha", "system", "auto")

    if is_dark:
        bg_window = "#181825"
        bg_crust = "#11111b"
        border_col = "#313244"
        fg_text = "#cdd6f4"
        fg_subtext0 = "#a6adc8"
        accent_blue = "#89b4fa"
        scrollbar_thumb = "rgba(166, 173, 200, 0.28)"
        scrollbar_hover = "rgba(137, 180, 250, 0.6)"
    else:
        bg_window = "#e6e9ef"
        bg_crust = "#dce0e8"
        border_col = "#ccd0da"
        fg_text = "#4c4f69"
        fg_subtext0 = "#6c6f85"
        accent_blue = "#1e66f5"
        scrollbar_thumb = "rgba(92, 95, 119, 0.28)"
        scrollbar_hover = "rgba(30, 102, 245, 0.6)"

    return f"""
    QHeaderView::section {{
        background-color: {bg_crust};
        color: {fg_subtext0};
        border: none;
        border-bottom: 1px solid {border_col};
        border-right: 1px solid {bg_window};
        padding: 6px 10px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
    }}
    QSplitter::handle {{
        background-color: {border_col};
        width: 1px;
        height: 1px;
    }}
    QSplitter::handle:hover {{
        background-color: {accent_blue};
    }}
    QTabBar::tab:selected {{
        border-bottom: 2px solid {accent_blue};
        font-weight: bold;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background: {scrollbar_thumb};
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {scrollbar_hover};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 8px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background: {scrollbar_thumb};
        min-width: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {scrollbar_hover};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
        border: none;
        background: none;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}
    """


def normalize_theme_mode(mode: str | None, *, target: str = "canonical") -> str:
    """Normalize theme mode between canonical ('system') and legacy ('auto') names."""
    raw = str(mode or "").strip().lower()
    if raw in ("light", "dark"):
        return raw
    return "auto" if target == "legacy" else "system"


def repolish_widget(widget: QWidget | None) -> None:
    """Re-polish a Qt widget and schedule a repaint so palette/QSS updates show live."""
    if widget is None or not shiboken6.isValid(widget):
        return
    try:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()
    except RuntimeError as exc:
        logger.debug("Skipping repolish on deleted widget: %s", exc)


def apply_theme(app: QApplication, mode: str) -> None:
    """Applies a theme mode ('auto', 'system', 'light', 'dark') to the application."""
    norm_mode = normalize_theme_mode(mode, target="legacy")
    hints = app.styleHints() if hasattr(app, "styleHints") else None
    if hints is not None:
        if norm_mode == "dark" and hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Dark)
        elif norm_mode == "light" and hasattr(hints, "setColorScheme"):
            hints.setColorScheme(Qt.ColorScheme.Light)
        elif norm_mode == "auto" and hasattr(hints, "unsetColorScheme"):
            hints.unsetColorScheme()

    if hasattr(app, "setStyle"):
        try:
            app.setStyle("Fusion")
        except Exception as exc:
            logger.debug("Failed setting Fusion style: %s", exc)

    if norm_mode in ("mocha", "latte", "catppuccin", "catppuccin_mocha", "catppuccin_latte"):
        palette = build_catppuccin_palette(norm_mode)
    elif norm_mode == "light":
        palette = create_pastel_light_palette()
    elif norm_mode == "dark":
        palette = create_pastel_dark_palette()
    else:  # 'auto' / system
        palette = app.style().standardPalette()

    def _is_active_window(w: QWidget) -> bool:
        if not shiboken6.isValid(w):
            return False
        try:
            if getattr(w, "_is_closing", False):
                return False
            # Skip already-closed windows/dialogs retained in QApplication.topLevelWidgets()
            if w.testAttribute(Qt.WidgetAttribute.WA_WState_ExplicitShowHide) and w.isHidden():
                return False
            # Skip unshown popup/container helpers (e.g. orphaned QMenu/QFrame)
            if not w.isVisible() and not isinstance(w, (QMainWindow, QDialog)):
                return False
        except RuntimeError as exc:
            logger.debug("Skipping deleted top-level widget during theme apply: %s", exc)
            return False
        return True

    try:
        raw_top_widgets = QApplication.topLevelWidgets()
    except RuntimeError as exc:
        logger.debug("Failed collecting top-level widgets during theme apply: %s", exc)
        raw_top_widgets = []

    top_widgets = [w for w in raw_top_widgets if _is_active_window(w)]
    top_ids = {id(w) for w in top_widgets}
    child_widgets: list[QWidget] = []
    seen_child_ids: set[int] = set()
    for top_widget in top_widgets:
        if not shiboken6.isValid(top_widget):
            continue
        try:
            found_children = top_widget.findChildren(QWidget)
        except RuntimeError as exc:
            logger.debug("Skipping children of deleted widget during theme apply: %s", exc)
            continue
        for child in found_children:
            try:
                if not shiboken6.isValid(child):
                    continue
                cid = id(child)
                if cid not in top_ids and cid not in seen_child_ids:
                    seen_child_ids.add(cid)
                    child_widgets.append(child)
            except RuntimeError as exc:
                logger.debug("Skipping deleted child widget during theme apply: %s", exc)

    app.setPalette(palette)

    global_qss = get_global_catppuccin_qss(norm_mode)
    if hasattr(app, "setStyleSheet") and global_qss:
        try:
            app.setStyleSheet(global_qss)
        except Exception as exc:
            logger.debug("Failed setting global Catppuccin QSS: %s", exc)

    # Set palette on top-level windows and child widgets AFTER applying stylesheet
    # so Qt's QStyleSheetStyle polish doesn't reset child palettes to obsolete cache.
    for top_widget in top_widgets:
        if shiboken6.isValid(top_widget):
            try:
                top_widget.setPalette(palette)
            except RuntimeError as exc:
                logger.debug("Skipping setPalette on deleted top-level widget: %s", exc)

    for child in child_widgets:
        if shiboken6.isValid(child):
            try:
                child.setPalette(palette)
            except RuntimeError as exc:
                logger.debug("Skipping setPalette on deleted child widget: %s", exc)

    for top_widget in top_widgets:
        if shiboken6.isValid(top_widget):
            try:
                if top_widget.isVisible():
                    repolish_widget(top_widget)
            except RuntimeError as exc:
                logger.debug("Skipping repolish on deleted top-level widget: %s", exc)
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
        "MM": ("#d20f39", "#fce7f3"),  # Partially Staged: Rose on soft pink
        "AM": ("#179299", "#ccfbf1"),  # Added+Modified: Teal on soft teal
        "MD": ("#df8e1d", "#fef3c7"),  # Modified+Deleted: Amber on soft yellow
        "AD": ("#fe640b", "#ffedd5"),  # Added+Deleted: Rust on soft peach
    },
    "dark": {
        "M": ("#89b4fa", "#1e2942"),  # Modified: Pastel sky on dark blue
        "A": ("#a6e3a1", "#1b3526"),  # Added: Pastel mint on dark green
        "D": ("#f38ba8", "#3b1c28"),  # Deleted: Pastel flamingo on dark red
        "R": ("#cba6f7", "#2c1e3d"),  # Renamed: Pastel mauve on dark purple
        "?": ("#9399b2", "#282a3a"),  # Untracked: Pastel slate on dark slate
        "⚠ C": ("#fab387", "#3d261e"),  # Conflict: Pastel peach on dark amber
        "MM": ("#f5c2e7", "#3d1f33"),  # Partially Staged: Catppuccin Pink on plum
        "AM": ("#94e2d5", "#1c3836"),  # Added+Modified: Catppuccin Teal on dark teal
        "MD": ("#f9e2af", "#3a301d"),  # Modified+Deleted: Catppuccin Yellow on dark amber
        "AD": ("#fab387", "#3d261e"),  # Added+Deleted: Catppuccin Peach on dark peach
    },
}


def get_badge_colors(change_type: str, is_dark: bool) -> tuple[str, str]:
    """Returns (foreground_color, background_color) for a status badge."""
    mode_key = "dark" if is_dark else "light"
    styles = BADGE_STYLES[mode_key]
    if change_type in styles:
        return styles[change_type]
    # For any partially staged composite code (e.g. 2 chars), fallback to MM style
    if len(change_type) == 2 and "MM" in styles:
        return styles["MM"]
    default_colors = ("#9399b2", "#282a3a") if is_dark else ("#7c7f93", "#e6e9ef")
    return default_colors


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
    "success": ("✔", "#216e39", "#a6e3a1", "CI: Success — all checks passed"),
    "failure": ("✖", "#d20f39", "#f38ba8", "CI: Failure — checks failed"),
    "pending": ("●", "#1153d6", "#89b4fa", "CI: Pending — checks in progress"),
    "unknown": ("○", "#5c5f77", "#a6adc8", "CI: No checks reported / unknown"),
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
    "light": {"rebase": "#8c4400", "merge": "#1153d6"},
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
    "dark": (
        "QPushButton { background-color: #89b4fa; color: #11111b; font-weight: bold; "
        "font-size: 12px; padding: 5px 12px; border: none; border-radius: 4px; } "
        "QPushButton:hover { background-color: #74c7ec; color: #11111b; } "
        "QPushButton:pressed { background-color: #b4befe; color: #11111b; } "
        "QPushButton:disabled { background-color: #313244; color: #a6adc8; "
        "font-weight: bold; font-size: 12px; padding: 5px 12px; "
        "border: 1px solid #45475a; border-radius: 4px; }"
    ),
}

SECONDARY_BUTTON_STYLES = {
    "light": {
        "bg": "#e6e9ef",
        "fg": "#4c4f69",
        "hover": "#dce0e8",
        "pressed": "#ccd0da",
        "border": "#bcc0cc",
        "disabled_bg": "#eff1f5",
        "disabled_fg": "#5c5f77",
    },
    "dark": {
        "bg": "#313244",
        "fg": "#cdd6f4",
        "hover": "#3e4054",
        "pressed": "#45475a",
        "border": "#45475a",
        "disabled_bg": "#1e1e2e",
        "disabled_fg": "#a6adc8",
    },
}


def get_secondary_button_style(is_dark: bool, *, compact: bool = False) -> str:
    """Return theme-aware QSS for secondary QPushButton controls."""
    c = SECONDARY_BUTTON_STYLES["dark" if is_dark else "light"]
    pad = "3px 8px" if compact else "5px 12px"
    return (
        f"QPushButton {{ background-color: {c['bg']}; color: {c['fg']}; "
        f"border: 1px solid {c['border']}; border-radius: 4px; padding: {pad}; }} "
        f"QPushButton:hover {{ background-color: {c['hover']}; }} "
        f"QPushButton:pressed {{ background-color: {c['pressed']}; }} "
        f"QPushButton:disabled {{ background-color: {c['disabled_bg']}; "
        f"color: {c['disabled_fg']}; border: 1px solid {c['border']}; }}"
    )


ICON_BUTTON_STYLES = {
    "light": {
        "bg": "#e6e9ef",
        "fg": "#4c4f69",
        "hover": "#dce0e8",
        "pressed": "#ccd0da",
        "border": "#bcc0cc",
        "disabled_fg": "#5c5f77",
    },
    "dark": {
        "bg": "#313244",
        "fg": "#cdd6f4",
        "hover": "#3e4054",
        "pressed": "#45475a",
        "border": "#45475a",
        "disabled_fg": "#a6adc8",
    },
}


def get_icon_button_style(is_dark: bool, *, rounded: bool = False) -> str:
    """Return theme-aware QSS for icon / tool buttons (QToolButton / QPushButton)."""
    c = ICON_BUTTON_STYLES["dark" if is_dark else "light"]
    radius = "14px" if rounded else "4px"
    return (
        f"QToolButton, QPushButton {{ background-color: {c['bg']}; color: {c['fg']}; "
        f"border: 1px solid {c['border']}; border-radius: {radius}; padding: 2px 6px; }} "
        f"QToolButton:hover, QPushButton:hover {{ background-color: {c['hover']}; }} "
        f"QToolButton:pressed, QPushButton:pressed {{ background-color: {c['pressed']}; }} "
        f"QToolButton:disabled, QPushButton:disabled {{ color: {c['disabled_fg']}; }}"
    )


STATUS_PILL_STYLES = {
    "light": {
        "sparse_active": {"bg": "#dcfce7", "border": "#22c55e", "fg": "#15803d"},
        "sparse_inactive": {"bg": "#e6e9ef", "border": "#bcc0cc", "fg": "#4c4f69"},
        "watcher": {"bg": "#e0e7ff", "border": "#93c5fd", "fg": "#1e40af"},
        "info": {"bg": "#dbeafe", "border": "#93c5fd", "fg": "#1e40af"},
    },
    "dark": {
        "sparse_active": {"bg": "#1e3827", "border": "#a6e3a1", "fg": "#a6e3a1"},
        "sparse_inactive": {"bg": "#252638", "border": "#45475a", "fg": "#cdd6f4"},
        "watcher": {"bg": "#1e2942", "border": "#45475a", "fg": "#89b4fa"},
        "info": {"bg": "#1e2942", "border": "#89b4fa", "fg": "#89b4fa"},
    },
}


def get_status_pill_style(kind: str, is_dark: bool) -> dict[str, str]:
    """Return {'bg', 'border', 'fg'} token dict for status bar indicator pills."""
    mode = "dark" if is_dark else "light"
    return STATUS_PILL_STYLES[mode].get(kind, STATUS_PILL_STYLES[mode]["info"])


TREE_WIDGET_STYLES = {
    "light": {
        "bg": "#ffffff",
        "fg": "#4c4f69",
        "alt_bg": "#f7f8fa",
        "border": "#ccd0da",
        "header_bg": "#e6e9ef",
        "header_fg": "#4c4f69",
        "selected_bg": "#1e66f5",
        "selected_fg": "#ffffff",
    },
    "dark": {
        "bg": "#11111b",
        "fg": "#cdd6f4",
        "alt_bg": "#181825",
        "border": "#45475a",
        "header_bg": "#1e1e2e",
        "header_fg": "#cdd6f4",
        "selected_bg": "#89b4fa",
        "selected_fg": "#11111b",
    },
}


def get_tree_widget_qss(is_dark: bool) -> str:
    """Return Catppuccin QSS for QTreeWidget / QTreeView panels."""
    t = TREE_WIDGET_STYLES["dark" if is_dark else "light"]
    return (
        f"QTreeWidget {{ background-color: {t['bg']}; alternate-background-color: {t['alt_bg']}; "
        f"color: {t['fg']}; border: 1px solid {t['border']}; border-radius: 4px; }} "
        f"QTreeWidget::item:selected {{ background-color: {t['selected_bg']}; "
        f"color: {t['selected_fg']}; }} "
        f"QHeaderView::section {{ background-color: {t['header_bg']}; color: {t['header_fg']}; "
        f"border: none; border-bottom: 1px solid {t['border']}; padding: 4px 6px; }}"
    )


SETTINGS_BADGE_STYLES = {
    "light": {"bg": "#e0e7ff", "border": "#93c5fd", "fg": "#1e40af"},
    "dark": {"bg": "#1e2942", "border": "#45475a", "fg": "#89b4fa"},
}


def get_settings_badge_qss(is_dark: bool) -> str:
    """Return theme-aware QSS for settings scope badge pills."""
    b = SETTINGS_BADGE_STYLES["dark" if is_dark else "light"]
    return (
        f"QLabel {{ font-size: 11px; color: {b['fg']}; background-color: {b['bg']}; "
        f"border: 1px solid {b['border']}; padding: 2px 6px; border-radius: 4px; }}"
    )


TOAST_TEXT_COLOR = {
    "light": "#216e39",
    "dark": "#a6e3a1",
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


# --- Avatar Tile Colors (Catppuccin Velvet Pastel) ---

AVATAR_BG_COLORS = {
    "light": [
        "#1e66f5",  # Blue (4.5:1 with #ffffff)
        "#8839ef",  # Mauve (4.7:1 with #ffffff)
        "#2d7d20",  # Dark Green (4.6:1 with #ffffff)
        "#d20f39",  # Red (4.6:1 with #ffffff)
        "#d95700",  # Deep Peach (3.4:1 with #ffffff)
        "#179299",  # Teal (3.8:1 with #ffffff)
        "#b2535d",  # Flamingo (4.1:1 with #ffffff)
        "#0375a3",  # Sky (4.4:1 with #ffffff)
    ],
    "dark": [
        "#89b4fa",  # Pastel Sky (10.6:1 with #11111b)
        "#cba6f7",  # Pastel Mauve (9.8:1 with #11111b)
        "#a6e3a1",  # Pastel Green (12.8:1 with #11111b)
        "#fab387",  # Pastel Peach (11.0:1 with #11111b)
        "#f38ba8",  # Pastel Red (8.6:1 with #11111b)
        "#94e2d5",  # Pastel Teal (12.7:1 with #11111b)
        "#eba0ac",  # Pastel Maroon (8.9:1 with #11111b)
        "#74c7ec",  # Pastel Sapphire (10.3:1 with #11111b)
    ],
}

AVATAR_FG_COLORS = {
    "light": "#ffffff",
    "dark": "#11111b",
}


def get_avatar_bg_color(identifier: str, is_dark: bool) -> str:
    """Returns a deterministic Catppuccin swatch hex for initials avatar tiles."""
    palette = AVATAR_BG_COLORS["dark" if is_dark else "light"]
    idx = sum(ord(c) for c in identifier) % len(palette)
    return palette[idx]


def get_avatar_fg_color(is_dark: bool) -> str:
    """Returns the text hex color for initials avatar tiles."""
    return AVATAR_FG_COLORS["dark" if is_dark else "light"]


# --- CLI Command Preview Bar Styling (Catppuccin Velvet Pastel) ---

CLI_PREVIEW_STYLES = {
    "light": {
        "bg": "#e6e9ef",  # Catppuccin Latte Mantle
        "border": "#ccd0da",  # Catppuccin Latte Surface0
        "fg": "#4c4f69",  # Catppuccin Latte Text
    },
    "dark": {
        "bg": "#1e1e2e",  # Catppuccin Mocha Base
        "border": "#45475a",  # Catppuccin Mocha Surface1
        "fg": "#cdd6f4",  # Catppuccin Mocha Text
    },
}

READONLY_FIELD_STYLES = {
    "light": {
        "bg": "#e6e9ef",  # Catppuccin Latte Mantle
        "border": "#ccd0da",  # Catppuccin Latte Surface0
        "fg": "#4c4f69",  # Catppuccin Latte Text
        "placeholder_fg": "#5c5f77",  # Catppuccin Latte Subtext1
    },
    "dark": {
        "bg": "#1e1e2e",  # Catppuccin Mocha Base
        "border": "#45475a",  # Catppuccin Mocha Surface1
        "fg": "#cdd6f4",  # Catppuccin Mocha Text
        "placeholder_fg": "#a6adc8",  # Catppuccin Mocha Subtext0
    },
}


def get_readonly_field_qss(is_dark: bool, *, placeholder: bool = False) -> str:
    """Return theme-aware single-line read-only field QSS for path readouts."""
    c = READONLY_FIELD_STYLES["dark" if is_dark else "light"]
    fg = c["placeholder_fg"] if placeholder else c["fg"]
    font_style = "font-style: italic; " if placeholder else ""
    return (
        f"QLabel {{ background-color: {c['bg']}; color: {fg}; "
        f"border: 1px solid {c['border']}; border-radius: 4px; "
        f"padding: 4px 8px; {font_style}}}"
    )


REBASE_ACTION_COLORS = {
    "light": {
        "pick": "#4c4f69",
        "reword": "#1e66f5",
        "edit": "#92400e",
        "squash": "#8839ef",
        "fixup": "#157388",
        "drop": "#d20f39",
    },
    "dark": {
        "pick": "#cdd6f4",
        "reword": "#89b4fa",
        "edit": "#f9e2af",
        "squash": "#cba6f7",
        "fixup": "#94e2d5",
        "drop": "#f38ba8",
    },
}
