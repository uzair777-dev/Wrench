"""Core integration & edge-case tests for VP-2 Interactive Rebase Sequencer."""

from __future__ import annotations

import os
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path

import pygit2
import pytest

from wrench.core import engine, rebase_sequencer
from wrench.core.exceptions import (
    DirtyTreeError,
    EmptyCommitMessageError,
    RepoBusyError,
    StaleLockDetectedError,
    WrenchGitError,
    WrenchRepoNotFoundError,
)
from wrench.core.models import RebaseTodoEntry
from wrench.core.paths import resolve_git_dir
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry


def _git(cwd: Path, *args: str) -> str:
    env = os.environ.copy()
    for var in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        env.pop(var, None)
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


def _init_repo(path: Path, *, empty: bool = False) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    if empty:
        return path
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "base.txt")
    _git(path, "commit", "-m", "base commit")
    return path


def _commit_file(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _summaries(repo: Path) -> list[str]:
    out = _git(repo, "log", "--reverse", "--format=%s")
    return [line.strip() for line in out.splitlines() if line.strip()]


def _make_settings_registry(tmp_path: Path) -> tuple[sqlite3.Connection, SettingsRegistry]:
    conn = sqlite3.connect(str(tmp_path / "settings.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    return conn, SettingsRegistry(conn)


def test_list_commits_oldest_first_and_bounded(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    base_oid = _git(repo, "rev-parse", "HEAD")
    c1 = _commit_file(repo, "f1.txt", "one\n", "commit one")
    c2 = _commit_file(repo, "f2.txt", "two\n", "commit two")
    c3 = _commit_file(repo, "f3.txt", "three\n", "commit three")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    assert [e.oid for e in entries] == [c1, c2, c3]
    assert [e.summary for e in entries] == ["commit one", "commit two", "commit three"]
    for e in entries:
        assert e.action == "pick"
        assert len(e.short_oid) == 7
        assert e.author == "Test User"

    bounded, truncated = engine.list_commits_for_interactive_rebase_checked(repo, base_oid, limit=2)
    assert len(bounded) == 2
    assert [e.oid for e in bounded] == [c1, c2]
    assert truncated is True


def test_interactive_rebase_reorder_commits(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "reorder")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _commit_file(repo, "a.txt", "a\n", "commit A")
    _commit_file(repo, "b.txt", "b\n", "commit B")
    _commit_file(repo, "c.txt", "c\n", "commit C")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    reordered = [entries[0], entries[2], entries[1]]

    handle = engine.open_repo(repo)
    res = engine.interactive_rebase(handle, base_oid, reordered)
    assert res.status == "complete"
    assert res.conflicted_files == []
    assert _summaries(repo) == ["base commit", "commit A", "commit C", "commit B"]


def test_interactive_rebase_reword_squash_fixup_drop(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "combo")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _commit_file(repo, "one.txt", "1\n", "first work")
    _commit_file(repo, "two.txt", "2\n", "second work")
    _commit_file(repo, "dropme.txt", "gone\n", "drop this commit")
    _commit_file(repo, "three.txt", "3\n", "squash with custom msg")
    _commit_file(repo, "four.txt", "4\n", "fixup quietly")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    plan = [
        replace(entries[0], action="reword", new_message="renamed first\n\nwith body line"),
        entries[1],
        replace(entries[2], action="drop"),
        replace(entries[3], action="squash", new_message="combined two and three"),
        replace(entries[4], action="fixup"),
    ]

    handle = engine.open_repo(repo)
    res = engine.interactive_rebase(handle, base_oid, plan)
    assert res.status == "complete"
    assert not (repo / "dropme.txt").exists()
    assert (repo / "two.txt").exists()
    assert (repo / "three.txt").exists()
    assert (repo / "four.txt").exists()
    assert _summaries(repo) == ["base commit", "renamed first", "combined two and three"]
    full_messages = _git(repo, "log", "-n", "2", "--reverse", "--format=%B===END===")
    assert "with body line" in full_messages


def test_interactive_rebase_squash_default_message_when_none(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "squash_default")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _commit_file(repo, "x.txt", "x\n", "keep first")
    _commit_file(repo, "y.txt", "y\n", "squash default")
    _commit_file(repo, "z.txt", "z\n", "reword last")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    plan = [
        entries[0],
        replace(entries[1], action="squash", new_message=None),
        replace(entries[2], action="reword", new_message="explicit reword after default squash"),
    ]
    res = engine.interactive_rebase(engine.open_repo(repo), base_oid, plan)
    assert res.status == "complete"
    assert _summaries(repo) == ["base commit", "keep first", "explicit reword after default squash"]
    body = _git(repo, "log", "-n", "1", "HEAD~1", "--format=%B")
    assert "squash default" in body


def test_interactive_rebase_edit_pauses_and_continues(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "edit")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _commit_file(repo, "e1.txt", "init\n", "edit target")
    _commit_file(repo, "e2.txt", "after\n", "following commit")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    plan = [replace(entries[0], action="edit"), entries[1]]

    handle = engine.open_repo(repo)
    res = engine.interactive_rebase(handle, base_oid, plan)
    assert res.status == "paused"
    assert res.conflicted_files == []
    git_dir = resolve_git_dir(repo)
    assert (git_dir / "rebase-merge").exists()

    (repo / "e1.txt").write_text("amended during edit\n", encoding="utf-8")
    _git(repo, "add", "e1.txt")
    _git(repo, "commit", "--amend", "--no-edit")

    cont = engine.rebase_continue(handle)
    assert cont.status == "complete"
    assert (repo / "e1.txt").read_text(encoding="utf-8") == "amended during edit\n"
    assert _summaries(repo) == ["base commit", "edit target", "following commit"]


def test_interactive_rebase_conflict_and_binary_conflict(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "conflict")
    (repo / "shared.txt").write_text("line 1\n", encoding="utf-8")
    (repo / "blob.bin").write_bytes(b"\x00\x01\x02")
    _git(repo, "add", "shared.txt", "blob.bin")
    _git(repo, "commit", "-m", "initial assets")
    base_oid = _git(repo, "rev-parse", "HEAD")

    _commit_file(repo, "shared.txt", "branch change A\n", "modify shared")
    (repo / "blob.bin").write_bytes(b"\xff\xfe\xfd\x00")
    _git(repo, "add", "blob.bin")
    _git(repo, "commit", "-m", "modify binary")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    # Conflict on purpose by rewriting the same file in reverse commit order
    repo2 = _init_repo(tmp_path / "conflict_reorder")
    (repo2 / "f.txt").write_text("v0\n", encoding="utf-8")
    (repo2 / "img.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01")
    _git(repo2, "add", "f.txt", "img.bin")
    _git(repo2, "commit", "-m", "v0")
    base2 = _git(repo2, "rev-parse", "HEAD")

    _commit_file(repo2, "f.txt", "v1\n", "set v1")
    (repo2 / "img.bin").write_bytes(b"\x89PNG\r\n\x1a\n\x11\x22")
    _git(repo2, "add", "img.bin")
    _git(repo2, "commit", "--amend", "--no-edit")

    (repo2 / "f.txt").write_text("v2\n", encoding="utf-8")
    (repo2 / "img.bin").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xee")
    _git(repo2, "add", "f.txt", "img.bin")
    _git(repo2, "commit", "-m", "set v2")

    entries2 = engine.list_commits_for_interactive_rebase(repo2, base2)
    handle2 = engine.open_repo(repo2)
    res = engine.interactive_rebase(handle2, base2, [entries2[1], entries2[0]])
    assert res.status == "conflict"
    assert "f.txt" in res.conflicted_files
    assert "img.bin" in res.conflicted_files
    engine.rebase_abort(handle2)
    assert len(entries) == 2


def test_interactive_rebase_autostash_and_dirty_tree_guard(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "autostash")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _commit_file(repo, "work.txt", "c1\n", "commit one")
    _commit_file(repo, "other.txt", "c2\n", "commit two")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    (repo / "base.txt").write_text("dirty uncommitted tweak\n", encoding="utf-8")

    handle = engine.open_repo(repo)
    with pytest.raises(DirtyTreeError):
        engine.interactive_rebase(handle, base_oid, entries, autostash=False)

    reordered = [entries[1], entries[0]]
    res = engine.interactive_rebase(handle, base_oid, reordered, autostash=True)
    assert res.status == "complete"
    assert (repo / "base.txt").read_text(encoding="utf-8") == "dirty uncommitted tweak\n"
    assert _summaries(repo) == ["base commit", "commit two", "commit one"]


def test_interactive_rebase_edge_cases_snapshots_and_security(tmp_path: Path) -> None:
    # 1. Invalid repo path
    with pytest.raises(WrenchRepoNotFoundError):
        engine.list_commits_for_interactive_rebase(tmp_path / "missing", "HEAD")

    # 2. Unborn HEAD
    empty_repo = _init_repo(tmp_path / "empty", empty=True)
    assert engine.list_commits_for_interactive_rebase(empty_repo, "HEAD") == []
    with pytest.raises(WrenchGitError, match="unborn HEAD"):
        rebase_sequencer.run_interactive_rebase(
            empty_repo,
            "HEAD",
            [RebaseTodoEntry("pick", "a" * 40, "a" * 7, "x", "A")],
        )

    # 3. Detached HEAD + pre_op_snapshot + GitEngine toggle + CLI '--' + lock + validation
    repo = _init_repo(tmp_path / "edge")
    base_oid = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "feature/work")
    _commit_file(repo, "d1.txt", "1\n", "first")
    _commit_file(repo, "d2.txt", "2\n", "second")
    head_oid = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", head_oid)

    head_lbl, base_lbl, is_detached = engine.get_interactive_rebase_target_label(repo, base_oid)
    assert is_detached is True
    assert head_lbl == "detached HEAD"
    assert base_lbl == "main"

    assert engine.build_interactive_rebase_cli_args(base_oid) == [
        "rebase",
        "-i",
        "--autostash",
        "--autosquash",
        "--",
        base_oid,
    ]
    with pytest.raises(WrenchGitError):
        engine.build_interactive_rebase_cli_args("--exec=evil")

    entries = engine.list_commits_for_interactive_rebase(repo, base_oid)
    with pytest.raises(WrenchGitError, match="Cannot squash/fixup the first commit"):
        engine.interactive_rebase(
            engine.open_repo(repo), base_oid, [replace(entries[0], action="squash"), entries[1]]
        )

    with pytest.raises(EmptyCommitMessageError):
        engine.interactive_rebase(
            engine.open_repo(repo),
            base_oid,
            [replace(entries[0], action="reword", new_message="   \n"), entries[1]],
        )

    # index.lock detection
    lock_file = resolve_git_dir(repo) / "index.lock"
    lock_file.write_text("", encoding="utf-8")
    try:
        with pytest.raises(StaleLockDetectedError):
            engine.interactive_rebase(engine.open_repo(repo), base_oid, entries)
    finally:
        lock_file.unlink(missing_ok=True)

    # RepoBusyError if rebase-merge exists
    rm_dir = resolve_git_dir(repo) / "rebase-merge"
    rm_dir.mkdir(exist_ok=True)
    try:
        with pytest.raises(RepoBusyError):
            engine.interactive_rebase(engine.open_repo(repo), base_oid, entries)
    finally:
        rm_dir.rmdir()

    # Safety snapshot creation controlled by SettingsRegistry + detached HEAD rebase
    conn, registry = _make_settings_registry(tmp_path)
    try:
        handle = engine.open_repo(repo)
        git_engine = engine.GitEngine(handle, settings=registry)
        registry.set("safety.pre_op_snapshot.enabled", True)
        res = git_engine.interactive_rebase(
            base_oid,
            [replace(entries[0], action="reword", new_message="detached reword"), entries[1]],
            conn=conn,
        )
        assert res.status == "complete"
        assert pygit2.Repository(str(repo)).head_is_detached is True
        assert _summaries(repo) == ["base commit", "detached reword", "second"]
        snap_rows = conn.execute("SELECT label, trigger_type FROM snapshots").fetchall()
        assert any(
            row["trigger_type"] == "pre_risky_op" and row["label"] == "Before interactive_rebase"
            for row in snap_rows
        )

        # Toggle off disables GitEngine calls immediately
        registry.set("rebase.interactive_ui.enabled", False)
        assert git_engine.list_commits_for_interactive_rebase(base_oid) == []
        with pytest.raises(WrenchGitError, match="disabled in Settings"):
            git_engine.interactive_rebase(base_oid, entries, conn=conn)
    finally:
        conn.close()
