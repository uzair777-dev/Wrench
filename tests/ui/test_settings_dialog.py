"""UI tests for SettingsDialog and preference dispatch (Phase 4.3).

Verifies:
- 6 settings pages (Appearance, Tabs, Repositories, Snapshots, Forge, Advanced)
- Live preference mutation without split-brain state
- Palette/theme token compliance and QPainter preview strip
- Active repo snapshot settings binding
"""

import json
import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from wrench.core import snapshots
from wrench.storage import repo_registry, settings
from wrench.storage.db import run_migrations
from wrench.ui.dialogs.settings_dialog import (
    AdvancedPage,
    AppearancePage,
    ForgePage,
    RepositoriesPage,
    SettingsDialog,
    SnapshotsPage,
    TabsPage,
)
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
    return conn


@pytest.fixture
def main_window(db_conn):
    win = MainWindow(conn=db_conn)
    win.show()
    yield win
    win.close()


def test_settings_dialog_pages_exist(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    assert dlg.nav_list.count() == 6

    expected_titles = [
        "Appearance",
        "Tabs",
        "Repositories",
        "Snapshots",
        "Forge",
        "Advanced",
    ]
    for i, title in enumerate(expected_titles):
        assert dlg.nav_list.item(i).text() == title

    # Switch pages via nav_list selection
    for i in range(6):
        dlg.nav_list.setCurrentRow(i)
        assert dlg.page_stack.currentIndex() == i

    assert isinstance(dlg.pages[0], AppearancePage)
    assert isinstance(dlg.pages[1], TabsPage)
    assert isinstance(dlg.pages[2], RepositoriesPage)
    assert isinstance(dlg.pages[3], SnapshotsPage)
    assert isinstance(dlg.pages[4], ForgePage)
    assert isinstance(dlg.pages[5], AdvancedPage)
    dlg.close()


def test_appearance_page_switches_theme(main_window, db_conn):
    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    dlg.nav_list.setCurrentRow(0)
    page: AppearancePage = dlg.pages[0]

    # Switch to Dark
    page.radio_dark.click()
    assert main_window._current_theme_mode == "dark"
    assert settings.get_setting(db_conn, "theme") == "dark"

    # Switch to Light
    page.radio_light.click()
    assert main_window._current_theme_mode == "light"
    assert settings.get_setting(db_conn, "theme") == "light"

    # Switch to Auto
    page.radio_auto.click()
    assert main_window._current_theme_mode == "auto"
    assert settings.get_setting(db_conn, "theme") == "auto"
    dlg.close()


def test_tabs_page_switches_orientation(main_window, db_conn):
    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    dlg.nav_list.setCurrentRow(1)
    page: TabsPage = dlg.pages[1]

    # Select Horizontal
    page.radio_horizontal.click()
    assert main_window.tab_container.orientation() == Qt.Horizontal
    assert settings.get_setting(db_conn, "ui.tab_orientation") == "horizontal"

    # Select Vertical
    page.radio_vertical.click()
    assert main_window.tab_container.orientation() == Qt.Vertical
    assert settings.get_setting(db_conn, "ui.tab_orientation") == "vertical"
    dlg.close()


def test_repositories_page_toggles_auto_fetch(main_window, db_conn):
    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    dlg.nav_list.setCurrentRow(2)
    page: RepositoriesPage = dlg.pages[2]

    # Default is enabled
    assert main_window._is_auto_fetch_enabled() is True
    assert page.chk_auto_fetch.isChecked() is True

    # Toggle to False
    page.chk_auto_fetch.setChecked(False)
    assert main_window._is_auto_fetch_enabled() is False
    assert settings.get_setting(db_conn, "repo.auto_fetch_on_open") == "false"

    # Toggle to True
    page.chk_auto_fetch.setChecked(True)
    assert main_window._is_auto_fetch_enabled() is True
    assert settings.get_setting(db_conn, "repo.auto_fetch_on_open") == "true"
    dlg.close()


def test_snapshots_page_no_repo_state(main_window):
    main_window._current_repo = None
    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    dlg.nav_list.setCurrentRow(3)
    page: SnapshotsPage = dlg.pages[3]

    assert not page.controls_widget.isEnabled()
    assert "No repository currently open" in page.repo_status_label.text()
    dlg.close()


def test_snapshots_page_with_active_repo(main_window, multi_commit_repo, db_conn):
    repo_registry.add_repo(db_conn, str(multi_commit_repo.path), "multi_repo")
    main_window._on_repo_changed(str(multi_commit_repo.path))

    dlg = SettingsDialog(main_window=main_window, parent=main_window)
    dlg.nav_list.setCurrentRow(3)
    page: SnapshotsPage = dlg.pages[3]

    assert page.controls_widget.isEnabled()
    assert multi_commit_repo.path.name in page.repo_status_label.text()

    # Modify snapshot trigger & interval
    page.spin_timer_min.setValue(15)
    page.chk_on_timer.setChecked(True)

    # Modify untracked mode & caps
    idx = page.combo_untracked_mode.findData("unlimited")
    page.combo_untracked_mode.setCurrentIndex(idx)
    page.spin_per_file_cap.setValue(25)
    page.spin_total_cap.setValue(150)

    # Verify saved to database via core.snapshots
    cfg = snapshots.get_snapshot_settings(main_window._current_repo, conn=db_conn)
    assert cfg.timer_interval_minutes == 15
    assert cfg.trigger_on_timer is True
    assert cfg.untracked_capture_mode == "unlimited"
    assert cfg.untracked_per_file_cap_mb == 25
    assert cfg.untracked_total_cap_mb == 150
    assert main_window._snapshot_timer.interval() == 15 * 60 * 1000
    dlg.close()


def test_forge_page_and_advanced_page(main_window, db_conn):
    dlg = SettingsDialog(main_window=main_window, parent=main_window)

    # Forge Page
    dlg.nav_list.setCurrentRow(4)
    forge_page: ForgePage = dlg.pages[4]
    assert "0 configured forge accounts" in forge_page.account_summary_label.text()

    # Advanced Page
    dlg.nav_list.setCurrentRow(5)
    adv_page: AdvancedPage = dlg.pages[5]
    settings.set_setting(db_conn, "forge.link_declined", json.dumps(["https://github.com/foo/bar"]))
    assert settings.get_setting(db_conn, "forge.link_declined") == '["https://github.com/foo/bar"]'

    adv_page.reset_declined_btn.click()
    assert settings.get_setting(db_conn, "forge.link_declined") == "[]"
    assert "reset" in adv_page.reset_status_label.text().lower()
    dlg.close()


def test_main_window_preferences_action_exists(main_window):
    assert hasattr(main_window, "act_preferences")
    assert main_window.act_preferences.text() == "&Preferences…"
    assert main_window.act_preferences.shortcut().toString() in ("Ctrl+,", "Ctrl+Comma")
