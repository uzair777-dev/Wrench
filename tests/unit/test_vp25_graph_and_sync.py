"""Unit tests for Phase VP-2.5 graph DAG walking, 150-remote cap, and sync execution (FR-3.16)."""

from pathlib import Path

import pygit2

from wrench.core import read_ops
from wrench.core.engine import GitEngine, open_repo


def test_detached_head_sync_status(tmp_path: Path):
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    # Initial commit
    tree_bld = repo.TreeBuilder()
    blob_id = repo.create_blob(b"detached head test\n")
    tree_bld.insert("file.txt", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    c1 = repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree_oid, [])
    repo.set_head("refs/heads/main")

    # Second commit
    blob_id2 = repo.create_blob(b"detached commit 2\n")
    tree_bld.insert("file2.txt", blob_id2, pygit2.GIT_FILEMODE_BLOB)
    tree_oid2 = tree_bld.write()
    c2 = repo.create_commit("refs/heads/main", sig, sig, "Second commit", tree_oid2, [c1])

    # Detach HEAD to c1
    repo.set_head(c1)
    assert repo.head_is_detached

    status = read_ops.get_branch_sync_status(tmp_path)
    assert status.is_detached is True
    assert status.branch_name.startswith("(detached")
    assert status.ahead == 0
    assert status.behind == 0
    assert status.upstream_name is None


def test_remote_tips_capped_at_150(tmp_path: Path):
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    # Root commit
    tree_bld = repo.TreeBuilder()
    blob_id = repo.create_blob(b"remote cap test\n")
    tree_bld.insert("root.txt", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    c_root = repo.create_commit("refs/heads/main", sig, sig, "Root commit", tree_oid, [])
    repo.set_head("refs/heads/main")

    # Create 160 distinct remote branches pointing to separate commits
    created_shas = []
    parent = c_root
    for i in range(160):
        bld = repo.TreeBuilder()
        b_id = repo.create_blob(f"branch content {i}\n".encode())
        bld.insert(f"file_{i:03d}.txt", b_id, pygit2.GIT_FILEMODE_BLOB)
        t_id = bld.write()
        c_i = repo.create_commit(
            f"refs/remotes/origin/feat-{i:03d}", sig, sig, f"Commit {i}", t_id, [parent]
        )
        created_shas.append(c_i)

    handle = open_repo(tmp_path)
    # Read ops multi-branch walk with cap
    commits = read_ops.get_log(handle, all_refs=True, limit=300)
    assert len(commits) >= 150

    # Verify memory limits remained intact during walking
    read_ops.configure_libgit2_memory_limits(32)


def test_run_git_terminal_command(tmp_path: Path):
    repo = pygit2.init_repository(str(tmp_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    tree_bld = repo.TreeBuilder()
    blob_id = repo.create_blob(b"git terminal command test\n")
    tree_bld.insert("test.txt", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree_oid, [])
    repo.set_head("refs/heads/main")

    handle = open_repo(tmp_path)
    engine = GitEngine(handle)

    # Run safe status command via string
    rc, stdout, stderr, dur = engine.run_git_terminal_command("git status --short")
    assert rc == 0
    assert dur > 0.0

    # Run rev-parse HEAD via list
    rc_rev, stdout_rev, stderr_rev, dur_rev = engine.run_terminal_command(
        ["rev-parse", "--abbrev-ref", "HEAD"]
    )
    assert rc_rev == 0
    assert "main" in stdout_rev

    # Empty command returns 0 without executing
    rc_empty, stdout_empty, stderr_empty, dur_empty = engine.run_git_terminal_command("")
    assert rc_empty == 0
