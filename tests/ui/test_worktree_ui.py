"""UI tests for Git Worktrees & Workspace Sessions (VP-3)."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from wrench.core import engine
from wrench.storage import session_storage
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry
from wrench.ui.dialogs.add_worktree_dialog import AddWorktreeDialog
from wrench.ui.main_window import MainWindow
from wrench.ui.widgets.worktree_panel import WorktreePanel
from wrench.ui.workers import wait_for_active_workers


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Tester")
    _git(path, "config", "user.email", "tester@test.com")
    (path / "README.md").write_text("hello\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "init")
    return path


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


def test_add_worktree_dialog_preview_and_validation(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "wt-ui-repo")
    settings_reg = SettingsRegistry()

    dialog = AddWorktreeDialog(engine, settings_reg, str(repo_dir))
    try:
        assert dialog.windowTitle() == "Add Linked Worktree"
        assert dialog.combo_branch.count() >= 1

        # Check default destination path
        initial_dest = dialog.edit_path.text()
        assert initial_dest

        # Change branch name and verify preview updates
        dialog.combo_branch.setEditText("feature-ui-testing")
        dialog._update_path_preview()
        new_dest = dialog.edit_path.text()
        assert "feature-ui-testing" in new_dest

        # CLI preview bar should reflect the git worktree add command
        preview_cmd = dialog.cli_preview.preview_text
        assert "worktree add" in preview_cmd
        assert "feature-ui-testing" in preview_cmd
    finally:
        dialog.close()


def test_worktree_panel_population_and_actions(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "panel-repo")
    wt_path = tmp_path / "linked-wt"
    engine.add_worktree(repo_dir, wt_path, branch="feature-panel", create_branch=True)

    settings_reg = SettingsRegistry()
    panel = WorktreePanel(engine, settings_reg)
    try:
        panel.set_repo_path(str(repo_dir))
        wait_for_active_workers(timeout=2.0)
        QApplication.processEvents()
        tree = panel.tree

        # 2 worktrees: main and linked
        assert tree.topLevelItemCount() == 2

        main_item = tree.topLevelItem(0)
        assert "main" in main_item.text(0)
        assert "[Main]" in main_item.text(0)

        linked_item = tree.topLevelItem(1)
        assert "feature-panel" in linked_item.text(0)

        # Settings button jump
        with patch.object(panel, "_on_settings_clicked") as mock_settings:
            panel.btn_settings.click()
            mock_settings.assert_called_once()
    finally:
        panel.close()


def test_main_window_worktree_and_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "mw_test.db"
    conn = sqlite3.connect(str(db_path))
    run_migrations(conn)

    repo_dir = _init_repo(tmp_path / "mw-repo")

    mw = MainWindow(conn=conn)
    try:
        assert hasattr(mw, "worktree_panel")
        assert hasattr(mw, "menu_workspace_sessions")
        assert hasattr(mw, "act_worktrees")

        # Test workspace sessions menu population when empty
        mw._populate_workspace_sessions_menu()
        actions = mw.menu_workspace_sessions.actions()
        assert any("(No saved sessions)" in a.text() for a in actions)

        # Save a session
        session_storage.save_session(conn, "Sprint 1", [str(repo_dir)], 0)

        # Menu population with saved session
        mw._populate_workspace_sessions_menu()
        submenus = [a.menu() for a in mw.menu_workspace_sessions.actions() if a.menu()]
        assert any(m.title() == "Sprint 1" for m in submenus)

        # Test restore
        mw._on_restore_workspace_session("Sprint 1")
        assert "Sprint 1" in mw.status_label.text()
    finally:
        mw.close()
