"""UI test for ChangesTab composite badges on partially-staged files."""

import pytest

from wrench.core import engine
from wrench.ui.tabs.changes_tab import ChangesTab, FileListItemWidget


@pytest.fixture
def changes_tab(qtbot, simple_repo):
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS repo_settings "
        "(repo_path TEXT, key TEXT, value TEXT, PRIMARY KEY(repo_path, key))"
    )
    tab = ChangesTab(conn)
    qtbot.addWidget(tab)
    tab.set_repo(simple_repo)
    return tab


def test_changes_tab_displays_composite_mm_badge(changes_tab, simple_repo) -> None:
    # 1. Modify and stage hello.txt
    (simple_repo.path / "hello.txt").write_text("first edit staged\n")
    engine.stage_file(simple_repo, "hello.txt")

    # 2. Modify hello.txt again without staging -> creates MM state
    (simple_repo.path / "hello.txt").write_text("second edit in worktree\n")

    changes_tab.refresh()

    assert changes_tab.files_list.count() == 1
    item = changes_tab.files_list.item(0)
    widget = changes_tab.files_list.itemWidget(item)
    assert isinstance(widget, FileListItemWidget)

    # Badge should reflect dual-state MM
    assert widget.badge.text() == "MM"
    assert "Partially Staged" in widget.toolTip()
    assert widget.badge.minimumWidth() >= 30


def test_changes_tab_commit_stage_all_mode(changes_tab, simple_repo) -> None:
    from wrench.storage.settings_registry import get_settings_registry

    registry = get_settings_registry(changes_tab._conn)
    registry.set_value(
        "safety.commit_partially_staged_mode",
        "stage_all",
        repo_path=str(simple_repo.path),
    )

    (simple_repo.path / "hello.txt").write_text("edit 1 staged\n")
    engine.stage_file(simple_repo, "hello.txt")
    (simple_repo.path / "hello.txt").write_text("edit 2 in worktree\n")

    changes_tab.refresh()
    changes_tab.commit_msg_input.setText("feat: test stage all")
    changes_tab._on_commit_clicked()

    # Both edits should be committed; working tree clean
    status = engine.get_status(simple_repo)
    assert len(status.staged) == 0
    assert len(status.unstaged) == 0
    assert (simple_repo.path / "hello.txt").read_text() == "edit 2 in worktree\n"


def test_changes_tab_commit_staged_only_mode(changes_tab, simple_repo) -> None:
    from wrench.storage.settings_registry import get_settings_registry

    registry = get_settings_registry(changes_tab._conn)
    registry.set_value(
        "safety.commit_partially_staged_mode",
        "staged_only",
        repo_path=str(simple_repo.path),
    )

    (simple_repo.path / "hello.txt").write_text("edit 1 staged\n")
    engine.stage_file(simple_repo, "hello.txt")
    (simple_repo.path / "hello.txt").write_text("edit 2 in worktree\n")

    changes_tab.refresh()
    changes_tab.commit_msg_input.setText("feat: test staged only")
    changes_tab._on_commit_clicked()

    # Edit 1 is committed, Edit 2 remains unstaged in working tree
    status = engine.get_status(simple_repo)
    assert len(status.staged) == 0
    assert len(status.unstaged) == 1
    assert status.unstaged[0].path == "hello.txt"


def test_changes_tab_commit_prompt_mode_with_cancel(changes_tab, simple_repo, monkeypatch) -> None:
    monkeypatch.setenv("WRENCH_TEST_PARTIAL_STAGING_CHOICE", "cancel")

    (simple_repo.path / "hello.txt").write_text("edit 1 staged\n")
    engine.stage_file(simple_repo, "hello.txt")
    (simple_repo.path / "hello.txt").write_text("edit 2 in worktree\n")

    changes_tab.refresh()
    changes_tab.commit_msg_input.setText("feat: cancel test")
    changes_tab._on_commit_clicked()

    # Commit should be aborted; input message preserved
    assert changes_tab.commit_msg_input.text() == "feat: cancel test"
    status = engine.get_status(simple_repo)
    assert len(status.staged) == 1
    assert len(status.unstaged) == 1
