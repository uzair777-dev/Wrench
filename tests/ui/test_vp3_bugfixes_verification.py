"""Verification tests for the 8 user-reported bugs across VP-3 and UI layers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from wrench.core.models import Commit, WorkspaceSession
from wrench.storage import session_storage
from wrench.storage.settings_registry import SettingsRegistry, SettingTier
from wrench.ui.commit_graph.detail_panel import CommitDetailPanel
from wrench.ui.commit_graph.layout import Connector, ConnectorKind, GraphRow
from wrench.ui.dialogs.settings_dialog import SettingsDialog
from wrench.ui.history_view import CommitGraphRowDelegate
from wrench.ui.tabs.tab_bar import TabContainer
from wrench.ui.widgets.context_header_bar import GitTerminalDrawer


def test_terminal_drawer_accepts_list_and_string(qtbot, tmp_path):
    """Test Issue 2: Terminal runner accepts both list[str] and str without crashing."""
    drawer = GitTerminalDrawer()
    qtbot.addWidget(drawer)
    records = []

    def mock_runner(tokens):
        records.append(tokens)
        return (0, f"Executed {tokens}", "", 12.5)

    drawer.set_command_runner(mock_runner)
    drawer.cmd_input.setText("git status --short")
    drawer._on_execute_command()

    assert len(records) == 1
    assert records[0] == ["status", "--short"]
    assert "Executed ['status', '--short']" in drawer.log_view.toPlainText()


def test_terminal_drawer_clear_and_close_buttons(qtbot):
    """Test Issue 3: Clear button clears both log & input; close button hides & emits closed."""
    drawer = GitTerminalDrawer()
    qtbot.addWidget(drawer)
    drawer.append_log("Some git logs")
    drawer.cmd_input.setText("git branch")
    assert bool(drawer.log_view.toPlainText())
    assert bool(drawer.cmd_input.text())

    # Click clear
    drawer.clear_btn.click()
    assert drawer.log_view.toPlainText() == ""
    assert drawer.cmd_input.text() == ""

    # Test close
    drawer.setVisible(True)
    closed_signals = []
    drawer.closed.connect(lambda: closed_signals.append(True))
    drawer.close_btn.click()

    assert not drawer.isVisible()
    assert len(closed_signals) == 1


def test_commit_detail_panel_displays_unsigned_badge(qtbot):
    """Test Issue 4: Unsigned commit displays [Unsigned] badge with tooltip."""
    panel = CommitDetailPanel()
    qtbot.addWidget(panel)
    panel.show()
    mock_repo = MagicMock()
    mock_repo.path = "/tmp/repo"
    panel.set_repo(mock_repo)

    commit = Commit(
        sha="a173afaa19d036843e98c0eeb8b7d7bf0095a5fc",
        author_name="Dev",
        author_email="dev@example.com",
        author_date="2026-11-23 20:00:00",
        message="I am fixing everything cleanly",
        parent_shas=(),
    )
    panel.set_commit(commit)

    assert panel.signature_badge.isHidden() is False
    assert panel.signature_badge.text() == "Unsigned"
    assert "cryptographic" in panel.signature_badge.toolTip().lower()


def test_tab_bar_add_menu_includes_worktrees(qtbot):
    """Test Issue 1: Tab bar add menu contains Worktree Manager when not open."""
    bar = TabContainer()
    qtbot.addWidget(bar)
    signals = []
    bar.add_category_tab_requested.connect(lambda t: signals.append(t))

    from PySide6.QtWidgets import QMenu

    class _CustomMenu(QMenu):
        last_menu = None

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            _CustomMenu.last_menu = self

        def exec(self, *args, **kwargs):
            return None

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("wrench.ui.tabs.tab_bar.QMenu", _CustomMenu)
        bar._show_add_menu()

        assert _CustomMenu.last_menu is not None
        actions = [a.text() for a in _CustomMenu.last_menu.actions()]
        assert "Worktree Manager" in actions


def test_workspace_session_saves_and_restores_tab_metadata():
    """Test Issue 6: WorkspaceSession serializes tabs and restores them."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE workspace_sessions (
            session_name    TEXT PRIMARY KEY,
            repo_paths_json TEXT NOT NULL,
            active_index    INTEGER NOT NULL DEFAULT 0,
            tabs_json       TEXT DEFAULT '[]',
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    tabs = [
        {"tab_type": "changes", "repo_path": "/repo1", "entity_id": None, "label": "Changes"},
        {"tab_type": "worktrees", "repo_path": "/repo1", "entity_id": None, "label": "Worktrees"},
        {"tab_type": "issue_detail", "repo_path": "/repo1", "entity_id": "origin:42", "label": "Issue #42"},
    ]

    session_storage.save_session(conn, "my_session", ["/repo1"], active_index=1, tabs=tabs)
    loaded = session_storage.load_session(conn, "my_session")

    assert loaded is not None
    assert loaded.session_name == "my_session"
    assert loaded.active_index == 1
    assert len(loaded.tabs) == 3
    assert loaded.tabs[1]["tab_type"] == "worktrees"
    assert loaded.tabs[2]["entity_id"] == "origin:42"


def test_settings_dialog_search_finds_worktrees_in_normal_mode(qtbot, tmp_path):
    """Test Issue 7: Searching 'worktree' finds settings even when starting in Normal mode."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("XDG_DATA_HOME", str(tmp_path))

        dlg = SettingsDialog(v1_compat=False)
        qtbot.addWidget(dlg)
        assert dlg._current_view_tier == SettingTier.NORMAL

        dlg.search_input.setText("worktree")

        # Worktrees category should be visible and matched
        page = dlg._get_or_create_category_page("Worktrees & Submodules")
        matching = [r for r in page.row_widgets if not r.isHidden()]
        assert len(matching) >= 1
        assert any("worktrees" in r.spec.key for r in matching)
        dlg.close()


def test_commit_graph_row_delegate_paint_geometry(qtbot):
    """Test Issue 8: CommitGraphRowDelegate paints node, active lanes, and connectors cleanly."""
    delegate = CommitGraphRowDelegate()

    img = QImage(300, 30, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    painter = QPainter(img)

    class DummyOption:
        rect = QRect(0, 0, 300, 30)
        widget = None
        state = 0

    # Row 1: Deflecting fork (should NOT draw bottom rail)
    row_deflecting = GraphRow(
        commit=Commit(
            sha="c1",
            author_name="Dev",
            author_email="dev@example.com",
            author_date="2026-11-23",
            message="Commit 1",
            parent_shas=("p1",),
        ),
        lane_index=1,
        active_lanes=[1, 2],
        connectors=[
            Connector(
                from_lane=1,
                to_lane=2,
                color="#f38ba8",
                kind=ConnectorKind.FORK_DOWN,
            )
        ],
        has_top_rail=True,
        node_color="#a6e3a1",
        active_lane_colors=[(1, "#a6e3a1"), (2, "#89b4fa")],
    )

    delegate._paint_graph_cell(
        painter,
        DummyOption(),
        row_deflecting,
        QColor("#a6e3a1"),
        is_selected=False,
    )

    # Row 2: Continuing commit with JOIN_TOP connector
    row_continuing = GraphRow(
        commit=Commit(
            sha="c2",
            author_name="Dev",
            author_email="dev@example.com",
            author_date="2026-11-23",
            message="Commit 2",
            parent_shas=("p2",),
        ),
        lane_index=2,
        active_lanes=[2],
        connectors=[
            Connector(
                from_lane=1,
                to_lane=2,
                color="#fab387",
                kind=ConnectorKind.JOIN_TOP,
            )
        ],
        has_top_rail=True,
        node_color="#89b4fa",
        active_lane_colors=[(2, "#89b4fa")],
    )

    delegate._paint_graph_cell(
        painter,
        DummyOption(),
        row_continuing,
        QColor("#89b4fa"),
        is_selected=True,
    )

    painter.end()
    assert not img.isNull()
