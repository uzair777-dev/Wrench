"""Unit tests for theme switching, Catppuccin Velvet Pastel palettes, and UI responsiveness."""

import sqlite3

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from wrench.core.engine import Diff, DiffLine, Hunk
from wrench.storage import settings
from wrench.storage.db import run_migrations
from wrench.ui.diff_view.diff_widget import DiffWidget
from wrench.ui.main_window import MainWindow
from wrench.ui.tabs.changes_tab import ChangesTab, FileListItemWidget
from wrench.ui.theme import (
    create_pastel_dark_palette,
    create_pastel_light_palette,
    get_badge_colors,
    is_dark_theme,
)


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


def test_pastel_palettes():
    light_pal = create_pastel_light_palette()
    assert light_pal.window().color().name().lower() == "#eff1f5"
    assert light_pal.base().color().name().lower() == "#ffffff"
    assert light_pal.windowText().color().name().lower() == "#4c4f69"

    dark_pal = create_pastel_dark_palette()
    assert dark_pal.window().color().name().lower() == "#181825"
    assert dark_pal.base().color().name().lower() == "#11111b"
    assert dark_pal.windowText().color().name().lower() == "#cdd6f4"


def test_is_dark_theme():
    widget = DiffWidget()
    widget.setPalette(create_pastel_light_palette())
    assert is_dark_theme(widget) is False

    widget.setPalette(create_pastel_dark_palette())
    assert is_dark_theme(widget) is True


def test_badge_colors():
    # Light mode
    m_fg, m_bg = get_badge_colors("M", is_dark=False)
    assert m_fg == "#1e66f5"
    assert m_bg == "#e0e7ff"

    a_fg, a_bg = get_badge_colors("A", is_dark=False)
    assert a_fg == "#40a02b"
    assert a_bg == "#dcfce7"

    d_fg, d_bg = get_badge_colors("D", is_dark=False)
    assert d_fg == "#d20f39"
    assert d_bg == "#fee2e2"

    # Dark mode
    m_fg_d, m_bg_d = get_badge_colors("M", is_dark=True)
    assert m_fg_d == "#89b4fa"
    assert m_bg_d == "#1e2942"

    a_fg_d, a_bg_d = get_badge_colors("A", is_dark=True)
    assert a_fg_d == "#a6e3a1"
    assert a_bg_d == "#1b3526"

    d_fg_d, d_bg_d = get_badge_colors("D", is_dark=True)
    assert d_fg_d == "#f38ba8"
    assert d_bg_d == "#3b1c28"


def test_diff_widget_theme_switching():
    diff = Diff(
        path="foo.py",
        is_binary=False,
        hunks=[
            Hunk(
                id="hunk_0",
                old_start=1,
                old_count=2,
                new_start=1,
                new_count=2,
                lines=[
                    DiffLine(origin=" ", content="unchanged", old_lineno=1, new_lineno=1),
                    DiffLine(origin="-", content="old line", old_lineno=2, new_lineno=-1),
                    DiffLine(origin="+", content="new line", old_lineno=-1, new_lineno=2),
                ],
            )
        ],
    )

    widget = DiffWidget()
    widget.set_diff_model(diff, title="Diff: foo.py", read_only=True)

    # 1. Switch to Light Mode
    widget.setPalette(create_pastel_light_palette())
    widget.refresh_theme()
    html_light = widget.editor.toHtml()
    assert "#dcefd8" in html_light  # pastel green add bg
    assert "#216e39" in html_light  # pastel green add text
    assert "#fcd7db" in html_light  # pastel red del bg
    assert "#a8233e" in html_light  # pastel red del text
    assert "#ffffff" in widget.editor.styleSheet()

    # 2. Switch to Dark Mode
    widget.setPalette(create_pastel_dark_palette())
    widget.refresh_theme()
    html_dark = widget.editor.toHtml()
    assert "#1e3527" in html_dark  # dark pastel green add bg
    assert "#a6e3a1" in html_dark  # dark pastel green add text
    assert "#3b1d28" in html_dark  # dark pastel red del bg
    assert "#f38ba8" in html_dark  # dark pastel red del text
    assert "#11111b" in widget.editor.styleSheet()

    # 3. Simulate PaletteChange event
    widget.setPalette(create_pastel_light_palette())
    event = QEvent(QEvent.PaletteChange)
    widget.changeEvent(event)
    assert "#dcefd8" in widget.editor.toHtml()


def test_repo_combo_stylesheet_and_file_item_badge():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    tab = ChangesTab(conn=conn)

    # 1. Dark mode: untouched native button and original dark combo stylesheet
    tab.setPalette(create_pastel_dark_palette())
    tab.refresh_theme()
    assert "color: palette(window-text);" in tab.repo_combo.styleSheet()
    assert "QComboBox QAbstractItemView" in tab.repo_combo.styleSheet()
    assert tab.commit_btn.styleSheet() == ""  # Untouched native Qt button

    # 2. Light mode: readable dark text on combo and sapphire commit button
    tab.setPalette(create_pastel_light_palette())
    tab.refresh_theme()
    assert "#4c4f69" in tab.repo_combo.styleSheet()
    assert "QComboBox QAbstractItemView" in tab.repo_combo.styleSheet()
    assert "#1e66f5" in tab.commit_btn.styleSheet()
    assert "#ffffff" in tab.commit_btn.styleSheet()
    assert "#7c7f93" in tab.commit_btn.styleSheet()

    # Badge style in light vs dark
    item_widget = FileListItemWidget("test.txt", "M")
    item_widget.setPalette(create_pastel_light_palette())
    item_widget.refresh_theme()
    assert "#1e66f5" in item_widget.badge.styleSheet()
    assert "#e0e7ff" in item_widget.badge.styleSheet()

    item_widget.setPalette(create_pastel_dark_palette())
    item_widget.refresh_theme()
    assert "#89b4fa" in item_widget.badge.styleSheet()
    assert "#1e2942" in item_widget.badge.styleSheet()


def test_main_window_theme_menu_and_persistence():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    win1 = MainWindow(conn=conn)
    assert win1.act_theme_auto.isChecked() is True

    # Set light theme
    win1._set_theme("light")
    assert win1.act_theme_light.isChecked() is True
    assert settings.get_setting(conn, "theme") == "light"

    # Set dark theme
    win1._set_theme("dark")
    assert win1.act_theme_dark.isChecked() is True
    assert settings.get_setting(conn, "theme") == "dark"

    # Restore in new window
    win2 = MainWindow(conn=conn)
    assert win2._current_theme_mode == "dark"
    assert win2.act_theme_dark.isChecked() is True


def test_tab_button_and_container_theme_refresh():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    win = MainWindow(conn=conn)
    tab_container = win.tab_container
    assert tab_container.count() >= 2

    # Switch to Dark
    win._set_theme("dark")
    active_btn = tab_container._tab_buttons[tab_container.current_index()]
    assert "color: palette(window-text)" in active_btn.styleSheet()

    inactive_idx = 1 if tab_container.current_index() == 0 else 0
    inactive_btn = tab_container._tab_buttons[inactive_idx]
    assert "color: palette(placeholder-text)" in inactive_btn.styleSheet()

    # Switch to Light
    win._set_theme("light")
    assert "color: palette(window-text)" in active_btn.styleSheet()
    assert "color: palette(placeholder-text)" in inactive_btn.styleSheet()


def test_changes_tab_palette_propagation():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    win = MainWindow(conn=conn)

    # 1. Switch to Dark
    win._set_theme("dark")
    assert is_dark_theme(win.changes_tab) is True
    assert win.changes_tab.files_list.palette().base().color().name().lower() == "#11111b"
    assert win.changes_tab.commit_desc_input.palette().base().color().name().lower() == "#11111b"

    # 2. Switch to Light
    win._set_theme("light")
    assert is_dark_theme(win.changes_tab) is False
    assert win.changes_tab.files_list.palette().base().color().name().lower() == "#ffffff"
    assert win.changes_tab.commit_desc_input.palette().base().color().name().lower() == "#ffffff"
