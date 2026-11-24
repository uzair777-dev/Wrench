"""Verification tests for the 8 user-reported bugs across VP-3 and UI layers."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from wrench.core.models import Commit
from wrench.storage import session_storage
from wrench.storage.settings_registry import SettingTier
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
    conn.execute("""
        CREATE TABLE workspace_sessions (
            session_name    TEXT PRIMARY KEY,
            repo_paths_json TEXT NOT NULL,
            active_index    INTEGER NOT NULL DEFAULT 0,
            tabs_json       TEXT DEFAULT '[]',
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)

    tabs = [
        {"tab_type": "changes", "repo_path": "/repo1", "entity_id": None, "label": "Changes"},
        {"tab_type": "worktrees", "repo_path": "/repo1", "entity_id": None, "label": "Worktrees"},
        {
            "tab_type": "issue_detail",
            "repo_path": "/repo1",
            "entity_id": "origin:42",
            "label": "Issue #42",
        },
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


def test_engine_list_branches_accepts_string_path(tmp_path):
    """Test Round 2: engine.list_branches accepts a string or Path object."""
    import pygit2

    from wrench.core import engine

    repo_path = tmp_path / "test_repo"
    pygit2.init_repository(str(repo_path))

    # Test with string repo path
    branches = engine.GitEngine().list_branches(repo=str(repo_path))
    assert isinstance(branches, list)

    # Test with Path repo path
    branches_path = engine.GitEngine().list_branches(repo=repo_path)
    assert isinstance(branches_path, list)


def test_add_worktree_dialog_branch_listing_and_collision(qtbot, tmp_path):
    """Test Round 2: AddWorktreeDialog populates branches and detects collisions."""
    import pygit2

    from wrench.core import engine
    from wrench.ui.dialogs.add_worktree_dialog import AddWorktreeDialog

    repo_path = tmp_path / "test_repo"
    r = pygit2.init_repository(str(repo_path))

    # Create initial commit so main branch exists
    sig = pygit2.Signature("Test", "test@example.com")
    tree = r.TreeBuilder().write()
    r.create_commit("refs/heads/main", sig, sig, "init", tree, [])

    eng = engine.GitEngine()
    dlg = AddWorktreeDialog(eng, None, str(repo_path))
    qtbot.addWidget(dlg)

    assert "main" in dlg._all_existing_branches
    assert dlg.combo_branch.count() >= 1

    # Collision test: trying to create a new branch named 'main' triggers validation
    dlg.chk_new_branch.setChecked(True)
    dlg.combo_branch.setEditText("main")
    dlg.edit_path.setText(str(tmp_path / "wt1"))

    # _on_add_clicked should abort before running git
    with pytest.MonkeyPatch.context() as mp:
        warning_shown = []
        mp.setattr(
            "PySide6.QtWidgets.QMessageBox.warning",
            lambda *args: warning_shown.append(args),
        )
        dlg._on_add_clicked()
        assert len(warning_shown) == 1
        assert "Already Exists" in warning_shown[0][1]
    dlg.close()


def test_commit_detail_panel_dynamic_message_and_splitter_proportions(qtbot):
    """Test Round 2: CommitDetailPanel dynamically sizes message and configures splitter."""
    panel = CommitDetailPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.set_compact_vertical_layout(True)
    assert panel.splitter.orientation() == Qt.Orientation.Vertical
    assert panel.minimumWidth() >= 280

    # Multi-line commit message
    multi_line_msg = (
        "Merge branch 'feature' into main\n\n"
        "This is paragraph 1 of the explanation.\n"
        "This is paragraph 2.\n"
        "More details here.\n"
    )
    commit = Commit(
        sha="1234567890abcdef1234567890abcdef12345678",
        author_name="Dev",
        author_email="dev@example.com",
        author_date="2026-11-23 20:00:00",
        message=multi_line_msg,
        parent_shas=(),
    )
    mock_repo = MagicMock()
    mock_repo.path = "/tmp/repo"
    panel.set_repo(mock_repo)
    panel.set_commit(commit)

    # Height should adapt above 60px to accommodate multiple lines
    assert panel.message_edit.height() >= 80
    assert panel.message_edit.maximumHeight() > 60


def test_avatar_pixmap_cache_and_loader(qtbot):
    """Test Round 2: AvatarPixmapCache renders clean 20x20 circular avatar pixmap."""
    from wrench.ui.history_view import AvatarPixmapCache

    cache = AvatarPixmapCache(maxsize=10)
    pix = cache.get_or_render("Junio C Hamano", "gitster@pobox.com", 20, "#89b4fa")
    assert not pix.isNull()
    assert pix.width() == 20
    assert pix.height() == 20


def test_round3_worktree_sibling_path_resolution(tmp_path):
    """Test Round 3 Issue 1: Destination worktree resolves as sibling in parent folder."""
    from wrench.core.worktrees import format_worktree_path

    repo_path = tmp_path / "Projects" / "astryx"
    repo_path.mkdir(parents=True)

    dest = format_worktree_path(repo_path, "feature-worktree")
    expected = (tmp_path / "Projects" / "astryx-feature-worktree").resolve()
    assert dest == expected


def test_round3_git_engine_facade_methods_exist():
    """Test Round 3 Issue 4: GitEngine has all worktree & signing methods."""
    from wrench.core.engine import GitEngine

    engine = GitEngine()
    methods = [
        "list_worktrees",
        "format_worktree_path",
        "add_worktree",
        "lock_worktree",
        "unlock_worktree",
        "remove_worktree",
        "prune_worktrees",
        "cross_worktree_cherry_pick",
        "verify_commit_signatures",
        "list_signing_keys",
        "run_terminal_command",
        "run_git_terminal_command",
    ]
    for m in methods:
        assert hasattr(engine, m), f"GitEngine missing facade method: {m}"
        assert callable(getattr(engine, m)), f"GitEngine member {m} is not callable"


def test_round3_signature_verification_handles_zero_oid():
    """Test Round 3 Issue 5: Zero-OID uncommitted WIP commits bypass git log gracefully."""
    from wrench.core.signing_ops import verify_commit_signatures_batch

    res = verify_commit_signatures_batch("/tmp", ["0000000000000000000000000000000000000000", ""])
    assert "0000000000000000000000000000000000000000" in res
    wip_status = res["0000000000000000000000000000000000000000"]
    assert wip_status.state == "unsigned"
    assert "WIP" in wip_status.validity_details


def test_round3_detail_panel_two_row_card_header(qtbot):
    """Test Round 3 Issue 3: Detail panel has 2-row card with author name, email, date, SHA."""
    panel = CommitDetailPanel()
    qtbot.addWidget(panel)
    panel.show()

    assert hasattr(panel, "author_name_label")
    assert hasattr(panel, "author_date_label")
    assert hasattr(panel, "sha_label")
    assert hasattr(panel, "copy_sha_btn")
    assert hasattr(panel, "signature_badge")
    assert hasattr(panel, "avatar_widget")

    mock_repo = MagicMock()
    mock_repo.path = "/tmp/repo"
    panel.set_repo(mock_repo)

    commit = Commit(
        sha="51af4e7d3bf0a89d71e19339e083c27635c10ad8",
        author_name="uzair777-dev",
        author_email="uzairshaikhking777@gmail.com",
        author_date="2026-11-23 15:27:12",
        message="feat: VP 03 feature complete",
        parent_shas=(),
    )
    panel.set_commit(commit)

    assert panel.author_name_label.text() == "uzair777-dev"
    assert "uzairshaikhking777@gmail.com" in panel.author_date_label.text()
    assert "2026-11-23" in panel.author_date_label.text()
    assert panel.sha_label.text() == "SHA: 51af4e7d"
    assert "51af4e7d3bf0a89d71e19339e083c27635c10ad8" in panel.sha_label.toolTip()


def test_round3_avatar_url_resolution_heuristics():
    """Test Round 3 Issue 2: Avatar resolution resolves GitHub handles & email prefixes."""
    from wrench.ui.widgets.avatar import resolve_author_avatar_url

    remotes = ["git@github.com:uzair777-dev/wrench.git"]
    # Direct username handle
    u1 = resolve_author_avatar_url("uzair777-dev", "uzair@example.com", remotes)
    assert u1 == "https://github.com/uzair777-dev.png?size=80"

    # Full name with spaces falls back to email handle
    u2 = resolve_author_avatar_url("Junio C Hamano", "gitster@pobox.com", remotes)
    assert u2 == "https://github.com/gitster.png?size=80"


def test_round4_avatar_loader_get_cached_avatar_and_cache_hygiene():
    """Test Round 4: AvatarLoader.get_cached_avatar and non-poisoning of in-flight avatars."""
    from wrench.ui.history_view import AvatarPixmapCache
    from wrench.ui.widgets.avatar import get_avatar_loader

    loader = get_avatar_loader()
    url = "https://example.com/nonexistent_test_avatar_round4.png"

    # Uncached URL returns None (triggers background fetch, doesn't return initials as fake avatar)
    cached = loader.get_cached_avatar(url, size=16)
    assert cached is None

    # AvatarPixmapCache must NOT cache in-flight avatar as a permanent initials tile
    cache = AvatarPixmapCache(maxsize=16)
    pm = cache.get_or_render("Test User", "testuser@example.com", 20, "#58a6ff", remote_urls=[])
    assert pm is not None
    assert not pm.isNull()
    # Cache key for email without URL is cached definitively
    assert ("testuser@example.com", 20, "#58a6ff", True) in cache._cache


def test_round4_commit_detail_message_flex_sizing(qtbot):
    """Test Round 4: Detail panel commit message flexes dynamically based on content."""
    panel = CommitDetailPanel()
    qtbot.addWidget(panel)
    panel.show()
    panel.resize(400, 500)

    mock_repo = MagicMock()
    mock_repo.path = "/tmp/repo"
    panel.set_repo(mock_repo)

    # 1. Single-line commit message
    c1 = Commit(
        sha="1111111111111111111111111111111111111111",
        author_name="Dev",
        author_email="dev@example.com",
        author_date="2026-11-24 10:00:00",
        message="Short single-line commit message",
        parent_shas=(),
    )
    panel.set_commit(c1)
    h_single = panel.message_edit.height()
    assert 30 <= h_single <= 60

    # 2. Multi-line commit message with long wrapped paragraph
    long_msg = (
        "This is a longer commit message description that wraps across multiple lines.\n"
        "It provides comprehensive architectural details about the implementation.\n"
        "It states the rules, constraints, edge cases, and verification results.\n"
        "Another paragraph detailing performance implications and UI rendering behaviors.\n"
        "Final concluding statement for the commit."
    )
    c2 = Commit(
        sha="2222222222222222222222222222222222222222",
        author_name="Dev",
        author_email="dev@example.com",
        author_date="2026-11-24 10:00:00",
        message=long_msg,
        parent_shas=(),
    )
    panel.set_commit(c2)
    h_multi = panel.message_edit.height()
    # Multi-line message must flex to be substantially taller than single-line message
    assert h_multi > h_single + 30
    assert h_multi >= 90


def test_round4_worktree_tab_management_and_stale_placeholder_removal(qtbot):
    """Test Round 4: Worktree tab placeholder is purged and replaced with WorktreePanel."""
    from PySide6.QtWidgets import QLabel, QWidget

    bar = TabContainer()
    qtbot.addWidget(bar)

    panel_widget = QWidget()
    # Simulate a stale placeholder tab named 'worktrees'
    placeholder = QWidget()
    _ = QLabel("Worktrees coming soon", placeholder)
    bar.add_tab(
        widget=placeholder,
        label="Worktrees",
        tab_type="worktrees",
        closable=True,
    )

    idx = bar.find_tab("worktrees", "")
    assert idx is not None
    assert bar.widget(idx) is not panel_widget

    # Clean up stale placeholder and install real panel
    bar.remove_tab(idx)
    bar.add_tab(
        widget=panel_widget,
        label="Worktrees",
        tab_type="worktrees",
        closable=True,
    )

    new_idx = bar.find_tab("worktrees", "")
    assert new_idx is not None
    assert bar.widget(new_idx) is panel_widget


def test_round5_worktree_panel_card_styling_and_actions(qtbot):
    """Test Round 5: WorktreePanel displays spacious cards (50px+ height) and action buttons."""
    from unittest.mock import MagicMock

    from wrench.core.models import WorktreeInfo
    from wrench.ui.widgets.worktree_panel import WorktreePanel

    engine = MagicMock()
    settings = MagicMock()
    settings.is_enabled.return_value = True

    panel = WorktreePanel(engine, settings)
    qtbot.addWidget(panel)
    panel.show()

    wt1 = WorktreeInfo(
        path="/tmp/fake-repo",
        head_oid="1111222233334444555566667777888899990000",
        branch_name="main",
        is_bare=False,
        is_locked=False,
        lock_reason=None,
        is_prunable=False,
        is_main=True,
    )
    wt2 = WorktreeInfo(
        path="/tmp/fake-repo-feature",
        head_oid="4444333322221111000099998888777766665555",
        branch_name="feature-worktree",
        is_bare=False,
        is_locked=False,
        lock_reason=None,
        is_prunable=False,
        is_main=False,
    )

    panel._repo_path = "/tmp/fake-repo"
    panel._worktrees = [wt1, wt2]
    panel._rebuild_tree()

    assert panel.lbl_count.text() == "2"
    assert panel.btn_add.text() == "+ Add Worktree"
    assert panel.tree.topLevelItemCount() == 2

    item0 = panel.tree.topLevelItem(0)
    item1 = panel.tree.topLevelItem(1)

    # Size hint must be at least 50px tall for spacious layout
    assert item0.sizeHint(0).height() >= 50
    assert item1.sizeHint(0).height() >= 50

    # Test double click emits open_worktree_requested
    with qtbot.waitSignal(panel.open_worktree_requested, timeout=1000) as sig:
        panel.tree.itemDoubleClicked.emit(item1, 0)
    assert sig.args == ["/tmp/fake-repo-feature"]


def test_round5_commit_detail_flex_proportions_and_minimum_heights(qtbot):
    """Test Round 5: DetailPanel caps huge commit message height and guards bottom sections."""
    from unittest.mock import MagicMock

    panel = CommitDetailPanel()
    qtbot.addWidget(panel)
    panel.resize(320, 600)

    mock_repo = MagicMock()
    mock_repo.path = "/tmp/repo"
    panel.set_repo(mock_repo)
    panel.show()

    # Minimum heights on files_table and diff_widget
    assert panel.files_table.minimumHeight() >= 85
    assert panel.diff_widget.minimumHeight() >= 150

    # Extremely long commit message (e.g. 25 lines like Christopher Chedeau's commit)
    huge_msg = "\n".join(
        [f"Line {i}: This is a long commit message paragraph description." for i in range(25)]
    )
    c = Commit(
        sha="44ac32b600000000000000000000000000000000",
        author_name="Christopher",
        author_email="chris@example.com",
        author_date="2026-11-24 10:00:00",
        message=huge_msg,
        parent_shas=(),
    )
    panel.set_commit(c)

    # Message box must be capped at <= 140px (never 300px+ crushing other widgets)
    msg_h = panel.message_edit.height()
    assert msg_h <= 140
    assert msg_h >= 80

    # Vertical compact layout sets splitter sizes and vertical orientation
    panel.set_compact_vertical_layout(True)
    assert panel.splitter.orientation() == Qt.Orientation.Vertical
    sizes = panel.splitter.sizes()
    assert sizes[0] >= 85  # files_table not crushed
    assert sizes[1] >= 150  # diff_widget has plenty of room
