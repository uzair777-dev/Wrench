"""Core unit & integration tests for VP-3 Git Worktrees & Bare-Hub Mode."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from wrench.core import engine
from wrench.core.exceptions import (
    WorktreeAlreadyCheckedOutError,
    WrenchGitError,
)
from wrench.core.models import WorktreeInfo
from wrench.storage import session_storage
from wrench.storage.db import run_migrations


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_repo(path: Path, *, bare: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if bare:
        _git(path, "init", "--bare", "-b", "main")
        return path

    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Wrench Tester")
    _git(path, "config", "user.email", "test@example.com")
    (path / "README.md").write_text("root\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "initial commit")
    return path


def test_format_worktree_path(tmp_path: Path) -> None:
    repo_dir = tmp_path / "my-project"
    repo_dir.mkdir()

    # Default template resolves relative to repo_dir's parent
    path = engine.format_worktree_path(repo_dir, "feature/awesome-ui")
    expected = (tmp_path.parent / "my-project-feature-awesome-ui").resolve()
    assert Path(path) == expected

    # Custom template
    custom_tmpl = "../worktrees/{repo_name}/{branch_name}"
    path_custom = engine.format_worktree_path(
        repo_dir, "hotfix/urgent", custom_tmpl
    )
    expected_custom = (tmp_path.parent / "worktrees" / "my-project" / "hotfix" / "urgent").resolve()
    assert Path(path_custom) == expected_custom


def test_worktree_lifecycle_real_repo(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "main-repo")

    # 1. List initial worktrees
    wts = engine.list_worktrees(repo_dir)
    assert len(wts) == 1
    main_wt = wts[0]
    assert main_wt.is_main is True
    assert main_wt.branch_name == "main"
    assert main_wt.is_bare is False
    assert main_wt.is_locked is False

    # 2. Add linked worktree with a new branch
    wt_path = tmp_path / "wt-feature"
    added_wt = engine.add_worktree(
        repo_dir,
        wt_path,
        branch_name="feature-x",
        new_branch=True,
    )
    assert added_wt.path == str(wt_path.resolve())
    assert added_wt.branch_name == "feature-x"
    assert added_wt.is_main is False
    assert (wt_path / ".git").is_file()

    # 3. List worktrees now contains both
    wts2 = engine.list_worktrees(repo_dir)
    assert len(wts2) == 2
    linked = [w for w in wts2 if not w.is_main][0]
    assert linked.branch_name == "feature-x"
    assert linked.is_locked is False

    # 4. Lock worktree
    engine.lock_worktree(repo_dir, wt_path, reason="active development")
    wts3 = engine.list_worktrees(repo_dir)
    linked_locked = [w for w in wts3 if not w.is_main][0]
    assert linked_locked.is_locked is True
    assert linked_locked.lock_reason == "active development"

    # 5. Unlock worktree
    engine.unlock_worktree(repo_dir, wt_path)
    wts4 = engine.list_worktrees(repo_dir)
    linked_unlocked = [w for w in wts4 if not w.is_main][0]
    assert linked_unlocked.is_locked is False

    # 6. Remove worktree
    engine.remove_worktree(repo_dir, wt_path, force=True)
    wts5 = engine.list_worktrees(repo_dir)
    assert len(wts5) == 1
    assert not wt_path.exists()


def test_add_worktree_already_checked_out_error(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo-conflict")
    wt_path = tmp_path / "wt-conflict"

    with pytest.raises(WorktreeAlreadyCheckedOutError):
        engine.add_worktree(
            repo_dir,
            wt_path,
            branch_name="main",
            new_branch=False,
        )


def test_bare_hub_mode_and_worktrees(tmp_path: Path) -> None:
    bare_hub = _init_repo(tmp_path / "hub.git", bare=True)

    # Bare hub status check
    repo_handle = engine.open_repo(bare_hub)
    status = engine.get_status(repo_handle)
    assert status.is_bare is True
    assert status.is_bare_hub is True

    # Add worktree to bare hub
    wt1_path = tmp_path / "hub-worktree-1"
    engine.add_worktree(
        bare_hub,
        wt1_path,
        branch_name="trunk",
        new_branch=True,
    )
    _git(wt1_path, "config", "user.name", "Tester")
    _git(wt1_path, "config", "user.email", "tester@test.com")
    (wt1_path / "first.txt").write_text("bare hub works!\n", encoding="utf-8")
    _git(wt1_path, "add", "-A")
    _git(wt1_path, "commit", "-m", "first commit in bare hub worktree")

    wts = engine.list_worktrees(bare_hub)
    # The bare repo entry is bare, linked worktree is non-bare
    assert any(w.is_bare for w in wts)
    linked = [w for w in wts if not w.is_bare]
    assert len(linked) == 1
    assert linked[0].branch_name == "trunk"


def test_prune_worktrees(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo-prune")
    wt_path = tmp_path / "wt-to-prune"
    engine.add_worktree(repo_dir, wt_path, branch_name="prune-me", new_branch=True)

    assert len(engine.list_worktrees(repo_dir)) == 2

    # Manually delete worktree folder on disk (simulating external deletion)
    import shutil
    shutil.rmtree(wt_path)

    # Before prune, list_worktrees flags it as prunable
    wts = engine.list_worktrees(repo_dir)
    prunable_wts = [w for w in wts if w.is_prunable]
    assert len(prunable_wts) == 1

    # Prune
    engine.prune_worktrees(repo_dir)
    assert len(engine.list_worktrees(repo_dir)) == 1


def test_cross_worktree_cherry_pick(tmp_path: Path) -> None:
    repo_dir = _init_repo(tmp_path / "repo-cherry")

    wt1_path = tmp_path / "wt1"
    wt2_path = tmp_path / "wt2"

    engine.add_worktree(repo_dir, wt1_path, branch_name="branch-1", new_branch=True)
    engine.add_worktree(repo_dir, wt2_path, branch_name="branch-2", new_branch=True)

    _git(wt1_path, "config", "user.name", "Tester")
    _git(wt1_path, "config", "user.email", "tester@test.com")
    _git(wt2_path, "config", "user.name", "Tester")
    _git(wt2_path, "config", "user.email", "tester@test.com")

    # Create commit in wt1
    (wt1_path / "feat.txt").write_text("feature content\n", encoding="utf-8")
    _git(wt1_path, "add", "-A")
    _git(wt1_path, "commit", "-m", "cherry pick me")
    sha = _git(wt1_path, "rev-parse", "HEAD")

    # Cherry-pick into wt2
    engine.cross_worktree_cherry_pick(wt2_path, sha)

    # Verify feat.txt exists in wt2
    assert (wt2_path / "feat.txt").exists()
    assert (wt2_path / "feat.txt").read_text(encoding="utf-8") == "feature content\n"


def test_workspace_sessions_storage_crud(tmp_path: Path) -> None:
    db_path = tmp_path / "wrench_test.db"
    conn = sqlite3.connect(str(db_path))
    run_migrations(conn)

    # 1. Save sessions
    session_storage.save_session(
        conn,
        "Project Alpha",
        ["/repos/alpha-main", "/repos/alpha-wt1"],
        active_index=1,
    )
    session_storage.save_session(
        conn,
        "Project Beta",
        ["/repos/beta"],
        active_index=0,
    )

    # 2. List sessions
    sessions = session_storage.list_sessions(conn)
    assert "Project Alpha" in sessions
    assert "Project Beta" in sessions

    # 3. Load session
    loaded = session_storage.load_session(conn, "Project Alpha")
    assert loaded is not None
    assert loaded.session_name == "Project Alpha"
    assert loaded.repo_paths == ("/repos/alpha-main", "/repos/alpha-wt1")
    assert loaded.active_index == 1

    # 4. Update session
    session_storage.save_session(
        conn,
        "Project Alpha",
        ["/repos/alpha-main", "/repos/alpha-wt1", "/repos/alpha-wt2"],
        active_index=2,
    )
    updated = session_storage.load_session(conn, "Project Alpha")
    assert updated is not None
    assert len(updated.repo_paths) == 3
    assert updated.active_index == 2

    # 5. Delete session
    assert session_storage.delete_session(conn, "Project Beta") is True
    assert session_storage.load_session(conn, "Project Beta") is None
    assert session_storage.delete_session(conn, "Nonexistent") is False
