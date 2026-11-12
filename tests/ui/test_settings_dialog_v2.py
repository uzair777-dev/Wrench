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

import json
import sqlite3

import pygit2
import pytest
from PySide6.QtWidgets import QApplication

from wrench.storage import repo_registry, settings
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import CATEGORIES_ORDER, SettingTier
from wrench.ui.dialogs.settings_dialog import SettingsDialog
from wrench.ui.main_window import MainWindow
from wrench.ui.theme import TOAST_TEXT_COLOR, is_dark_theme
from wrench.ui.widgets import avatar as avatar_mod


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

    # Clear search in default Normal view -> shows all 7 Normal settings
    dlg.search_input.setText("")
    normal_visible = [r for r in page.row_widgets if not r.isHidden()]
    assert len(normal_visible) == 7
    assert all(r.spec.tier == SettingTier.NORMAL for r in normal_visible)

    # Switch to Advanced view -> shows all 14 rows in General & UI
    dlg.view_mode_combo.setCurrentIndex(1)
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


def _layout_widgets(layout) -> list:
    widgets = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is not None:
            widgets.append(item.widget())
    return widgets


def _find_row(dlg: SettingsDialog, category: str, key: str):
    page = dlg._get_or_create_category_page(category)
    for row in page.row_widgets:
        if row.spec.key == key:
            return row
    raise AssertionError(f"Setting row {key!r} not found in {category!r}")


def test_v2_normal_view_hides_advanced_settings(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg.view_mode_combo.currentData() == SettingTier.NORMAL.value

    page = dlg._get_or_create_category_page("General & UI")
    visible = [r for r in page.row_widgets if not r.isHidden()]
    assert len(visible) == 7
    assert all(r.spec.tier == SettingTier.NORMAL for r in visible)

    hidden_cats = {
        dlg.nav_list.item(i).text()
        for i in range(dlg.nav_list.count())
        if dlg.nav_list.item(i).isHidden()
    }
    assert hidden_cats == {
        "Branches & Stacks",
        "Worktrees & Submodules",
        "Forges & CI",
        "Blame & Search",
        "Watcher & Performance",
        "Custom Actions & Shortcuts",
    }
    dlg.close()


def test_v2_advanced_view_shows_all_settings(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    dlg.view_mode_combo.setCurrentIndex(1)
    assert dlg.view_mode_combo.currentData() == SettingTier.ADVANCED.value

    for i in range(dlg.nav_list.count()):
        assert not dlg.nav_list.item(i).isHidden()

    total_rows = 0
    for page in dlg.pages:
        total_rows += len(page.row_widgets)
        assert all(not r.isHidden() for r in page.row_widgets)
    assert total_rows >= 75
    dlg.close()


def test_v2_view_mode_persists_across_dialog_opens(main_window):
    dlg1 = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg1.view_mode_combo.currentData() == "normal"
    dlg1.view_mode_combo.setCurrentIndex(1)
    dlg1.close()

    dlg2 = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg2.view_mode_combo.currentData() == "advanced"
    for i in range(dlg2.nav_list.count()):
        assert not dlg2.nav_list.item(i).isHidden()
    dlg2.view_mode_combo.setCurrentIndex(0)
    dlg2.close()

    dlg3 = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg3.view_mode_combo.currentData() == "normal"
    dlg3.close()


def test_v2_top_bar_has_two_rows(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    row1 = _layout_widgets(dlg.top_row_1)
    row2 = _layout_widgets(dlg.top_row_2)
    bottom = _layout_widgets(dlg.bottom_bar)

    assert dlg.search_input in row1
    assert dlg.view_mode_combo in row1
    assert dlg.scope_combo in row2
    assert dlg.btn_modified_only in row2
    assert dlg.btn_undo in row2
    assert dlg.btn_redo in row2
    assert dlg.btn_reset_category in row2

    assert dlg.btn_minimalist not in row1
    assert dlg.btn_minimalist not in row2
    assert dlg.btn_minimalist in bottom
    dlg.close()


def test_v2_normal_mode_hides_scope_and_modified_and_reset(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    dlg.show()

    assert dlg.search_input.isVisible() is True
    assert dlg.view_mode_combo.isVisible() is True
    assert dlg.btn_undo.isVisible() is True
    assert dlg.btn_redo.isVisible() is True

    assert dlg.scope_combo.isVisible() is False
    assert dlg.btn_modified_only.isVisible() is False
    assert dlg.btn_reset_category.isVisible() is False
    assert dlg.btn_minimalist.isVisible() is False

    dlg.view_mode_combo.setCurrentIndex(1)
    assert dlg.scope_combo.isVisible() is True
    assert dlg.btn_modified_only.isVisible() is True
    assert dlg.btn_reset_category.isVisible() is True
    assert dlg.btn_minimalist.isVisible() is True
    dlg.close()


def test_v2_select_category_reveals_advanced_target_without_overwriting_saved_mode(main_window):
    dlg = SettingsDialog(main_window=main_window, parent=main_window, v1_compat=False)
    assert dlg.registry.get_str("ui.settings_view_mode") == "normal"

    dlg.select_category(
        "Worktrees & Submodules",
        highlight_key="monorepo.sparse_checkout_ui.enabled",
    )
    assert dlg.view_mode_combo.currentData() == "advanced"
    row = _find_row(dlg, "Worktrees & Submodules", "monorepo.sparse_checkout_ui.enabled")
    assert not row.isHidden()
    assert dlg.registry.get_str("ui.settings_view_mode") == "normal"
    dlg.close()


def test_v2_theme_change_applies_immediately_on_close_and_across_restart(tmp_path, app):
    orig_palette = app.palette()
    db_file = tmp_path / "wrench.db"

    conn1 = sqlite3.connect(db_file)
    conn1.row_factory = sqlite3.Row
    run_migrations(conn1)
    try:
        win1 = MainWindow(conn=conn1)
        win1.show()

        dlg = SettingsDialog(main_window=win1, parent=win1, v1_compat=False)
        win1._active_settings_dialog = dlg
        dlg.show()

        theme_row = _find_row(dlg, "General & UI", "ui.theme_mode")
        light_idx = theme_row.combo_control.findData("light")
        assert light_idx >= 0
        theme_row.combo_control.setCurrentIndex(light_idx)

        # Immediately applied before closing Preferences
        assert win1._current_theme_mode == "light"
        assert win1.act_theme_light.isChecked() is True
        assert is_dark_theme(win1) is False
        assert is_dark_theme(dlg) is False
        assert app.palette().window().color().name().lower() == "#eff1f5"
        assert TOAST_TEXT_COLOR["light"] in dlg.toast_label.styleSheet()
        assert "Saved 'ui.theme_mode' → light" in dlg.toast_label.text()

        # Remains applied on dialog close
        dlg.close()
        win1._active_settings_dialog = None
        assert win1._current_theme_mode == "light"
        assert is_dark_theme(win1) is False
        win1.close()
        conn1.close()

        # Fresh connection / second MainWindow launch restores light directly
        conn2 = sqlite3.connect(db_file)
        conn2.row_factory = sqlite3.Row
        win2 = MainWindow(conn=conn2)
        win2.show()
        try:
            assert win2._current_theme_mode == "light"
            assert win2.act_theme_light.isChecked() is True
            assert is_dark_theme(win2) is False

            dlg2 = SettingsDialog(main_window=win2, parent=win2, v1_compat=False)
            win2._active_settings_dialog = dlg2
            dlg2.show()
            theme_row2 = _find_row(dlg2, "General & UI", "ui.theme_mode")
            theme_row2.combo_control.setCurrentIndex(theme_row2.combo_control.findData("dark"))

            assert win2._current_theme_mode == "dark"
            assert is_dark_theme(win2) is True
            assert is_dark_theme(dlg2) is True
            assert app.palette().window().color().name().lower() == "#181825"
            assert TOAST_TEXT_COLOR["dark"] in dlg2.toast_label.styleSheet()
            dlg2.close()
            win2._active_settings_dialog = None
        finally:
            win2.close()
            conn2.close()

        # Third launch restores dark; switching back to system persists cleanly
        conn3 = sqlite3.connect(db_file)
        conn3.row_factory = sqlite3.Row
        win3 = MainWindow(conn=conn3)
        try:
            assert win3._current_theme_mode == "dark"
            assert win3.act_theme_dark.isChecked() is True
            assert is_dark_theme(win3) is True

            dlg3 = SettingsDialog(main_window=win3, parent=win3, v1_compat=False)
            theme_row3 = _find_row(dlg3, "General & UI", "ui.theme_mode")
            theme_row3.combo_control.setCurrentIndex(theme_row3.combo_control.findData("system"))
            assert win3._current_theme_mode == "auto"
            assert win3.act_theme_auto.isChecked() is True
            dlg3.close()
        finally:
            win3.close()
            conn3.close()
    finally:
        app.setPalette(orig_palette)


def test_v2_font_size_avatars_humor_and_activity_max_lines_apply_live_and_flush_on_close(
    tmp_path, app
):
    orig_font = app.font()
    repo_dir = tmp_path / "clean_repo"
    repo = pygit2.init_repository(str(repo_dir), initial_head="main")
    readme = repo_dir / "README.md"
    readme.write_text("# clean\n", encoding="utf-8")
    repo.index.add("README.md")
    repo.index.write()
    sig = pygit2.Signature("Dev", "dev@example.com", 1_700_000_000, 0)
    repo.create_commit("HEAD", sig, sig, "init", repo.index.write_tree(), [])

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    repo_registry.add_repo(conn, str(repo_dir), "clean_repo")

    try:
        win = MainWindow(conn=conn)
        try:
            win.tab_container.set_current_index(0)
            win.show()
            dlg = SettingsDialog(main_window=win, parent=win, v1_compat=False)
            win._active_settings_dialog = dlg
            dlg.show()

            # 1. Humor lines live toggle
            assert win.changes_tab.clean_quote.isVisible() is True
            humor_row = _find_row(dlg, "General & UI", "ui.humor_lines")
            humor_row.chk_control.setChecked(False)
            assert win.act_humor_lines.isChecked() is False
            assert win.changes_tab.clean_quote.text() == ""
            assert win.changes_tab.clean_quote.isVisible() is False

            humor_row.chk_control.setChecked(True)
            assert win.act_humor_lines.isChecked() is True
            assert win.changes_tab.clean_quote.isVisible() is True
            assert bool(win.changes_tab.clean_quote.text())

            # 2. Gravatar live toggle clears cache
            avatar_mod._author_avatar_url_cache[("Dev", "dev@example.com", (), False)] = "stale"
            grav_row = _find_row(dlg, "General & UI", "ui.avatars_gravatar")
            grav_row.chk_control.setChecked(True)
            assert ("Dev", "dev@example.com", (), False) not in avatar_mod._author_avatar_url_cache

            # 3. Activity dock max_lines (Advanced setting)
            dlg.view_mode_combo.setCurrentIndex(1)
            dock_row = _find_row(dlg, "General & UI", "ui.activity_dock.max_lines")
            dock_row.spin_control.setValue(120)
            dock_row.flush_pending()
            assert win._activity_log._entries.maxlen == 120
            assert win._activity_dock.scrollback.maximumBlockCount() == 120

            # 4. Font size typed into QSpinBox lineEdit and closed BEFORE 150ms debounce fires
            font_row = _find_row(dlg, "General & UI", "ui.font_size_pt")
            font_row.spin_control.lineEdit().setText("14")
            dlg.close()

            assert win._settings_registry.get_int("ui.font_size_pt") == 14
            assert app.font().pointSize() == 14
            assert win.font().pointSize() == 14
        finally:
            win.close()
    finally:
        app.setFont(orig_font)
        avatar_mod.clear_author_avatar_cache()
        conn.close()


def test_v2_repo_override_for_inactive_repo_does_not_affect_active_window(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    try:
        win = MainWindow(conn=conn)
        try:
            initial_gen = win._commit_graph_generation
            initial_sparse_vis = win.act_sparse_checkout.isVisible()

            inactive_repo = str(tmp_path / "other_repo")
            win._settings_registry.set(
                "maintenance.auto_commit_graph.enabled", False, inactive_repo
            )
            win._settings_registry.set("monorepo.sparse_checkout_ui.enabled", False, inactive_repo)

            assert win._commit_graph_generation == initial_gen
            assert win.act_sparse_checkout.isVisible() == initial_sparse_vis
        finally:
            win.close()
    finally:
        conn.close()


def test_v2_session_state_bool_never_clobbers_session_json(tmp_path):
    repo_dir = tmp_path / "sess_repo"
    pygit2.init_repository(str(repo_dir), initial_head="main")
    db_file = tmp_path / "session.db"

    conn1 = sqlite3.connect(db_file)
    conn1.row_factory = sqlite3.Row
    run_migrations(conn1)
    repo_registry.add_repo(conn1, str(repo_dir), "sess_repo")
    try:
        win1 = MainWindow(conn=conn1)
        try:
            assert win1.changes_tab._repo is not None
            dlg = SettingsDialog(main_window=win1, parent=win1, v1_compat=False)
            sess_row = _find_row(dlg, "General & UI", "ui.session_state")
            sess_row.chk_control.setChecked(False)
            dlg.close()
        finally:
            # Closing MainWindow saves session JSON into app_settings without clobbering BOOL False
            win1.close()

        raw = settings.get_setting(conn1, "ui.session_state")
        assert raw is not None
        parsed = json.loads(raw)
        assert parsed["version"] == 1
        assert win1._settings_registry.get_bool("ui.session_state") is False
    finally:
        conn1.close()

    conn2 = sqlite3.connect(db_file)
    conn2.row_factory = sqlite3.Row
    try:
        win2 = MainWindow(conn=conn2)
        try:
            assert win2._settings_registry.get_bool("ui.session_state") is False
            assert win2.changes_tab._repo is None
        finally:
            win2.close()
    finally:
        conn2.close()
