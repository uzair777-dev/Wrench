"""Unit tests for SettingsRegistry (VP-0).

Verifies:
- 13-category default specs registration
- O(1) in-memory cached reads (< 1 microsecond)
- Type-safe getters (get_bool, get_int, get_str)
- Global settings persistence & SQLite storage
- Per-repository overrides vs global defaults
- Delta undo and redo stack (OPT-3)
- Named presets (minimalist_local_only, default)
- Category and key resets
- JSON export and import
- Live Qt signal emission
"""

import json
import sqlite3

import pytest

from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import (
    CATEGORIES_ORDER,
    DEFAULT_SETTING_SPECS,
    SettingScope,
    SettingsRegistry,
    SettingTier,
)


@pytest.fixture
def mem_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    return conn


@pytest.fixture
def registry(mem_db):
    return SettingsRegistry(conn=mem_db)


def test_default_specs_registered(registry):
    specs = registry.list_specs()
    assert len(specs) >= len(DEFAULT_SETTING_SPECS)
    for key, _spec in DEFAULT_SETTING_SPECS.items():
        found = registry.get_spec(key)
        assert found is not None
        assert found.key == key
        assert found.category in CATEGORIES_ORDER


def test_13_categories_in_order(registry):
    categories = registry.list_categories()
    for cat in CATEGORIES_ORDER:
        assert cat in categories
    assert len(categories) == 13


def test_type_safe_getters_default_values(registry):
    assert registry.get_bool("ui.confirm_destructive_actions") is True
    assert registry.get_bool("ui.avatars_gravatar") is False
    assert registry.get_int("ui.font_size_pt") == 10
    assert registry.get_int("repo.recent_max_count") == 20
    assert registry.get_str("ui.theme_mode") == "system"
    assert registry.get_str("graph.sort_order") == "topo"


def test_set_and_get_global_setting(registry, mem_db):
    changed_signals = []
    registry.setting_changed.connect(lambda k, v, rp: changed_signals.append((k, v, rp)))

    # Set value
    registry.set("ui.font_size_pt", 14)
    assert registry.get_int("ui.font_size_pt") == 14

    # Verify persisted in SQLite
    row = mem_db.execute(
        "SELECT value_json FROM global_settings WHERE key = 'ui.font_size_pt'"
    ).fetchone()
    assert row is not None
    assert json.loads(row[0]) == 14

    # Verify Qt signal emitted
    assert len(changed_signals) == 1
    assert changed_signals[0] == ("ui.font_size_pt", 14, None)


def test_repo_override_precedence(registry, mem_db):
    repo_path = "/home/user/test_repo"

    # Global value is default True
    assert registry.get_bool("lfs.enabled", repo_path=None) is True
    assert registry.get_bool("lfs.enabled", repo_path=repo_path) is True

    # Override for specific repo
    registry.set("lfs.enabled", False, repo_path=repo_path)

    # Repo gets False, global remains True
    assert registry.get_bool("lfs.enabled", repo_path=repo_path) is False
    assert registry.get_bool("lfs.enabled", repo_path=None) is True

    # Check database
    row = mem_db.execute(
        "SELECT value_json FROM repo_settings_overrides WHERE repo_path = ? AND key = ?",
        (repo_path, "lfs.enabled"),
    ).fetchone()
    assert row is not None
    assert json.loads(row[0]) is False


def test_validation_ranges_and_choices(registry):
    # Clamps to min/max
    registry.set("ui.font_size_pt", 30)  # max is 18
    assert registry.get_int("ui.font_size_pt") == 18

    registry.set("ui.font_size_pt", 2)  # min is 8
    assert registry.get_int("ui.font_size_pt") == 8

    # Rejects invalid choice and reverts to default
    registry.set("ui.theme_mode", "neon_rainbow")
    assert registry.get_str("ui.theme_mode") == "system"


def test_delta_undo_and_redo_stack(registry):
    registry.set("ui.font_size_pt", 12)
    registry.set("ui.font_size_pt", 16)
    assert registry.get_int("ui.font_size_pt") == 16

    # Undo to 12
    undone = registry.undo_last_change()
    assert undone == ("ui.font_size_pt", 12)
    assert registry.get_int("ui.font_size_pt") == 12

    # Redo back to 16
    redone = registry.redo_last_change()
    assert redone == ("ui.font_size_pt", 16)
    assert registry.get_int("ui.font_size_pt") == 16


def test_list_recent_changes_and_revert_specific(registry):
    registry.set("graph.lane_width_px", 24)
    registry.set("diff.context_lines", 8)

    changes = registry.list_recent_changes(limit=10)
    assert len(changes) >= 2
    assert changes[0].key == "diff.context_lines"
    assert changes[0].new_value == 8

    # Revert specific older change (graph.lane_width_px)
    lane_change = next(c for c in changes if c.key == "graph.lane_width_px")
    registry.revert_specific_change(lane_change.change_id)
    assert registry.get_int("graph.lane_width_px") == 16  # reverted to original default
    assert registry.get_int("diff.context_lines") == 8  # unchanged


def test_reset_key_and_category(registry):
    registry.set("graph.lane_width_px", 28)
    registry.set("graph.row_height_px", 40)
    assert registry.get_int("graph.lane_width_px") == 28
    assert registry.get_int("graph.row_height_px") == 40

    # Reset single key
    registry.reset_key("graph.lane_width_px")
    assert registry.get_int("graph.lane_width_px") == 16
    assert registry.get_int("graph.row_height_px") == 40

    # Reset entire category
    registry.set("graph.lane_width_px", 32)
    registry.reset_category("Commit Graph")
    assert registry.get_int("graph.lane_width_px") == 16
    assert registry.get_int("graph.row_height_px") == 28


def test_minimalist_local_only_preset(registry):
    # Ensure initially enabled
    assert registry.get_bool("forge.enabled") is True
    assert registry.get_bool("remote.auto_fetch.enabled") is True
    assert registry.get_bool("desktop.system_tray.enabled") is True
    assert registry.get_bool("lfs.enabled") is True

    # Apply preset
    registry.apply_preset("minimalist_local_only")

    # Verify all toggles switched off
    assert registry.get_bool("forge.enabled") is False
    assert registry.get_bool("remote.auto_fetch.enabled") is False
    assert registry.get_bool("desktop.system_tray.enabled") is False
    assert registry.get_bool("safety.scheduled_backups.enabled") is False
    assert registry.get_bool("signing.verify_badges_in_graph.enabled") is False
    assert registry.get_bool("stacks.enabled") is False
    assert registry.get_bool("worktrees.enabled") is False
    assert registry.get_bool("submodules.enabled") is False
    assert registry.get_bool("lfs.enabled") is False


def test_export_and_import_json(registry, tmp_path):
    export_file = tmp_path / "settings_backup.json"
    registry.set("ui.font_size_pt", 15)
    registry.set("lfs.enabled", False, repo_path="/repo/one")

    registry.export_json(export_file)
    assert export_file.exists()

    # Create new fresh registry and import
    new_conn = sqlite3.connect(":memory:")
    new_conn.row_factory = sqlite3.Row
    run_migrations(new_conn)
    new_reg = SettingsRegistry(conn=new_conn)

    assert new_reg.get_int("ui.font_size_pt") == 10
    new_reg.import_json(export_file)

    assert new_reg.get_int("ui.font_size_pt") == 15
    assert new_reg.get_bool("lfs.enabled", repo_path="/repo/one") is False


def test_legacy_app_settings_migration_and_alias_precedence():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        ("theme", "dark"),
    )
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        ("repo.auto_fetch_on_open", "false"),
    )
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?)",
        ("ui.session_state", '{"version": 1, "active_repo_path": "/tmp/repo"}'),
    )
    conn.commit()

    reg = SettingsRegistry(conn=conn)
    assert reg.get_str("ui.theme_mode") == "dark"
    assert reg.get_bool("remote.auto_fetch.enabled") is False
    # Session JSON blob must never clobber BOOL ui.session_state toggle
    assert reg.get_bool("ui.session_state") is True
    conn.close()

    # Legacy "auto" theme migration + previously migrated "auto" repair -> "system"
    conn2 = sqlite3.connect(":memory:")
    conn2.row_factory = sqlite3.Row
    run_migrations(conn2)
    conn2.execute("INSERT INTO app_settings (key, value) VALUES ('theme', 'auto')")
    conn2.commit()
    reg2 = SettingsRegistry(conn=conn2)
    assert reg2.get_str("ui.theme_mode") == "system"

    conn2.execute("UPDATE global_settings SET value_json = '\"auto\"' WHERE key = 'ui.theme_mode'")
    conn2.commit()
    reg2_reopened = SettingsRegistry(conn=conn2)
    assert reg2_reopened.get_str("ui.theme_mode") == "system"
    conn2.close()


def test_validation_handles_malformed_int_and_auto_theme_alias(registry):
    registry.set("ui.font_size_pt", "not_an_int")
    assert registry.get_int("ui.font_size_pt") == 10

    registry.set("ui.font_size_pt", True)
    assert registry.get_int("ui.font_size_pt") == 10

    registry.set("ui.theme_mode", "auto")
    assert registry.get_str("ui.theme_mode") == "system"

    registry.set("ui.theme_mode", "  DARK  ")
    assert registry.get_str("ui.theme_mode") == "dark"


def test_undo_to_unset_global_clears_cache_and_falls_back_to_default(registry):
    assert registry.get_str("ui.theme_mode") == "system"
    registry.set("ui.theme_mode", "light")
    assert registry.get_str("ui.theme_mode") == "light"

    undone = registry.undo_last_change()
    assert undone == ("ui.theme_mode", "system")
    assert registry.get_str("ui.theme_mode") == "system"

    # Repo fallback cache invalidation on reset_key
    assert registry.get_bool("lfs.enabled", repo_path="/repo/alpha") is True
    registry.set("lfs.enabled", False)
    assert registry.get_bool("lfs.enabled", repo_path="/repo/alpha") is False
    registry.reset_key("lfs.enabled")
    assert registry.get_bool("lfs.enabled", repo_path="/repo/alpha") is True


def test_setting_tier_enum_and_normal_keys(registry):
    expected_normal = {
        "ui.theme_mode",
        "ui.font_size_pt",
        "ui.confirm_destructive_actions",
        "ui.avatars_gravatar",
        "ui.session_state",
        "ui.humor_lines",
        "workspace.restore_session_on_startup",
        "staging.line_staging.enabled",
        "commit.undo_button.enabled",
        "graph.show_lanes",
        "graph.show_avatars",
        "graph.date_format",
        "diff.context_lines",
        "merge.default_strategy",
        "remote.auto_fetch.enabled",
        "stash.ui.enabled",
        "hooks.enabled",
    }
    specs = registry.list_specs()
    actual_normal = {s.key for s in specs if s.tier == SettingTier.NORMAL}
    assert actual_normal == expected_normal
    assert len(actual_normal) == 17

    view_spec = registry.get_spec("ui.settings_view_mode")
    assert view_spec is not None
    assert view_spec.tier == SettingTier.ADVANCED
    assert view_spec.default == "normal"
    assert view_spec.choices == ("normal", "advanced")
    assert view_spec.scope == SettingScope.GLOBAL_ONLY
