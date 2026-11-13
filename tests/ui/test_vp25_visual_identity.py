"""Automated UI verification suite for Phase VP-2.5 (FR-3.16, FR-3.17, FR-11.7-11.10)."""

from pathlib import Path

import pygit2
from PySide6.QtCore import Qt

from wrench.core.engine import GitEngine, open_repo
from wrench.core.models import BranchSyncStatus, Diff, DiffLine, Hunk
from wrench.ui import icons
from wrench.ui.changes_view import ZeroChangesLaunchpadWidget
from wrench.ui.commit_graph.graph_widget import CommitGraphWidget
from wrench.ui.diff_view.diff_widget import DiffWidget
from wrench.ui.history_view import HistoryView
from wrench.ui.widgets.context_header_bar import ContextHeaderBar, GitTerminalDrawer


def test_icons_vector_rendering(qapp):
    """Verify all 26 SVG vector icon templates render into valid QPixmap and QIcon."""
    assert len(icons.ICON_NAMES) >= 26
    for name in icons.ICON_NAMES:
        pm = icons.get_pixmap(name, size=24)
        assert pm is not None
        assert not pm.isNull()
        assert pm.width() == 24
        assert pm.height() == 24

        icon = icons.get_icon(name, size=16)
        assert icon is not None
        assert not icon.isNull()

    # Fallback guard
    fallback_pm = icons.get_pixmap("non_existent_icon_xyz", size=20)
    assert fallback_pm is not None
    assert not fallback_pm.isNull()


def test_context_header_bar_components(qapp, tmp_path: Path):
    """Verify 4-Cell ContextHeaderBar displays repo/branch metadata and emits sync signals."""
    bar = ContextHeaderBar()
    bar.set_repo_info("wrench", "/home/dev/wrench")
    assert "wrench" in bar.repo_cell.repo_name_lbl.text()

    status = BranchSyncStatus(
        branch_name="feature/visuals",
        upstream_name="origin/feature/visuals",
        ahead=3,
        behind=2,
        is_detached=False,
    )
    bar.set_branch_sync_status(status)
    assert "feature/visuals" in bar.branch_cell.branch_btn.text()
    assert "3↑" in bar.sync_cell.sync_btn.text()
    assert "2↓" in bar.sync_cell.sync_btn.text()

    # Test sync signal emissions
    sync_emitted = []
    fetch_emitted = []
    undo_emitted = []
    terminal_emitted = []

    bar.sync_clicked.connect(lambda: sync_emitted.append(True))
    bar.fetch_clicked.connect(lambda: fetch_emitted.append(True))
    bar.undo_clicked.connect(lambda: undo_emitted.append(True))
    bar.terminal_clicked.connect(lambda: terminal_emitted.append(True))

    bar.sync_cell.sync_btn.click()
    assert len(sync_emitted) == 1

    status_clean = BranchSyncStatus(
        branch_name="feature/visuals",
        upstream_name="origin/feature/visuals",
        ahead=0,
        behind=0,
        is_detached=False,
    )
    bar.set_branch_sync_status(status_clean)
    bar.sync_cell.fetch_btn.click()
    assert len(fetch_emitted) == 1

    bar.quick_actions.undo_btn.click()
    assert len(undo_emitted) == 1

    bar.quick_actions.terminal_btn.click()
    assert len(terminal_emitted) == 1
    bar.close()


def test_git_terminal_drawer_toggle_and_exec(qapp):
    """Verify GitTerminalDrawer toggle animation and safe command execution."""
    drawer = GitTerminalDrawer()
    assert not drawer.is_expanded

    drawer.toggle_drawer()
    assert drawer.is_expanded

    # Mock runner
    runner_calls = []

    def mock_runner(args):
        runner_calls.append(args)
        return (0, "On branch main\nnothing to commit", "", 12.5)

    drawer.set_command_runner(mock_runner)
    drawer.cmd_input.setText("git status")
    drawer._on_execute_command()

    assert len(runner_calls) == 1
    assert runner_calls[0] == ["status"]
    log_text = drawer.log_view.toPlainText()
    assert "On branch main" in log_text
    assert "succeeded in 12.5ms" in log_text

    drawer.close()


def test_zero_changes_launchpad_widget(qapp):
    """Verify ZeroChangesLaunchpadWidget 4 action cards and Linus quote display."""
    launchpad = ZeroChangesLaunchpadWidget()
    assert len(launchpad.cards) == 4
    assert launchpad.quote_lbl.text() != ""

    sync_clicked = []
    terminal_clicked = []
    file_clicked = []
    history_clicked = []

    launchpad.sync_clicked.connect(lambda: sync_clicked.append(True))
    launchpad.terminal_clicked.connect(lambda: terminal_clicked.append(True))
    launchpad.file_manager_clicked.connect(lambda: file_clicked.append(True))
    launchpad.history_clicked.connect(lambda: history_clicked.append(True))

    launchpad.cards[0].mousePressEvent(None)
    assert len(sync_clicked) == 1

    launchpad.cards[1].mousePressEvent(None)
    assert len(terminal_clicked) == 1

    launchpad.cards[2].mousePressEvent(None)
    assert len(file_clicked) == 1

    launchpad.cards[3].mousePressEvent(None)
    assert len(history_clicked) == 1
    launchpad.close()


def test_diff_widget_dual_gutter_and_50k_cap(qapp):
    """Verify DiffWidget renders dual-gutter line numbers and protects against huge diffs."""
    widget = DiffWidget()
    widget.show()

    # Small diff
    hunk = Hunk(
        id="h1",
        old_start=1,
        old_count=3,
        new_start=1,
        new_count=3,
        lines=[
            DiffLine(content="context line", origin=" ", old_lineno=1, new_lineno=1),
            DiffLine(content="deleted line", origin="-", old_lineno=2, new_lineno=None),
            DiffLine(content="added line", origin="+", old_lineno=None, new_lineno=2),
        ],
    )
    diff = Diff(path="sample.py", is_binary=False, hunks=[hunk])
    widget.set_diff_model(diff)
    assert widget.truncation_banner.isHidden()

    # 50,001 line diff cap test
    lines_huge = [
        DiffLine(content=f"line {i}", origin=" ", old_lineno=i, new_lineno=i)
        for i in range(1, 50005)
    ]
    hunk_huge = Hunk(
        id="h_huge", old_start=1, old_count=50005, new_start=1, new_count=50005, lines=lines_huge
    )
    diff_huge = Diff(path="huge.txt", is_binary=False, hunks=[hunk_huge])
    widget.set_diff_model(diff_huge)
    assert not widget.truncation_banner.isHidden()
    widget.close()


def test_history_view_three_column_layout_and_refs_sidebar(qapp, tmp_path: Path):
    """Verify HistoryView 3-column layout, RefsSidebarWidget hierarchy, and CommitInspectorDock."""
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    # Initial commit
    tree_bld = repo.TreeBuilder()
    blob_id = repo.create_blob(b"history three column test\n")
    tree_bld.insert("app.py", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    c1 = repo.create_commit("refs/heads/main", sig, sig, "Initial commit on main", tree_oid, [])
    repo.set_head("refs/heads/main")

    # Create tag
    repo.create_tag("v0.1.0", c1, pygit2.GIT_OBJECT_COMMIT, sig, "Initial release")

    handle = open_repo(tmp_path)
    view = HistoryView()
    view.set_repo(handle)

    # Check 3 columns in splitter
    assert view.content_splitter.count() == 3
    assert view.sidebar is not None
    assert view.graph_widget is not None
    assert view.inspector_dock is not None

    # Check sidebar hierarchy
    assert view.sidebar.local_root.childCount() >= 1
    assert "main" in view.sidebar.local_root.child(0).text(0)
    assert view.sidebar.tag_root.childCount() >= 1
    assert "v0.1.0" in view.sidebar.tag_root.child(0).text(0)

    # Check commit inspector dock
    commit_details = GitEngine(handle).get_commit_details(str(c1))
    view.inspector_dock.set_commit(commit_details)
    assert view.inspector_dock.sha_lbl.text() == str(c1)
    assert "Dev" in view.inspector_dock.author_name_lbl.text()
    assert "Initial commit on main" in view.inspector_dock.msg_edit.toPlainText()

    view.close()


def test_graph_widget_wip_virtual_row(qapp, tmp_path: Path):
    """Verify CommitGraphWidget inserts virtual // WIP row when uncommitted changes exist."""
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    # Commit 1
    tree_bld = repo.TreeBuilder()
    blob_id = repo.create_blob(b"wip row test\n")
    tree_bld.insert("tracked.txt", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    c1 = repo.create_commit("refs/heads/main", sig, sig, "Base commit", tree_oid, [])
    repo.set_head("refs/heads/main")

    # Modify file to create unstaged dirty changes
    (tmp_path / "tracked.txt").write_text("modified uncommitted content\n")

    handle = open_repo(tmp_path)
    graph = CommitGraphWidget()
    graph.set_three_column_mode(True)
    graph.set_repo(handle)

    # Verify row 0 is WIP row
    assert graph._model.rowCount() >= 2
    row0 = graph._model._rows[0]
    assert row0.commit.sha == "0000000000000000000000000000000000000000"
    assert "// WIP" in row0.commit.message
    assert row0.commit.author_name == "Working Tree"

    # Header in 3-column mode has 6 columns
    assert graph._model.columnCount() == 6
    assert graph._model.headerData(0, Qt.Orientation.Horizontal) == "Branch / Tag"
    assert graph._model.headerData(1, Qt.Orientation.Horizontal) == "Graph"
    assert graph._model.headerData(2, Qt.Orientation.Horizontal) == "Message"

    graph.close()
