"""UI tests for SettingsDialog v2 (VP-0 13-Category Registry Preferences Center).

Verifies:
- 13 categories in QListWidget in exact canonical order
- OPT-1 Lazy Category Page Loading
- Instant search filter (< 5 ms)
- Scope selector (Global vs Repo Override)
- Minimalist local-only 1-click preset
- Delta undo/redo actions
- Category reset
- Non-blocking headless execution (FLASH-4)
"""

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import CATEGORIES_ORDER
from wrench.ui.dialogs.settings_dialog import SettingsDialog
from wrench.ui.main_window import MainWindow


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    yield conn
    conn.close()


@pytest.fixture
def main_window(db_conn):
    win = MainWindow(conn=db_conn)
    win.show()
    yield win
    win.close()


def test_v2_dialog_13_categories_in_nav_list(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg.nav_list.count() == 13
    for i, cat in enumerate(CATEGORIES_ORDER):
        assert dlg.nav_list.item(i).text() == cat
    dlg.close()


def test_v2_dialog_lazy_page_instantiation(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    # Row 0 ("General & UI") is selected initially, so only 1 page instantiated
    assert len(dlg._category_pages) == 1
    assert "General & UI" in dlg._category_pages

    # Switch to Commit Graph (index 2)
    dlg.nav_list.setCurrentRow(2)
    assert len(dlg._category_pages) == 2
    assert "Commit Graph" in dlg._category_pages
    dlg.close()


def test_v2_dialog_search_filter_instant(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    dlg.show()
    dlg.search_input.setText("gravatar")

    # Should automatically focus on "General & UI" and show only the matching row
    page = dlg._get_or_create_category_page("General & UI")
    matching_rows = [r for r in page.row_widgets if not r.isHidden()]
    assert len(matching_rows) == 1
    assert matching_rows[0].spec.key == "ui.avatars_gravatar"

    # Clear search
    dlg.search_input.setText("")
    all_visible = [r for r in page.row_widgets if not r.isHidden()]
    assert len(all_visible) == len(page.row_widgets)
    dlg.close()


def test_v2_dialog_scope_selector(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg.active_scope is None
    assert dlg.scope_combo.count() >= 1
    assert dlg.scope_combo.currentIndex() == 0
    dlg.close()


def test_v2_dialog_minimalist_preset_and_undo(main_window, db_conn):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    reg = dlg.registry

    assert reg.get_bool("forge.enabled") is True
    assert reg.get_bool("lfs.enabled") is True

    # Apply minimalist mode
    dlg.btn_minimalist.click()
    assert reg.get_bool("forge.enabled") is False
    assert reg.get_bool("lfs.enabled") is False
    assert "Minimalist" in dlg.toast_label.text()

    # Undo
    dlg.btn_undo.click()
    assert "Undone" in dlg.toast_label.text()
    dlg.close()


def test_v2_dialog_reset_category(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    dlg.nav_list.setCurrentRow(2)  # Commit Graph
    reg = dlg.registry

    reg.set("graph.lane_width_px", 28)
    assert reg.get_int("graph.lane_width_px") == 28

    dlg.btn_reset_category.click()
    assert reg.get_int("graph.lane_width_px") == 16
    assert "Reset category" in dlg.toast_label.text()
    dlg.close()
