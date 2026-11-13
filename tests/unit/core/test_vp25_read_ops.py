"""Unit tests for Phase VP-2.5 multi-branch DAG walk and sync metadata (FR-3.16)."""

from pathlib import Path

import pygit2

from wrench.core import read_ops
from wrench.core.engine import GitEngine, open_repo
from wrench.core.models import BranchSyncStatus, RefSidebarTree


def test_libgit2_memory_limits():
    read_ops.configure_libgit2_memory_limits(32)
    # Re-call to verify idempotent safety
    read_ops.configure_libgit2_memory_limits(32)


def test_branch_sync_status_empty_unborn_repo(tmp_path: Path):
    pygit2.init_repository(str(tmp_path))
    status = read_ops.get_branch_sync_status(tmp_path)
    assert isinstance(status, BranchSyncStatus)
    assert status.ahead == 0
    assert status.behind == 0
    assert status.upstream_name is None
    assert status.is_detached is False

    tree = read_ops.get_ref_sidebar_tree(tmp_path)
    assert isinstance(tree, RefSidebarTree)
    assert len(tree.local_branches) == 0


def test_multi_branch_and_remote_walk_and_sync(tmp_path: Path):
    # Setup origin repo
    origin_path = tmp_path / "origin"
    origin_repo = pygit2.init_repository(str(origin_path))
    sig = pygit2.Signature("Dev", "dev@example.com", 1700000000, 0)

    # Initial commit on origin main
    tree_bld = origin_repo.TreeBuilder()
    blob_id = origin_repo.create_blob(b"hello origin\n")
    tree_bld.insert("file.txt", blob_id, pygit2.GIT_FILEMODE_BLOB)
    tree_oid = tree_bld.write()
    c1 = origin_repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree_oid, [])
    origin_repo.set_head("refs/heads/main")

    # Second commit on origin main
    blob_id2 = origin_repo.create_blob(b"hello origin v2\n")
    tree_bld.insert("file.txt", blob_id2, pygit2.GIT_FILEMODE_BLOB)
    tree_oid2 = tree_bld.write()
    c2 = origin_repo.create_commit(
        "refs/heads/main", sig, sig, "Origin main commit 2", tree_oid2, [c1]
    )

    # Branch off origin: origin/assets/pr-10949
    c_pr = origin_repo.create_commit(
        "refs/heads/assets/pr-10949", sig, sig, "PR 10949 work", tree_oid2, [c1]
    )

    # Tag v1.0 on c1
    origin_repo.create_tag("v1.0", c1, pygit2.GIT_OBJECT_COMMIT, sig, "Release v1.0")

    # Clone to local repo
    local_path = tmp_path / "local"
    local_repo = pygit2.clone_repository(str(origin_path), str(local_path))

    # Reset local main back to c1 so local main is 1 commit behind origin/main
    local_main = local_repo.branches.local["main"]
    local_main.set_target(c1)

    # Add a local-only commit on local main so local is 1 ahead, 1 behind
    blob_local = local_repo.create_blob(b"local divergence\n")
    tree_bld_loc = local_repo.TreeBuilder()
    tree_bld_loc.insert("local.txt", blob_local, pygit2.GIT_FILEMODE_BLOB)
    tree_oid_loc = tree_bld_loc.write()
    c_loc = local_repo.create_commit(
        "refs/heads/main", sig, sig, "Local commit on main", tree_oid_loc, [c1]
    )

    # 1. Test get_branch_sync_status
    status = read_ops.get_branch_sync_status(local_path)
    assert status.branch_name == "main"
    assert status.upstream_name == "origin/main"
    assert status.ahead == 1
    assert status.behind == 1
    assert status.is_detached is False

    # 2. Test get_ref_sidebar_tree
    tree = read_ops.get_ref_sidebar_tree(local_path)
    local_names = [b.name for b in tree.local_branches]
    assert "main" in local_names
    remote_names = [b.name for b in tree.remote_branches]
    assert "origin/main" in remote_names
    assert "origin/assets/pr-10949" in remote_names
    assert not any(n.endswith("/HEAD") for n in remote_names)
    tag_names = [t.name for t in tree.tags]
    assert "v1.0" in tag_names

    # 3. Test multi-branch walking with all_refs=True
    handle = open_repo(local_path)
    commits = read_ops.get_log(handle, all_refs=True, limit=100)
    commit_shas = {c.sha for c in commits}
    assert str(c_loc) in commit_shas
    assert str(c2) in commit_shas
    assert str(c_pr) in commit_shas
    assert str(c1) in commit_shas

    # 4. Test get_ref_labels
    labels_map = read_ops.get_ref_labels(handle)
    all_label_names = [lbl.name for lst in labels_map.values() for lbl in lst]
    assert "local:main" in all_label_names or "main" in all_label_names
    assert "remote:origin/main" in all_label_names
    assert "remote:origin/assets/pr-10949" in all_label_names
    assert "remote:origin/HEAD" not in all_label_names

    # 5. Test GitEngine facade methods
    engine = GitEngine(handle)
    eng_status = engine.get_branch_sync_status()
    assert eng_status.ahead == 1
    assert eng_status.behind == 1
    eng_tree = engine.get_ref_sidebar_tree()
    assert len(eng_tree.local_branches) >= 1
