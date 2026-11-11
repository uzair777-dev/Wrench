"""Core unit & integration tests for VP-16 Monorepo Engine."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pygit2
import pytest

from wrench.core import engine
from wrench.core.exceptions import WrenchRepoNotFoundError
from wrench.core.models import (
    CommitGraphStats,
    LogFilter,
    LogPage,
    SparseCheckoutState,
    TreeDirectoryEntry,
)
from wrench.core.paths import resolve_git_dir
from wrench.core.security_sanitizer import redact_secrets, validate_clone_url, validate_git_ref
from wrench.core.sparse_checkout import _validate_sparse_dir
from wrench.storage.db import run_migrations
from wrench.storage.settings_registry import SettingsRegistry


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=cwd,
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

    (path / "README.md").write_text("root\n", encoding="utf-8")
    (path / "apps" / "api").mkdir(parents=True, exist_ok=True)
    (path / "apps" / "api" / "main.py").write_text("print('api')\n", encoding="utf-8")
    (path / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (path / "apps" / "web" / "index.ts").write_text("console.log('web')\n", encoding="utf-8")
    (path / "libs" / "core").mkdir(parents=True, exist_ok=True)
    (path / "libs" / "core" / "util.py").write_text("x = 1\n", encoding="utf-8")
    (path / "docs").mkdir(parents=True, exist_ok=True)
    (path / "docs" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    _git(path, "add", "-A")
    _git(path, "commit", "-m", "initial monorepo commit")
    return path


def test_sparse_checkout_lifecycle_real_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "monorepo")
    assert engine.is_sparse_checkout_enabled(repo) is False
    assert engine.list_sparse_directories(repo) == []

    engine.init_sparse_checkout(repo, cone=True)
    assert engine.is_sparse_checkout_enabled(repo) is True
    assert engine.list_sparse_directories(repo) == []
    assert (repo / "README.md").exists()
    assert not (repo / "apps").exists()

    engine.set_sparse_directories(repo, ["apps/api", "docs"])
    dirs = engine.list_sparse_directories(repo)
    assert dirs == ["apps/api", "docs"]
    assert (repo / "apps" / "api" / "main.py").exists()
    assert (repo / "docs" / "guide.md").exists()
    assert not (repo / "libs").exists()

    state = engine.get_sparse_checkout_state(repo)
    assert isinstance(state, SparseCheckoutState)
    assert state.enabled is True
    assert state.cone_mode is True
    assert state.directories == ("apps/api", "docs")

    engine.disable_sparse_checkout(repo)
    assert engine.is_sparse_checkout_enabled(repo) is False
    assert (repo / "libs" / "core" / "util.py").exists()
    assert (repo / "apps" / "web" / "index.ts").exists()


def test_linked_worktree_resolve_and_sparse(tmp_path: Path) -> None:
    main_repo = _init_repo(tmp_path / "main_repo")
    wt_dir = tmp_path / "wt_feature"
    _git(main_repo, "worktree", "add", "-b", "feature/sparse", str(wt_dir))

    resolved = resolve_git_dir(wt_dir)
    assert resolved.is_dir()
    assert "worktrees" in str(resolved)

    engine.set_sparse_directories(wt_dir, ["libs/core"])
    assert engine.is_sparse_checkout_enabled(wt_dir) is True
    assert engine.list_sparse_directories(wt_dir) == ["libs/core"]
    assert (wt_dir / "libs" / "core" / "util.py").exists()
    assert not (wt_dir / "docs").exists()
    assert engine.is_sparse_checkout_enabled(main_repo) is False

    with pytest.raises(WrenchRepoNotFoundError):
        resolve_git_dir(tmp_path / "does_not_exist")


def test_list_tree_subdirectories_skips_blobs_submodules_and_handles_edge_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Unborn HEAD returns []
    empty_repo = _init_repo(tmp_path / "empty_repo", empty=True)
    assert engine.is_unborn_repo(empty_repo) is True
    assert engine.list_tree_subdirectories(empty_repo) == []
    assert engine.list_head_top_directories(empty_repo) == []

    # Populated repo with submodule gitlink + detached HEAD
    repo = _init_repo(tmp_path / "with_submod")
    sub_src = _init_repo(tmp_path / "sub_src")
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add", str(sub_src), "vendor/sub"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    _git(repo, "commit", "-m", "add submodule")

    top_entries = engine.list_tree_subdirectories(repo)
    assert all(isinstance(e, TreeDirectoryEntry) for e in top_entries)
    top_names = [e.name for e in top_entries]
    assert top_names == ["apps", "docs", "libs", "vendor"]

    # Submodule entry under vendor/ is GIT_OBJECT_COMMIT and must be skipped
    vendor_children = engine.list_tree_subdirectories(repo, "vendor")
    assert vendor_children == []

    # Apps has nested dirs; docs has only files -> has_children checks accuracy
    apps_entry = next(e for e in top_entries if e.name == "apps")
    docs_entry = next(e for e in top_entries if e.name == "docs")
    assert apps_entry.has_children is True
    assert docs_entry.has_children is False

    # Detached HEAD still lists tree cleanly
    head_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "--detach", head_sha)
    detached_children = engine.list_tree_subdirectories(repo, "apps")
    assert [e.rel_path for e in detached_children] == ["apps/api", "apps/web"]

    # Top directory scan bounded by max_depth
    depth1 = engine.list_head_top_directories(repo, max_depth=1)
    assert depth1 == ["apps", "docs", "libs", "vendor"]
    depth2 = engine.list_head_top_directories(repo, max_depth=2)
    assert "apps/api" in depth2
    assert "vendor/sub" not in depth2


def test_security_sanitizers_and_validators() -> None:
    # SEC-2 clone URL validation
    for bad in [
        "",
        "   ",
        "--upload-pack=evil",
        "-oProxyCommand=bad",
        "ext::sh -c whoami",
        "EXT::echo pwned",
        "fd::0",
        "javascript:alert(1)",
        "data:text/plain,abc",
        "https://github.com/a/b\x00c",
        "https://",
        "ftp://example.com/repo.git",
    ]:
        with pytest.raises(ValueError):
            validate_clone_url(bad)

    assert (
        validate_clone_url("https://github.com/org/repo.git") == "https://github.com/org/repo.git"
    )
    assert validate_clone_url("git@github.com:org/repo.git") == "git@github.com:org/repo.git"
    assert validate_clone_url("file:///tmp/upstream.git") == "file:///tmp/upstream.git"
    assert validate_clone_url("/tmp/upstream.git") == "/tmp/upstream.git"

    # Ref validation
    for bad_ref in ["", "--exec=evil", "a..b", "foo bar", "bad~1", "branch.lock"]:
        with pytest.raises(ValueError):
            validate_git_ref(bad_ref)
    assert validate_git_ref("feature/vp-16_test") == "feature/vp-16_test"

    # Sparse path validation
    for bad_dir in ["", "/", "../etc", "a/../b", "/abs/path", "dir/*", "a/-flag", "a\x00b", "a//b"]:
        with pytest.raises(ValueError):
            _validate_sparse_dir(bad_dir)
    assert _validate_sparse_dir(".github/workflows/") == ".github/workflows"

    # SEC-3 secret redaction
    secret_text = (
        "git clone -- https://alice:s3cr3tpass@github.com/org/repo.git "
        "token ghp_1234567890abcdef and glpat-abc123def456 Bearer eyJ0eXAiOiJKV1Q"
    )
    redacted = redact_secrets(secret_text)
    assert "s3cr3tpass" not in redacted
    assert "alice:" not in redacted
    assert "ghp_1234567890abcdef" not in redacted
    assert "glpat-abc123def456" not in redacted
    assert "eyJ0eXAiOiJKV1Q" not in redacted
    assert "https://***:***@github.com/org/repo.git" in redacted


def test_partial_clone_with_sparse_local_file_remote(tmp_path: Path) -> None:
    work_src = _init_repo(tmp_path / "src_repo")
    bare_remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--bare", str(work_src), str(bare_remote))
    # Enable uploadpack.allowFilter on bare repo for file:// partial clone
    _git(bare_remote, "config", "uploadpack.allowFilter", "true")
    _git(bare_remote, "config", "uploadpack.allowAnySHA1InWant", "true")

    dest = tmp_path / "partial_checkout"
    result = engine.clone_repo(
        bare_remote.as_uri(),
        dest,
        filter_spec="blob:none",
        sparse=True,
    )
    assert result.path == dest
    state = engine.get_sparse_checkout_state(dest)
    assert state.enabled is True
    assert state.partial_filter == "blob:none"
    assert (dest / "README.md").exists()
    assert not (dest / "apps").exists()

    engine.set_sparse_directories(dest, ["apps/api"])
    assert (dest / "apps" / "api" / "main.py").exists()


def test_partial_clone_tree_zero_promisor_lazy_dir_listing(tmp_path: Path) -> None:
    work_src = _init_repo(tmp_path / "src_tree0")
    bare_remote = tmp_path / "remote_tree0.git"
    _git(tmp_path, "clone", "--bare", str(work_src), str(bare_remote))
    _git(bare_remote, "config", "uploadpack.allowFilter", "true")
    _git(bare_remote, "config", "uploadpack.allowAnySHA1InWant", "true")

    dest = tmp_path / "tree0_checkout"
    result = engine.clone_repo(
        bare_remote.as_uri(),
        dest,
        filter_spec="tree:0",
        sparse=True,
    )
    assert result.path == dest
    state = engine.get_sparse_checkout_state(dest)
    assert state.enabled is True
    assert state.partial_filter == "tree:0"

    top = engine.list_tree_subdirectories(dest, "")
    assert [e.name for e in top] == ["apps", "docs", "libs"]
    apps_children = engine.list_tree_subdirectories(dest, "apps")
    assert [e.rel_path for e in apps_children] == ["apps/api", "apps/web"]


def test_commit_graph_write_locks_and_setting_gate(tmp_path: Path) -> None:
    empty = _init_repo(tmp_path / "empty", empty=True)
    empty_stats = engine.write_commit_graph(empty)
    assert isinstance(empty_stats, CommitGraphStats)
    assert empty_stats.written is False
    assert empty_stats.skipped_reason == "empty_repo"

    repo = _init_repo(tmp_path / "repo")
    info_dir = repo / ".git" / "objects" / "info"
    info_dir.mkdir(parents=True, exist_ok=True)
    lock_file = info_dir / "commit-graph.lock"
    lock_file.write_text("locked", encoding="utf-8")

    locked_stats = engine.write_commit_graph(repo)
    assert locked_stats.written is False
    assert locked_stats.skipped_reason == "locked"
    lock_file.unlink()

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    run_migrations(conn)
    reg = SettingsRegistry(conn=conn)
    reg.set("maintenance.auto_commit_graph.enabled", False)
    disabled_stats = engine.maybe_write_commit_graph(repo, settings_registry=reg)
    assert disabled_stats.written is False
    assert disabled_stats.skipped_reason == "disabled"

    reg.set("maintenance.auto_commit_graph.enabled", True)
    ok_stats = engine.maybe_write_commit_graph(repo, settings_registry=reg)
    assert ok_stats.written is True
    assert ok_stats.graph_file_size_bytes > 0
    assert (info_dir / "commit-graph").is_file() or (
        info_dir / "commit-graphs" / "commit-graph-chain"
    ).is_file()


def test_get_log_page_pagination_detached_and_unborn(tmp_path: Path) -> None:
    empty = _init_repo(tmp_path / "empty_log", empty=True)
    empty_handle = engine.open_repo(empty)
    assert engine.get_log_page(empty_handle, limit=10) == LogPage(
        commits=(), next_cursor_sha=None, has_more=False, scanned_count=0
    )

    repo_path = _init_repo(tmp_path / "history_repo", empty=True)
    r = pygit2.Repository(str(repo_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1_700_000_000, 0)
    parents: list[pygit2.Oid] = []
    expected_shas: list[str] = []
    for idx in range(12):
        tb = r.TreeBuilder()
        blob_oid = r.create_blob(f"commit {idx}\n".encode())
        tb.insert("file.txt", blob_oid, pygit2.GIT_FILEMODE_BLOB)
        tree_oid = tb.write()
        oid = r.create_commit(
            "refs/heads/main",
            sig,
            sig,
            f"commit message #{idx:02d}",
            tree_oid,
            parents,
        )
        parents = [oid]
        expected_shas.append(str(oid))

    expected_desc = list(reversed(expected_shas))
    handle = engine.open_repo(repo_path)

    # Multi-page walk reusing RepoHandle (cached walker path)
    all_seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = engine.get_log_page(handle, limit=5, cursor_sha=cursor, all_refs=True)
        pages += 1
        all_seen.extend(c.sha for c in page.commits)
        if not page.has_more:
            assert page.next_cursor_sha is None
            break
        assert page.next_cursor_sha == page.commits[-1].sha
        cursor = page.next_cursor_sha

    assert pages == 3
    assert all_seen == expected_desc

    # Fresh RepoHandle per page (walker miss seek path) + filter + detached HEAD
    _git(repo_path, "checkout", "--detach", expected_desc[0])
    handle2 = engine.open_repo(repo_path)
    p1 = engine.get_log_page(handle2, limit=4)
    handle3 = engine.open_repo(repo_path)
    p2 = engine.get_log_page(handle3, limit=4, cursor_sha=p1.next_cursor_sha)
    assert [c.sha for c in p1.commits + p2.commits] == expected_desc[:8]

    filtered = engine.get_log_page(
        handle3,
        LogFilter(message_substring="#05"),
        limit=10,
    )
    assert len(filtered.commits) == 1
    assert "#05" in filtered.commits[0].message


def test_large_50k_line_diff_truncation_and_binary_guard(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "diff_repo")
    big_file = repo / "huge.txt"
    big_file.write_text("".join(f"line-{i:06d}\n" for i in range(52000)), encoding="utf-8")
    bin_file = repo / "blob.bin"
    bin_file.write_bytes(b"\x00\x01\x02\xff\xfe\xfd\x00binary")
    _git(repo, "add", "huge.txt", "blob.bin")
    _git(repo, "commit", "-m", "add huge text and binary")

    handle = engine.open_repo(repo)
    sha = _git(repo, "rev-parse", "HEAD")

    capped = engine.get_commit_diff(handle, sha, "huge.txt", max_lines=5000)
    assert capped.is_binary is False
    assert capped.is_truncated is True
    assert capped.total_lines >= 52000
    assert capped.truncated_reason is not None
    assert sum(len(h.lines) for h in capped.hunks) == 5000

    binary_diff = engine.get_commit_diff(handle, sha, "blob.bin", max_lines=5000)
    assert binary_diff.is_binary is True
    assert binary_diff.hunks == []

    # Working tree staged/unstaged cap
    big_file.write_text("".join(f"mod-{i:06d}\n" for i in range(52000)), encoding="utf-8")
    wt_capped = engine.get_diff(handle, "huge.txt", staged=False, max_lines=100)
    assert wt_capped.is_truncated is True
    assert sum(len(h.lines) for h in wt_capped.hunks) == 100
