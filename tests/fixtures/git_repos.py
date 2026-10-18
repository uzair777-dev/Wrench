"""Pytest fixtures that create throwaway git repos in tmp_path."""

from pathlib import Path

import pygit2
import pytest

from wrench.core.engine import RepoHandle


@pytest.fixture
def empty_repo(tmp_path: Path) -> RepoHandle:
    """A freshly init'd repo with zero commits (unborn branch)."""
    repo_path = tmp_path / "empty-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))
    # Configure local user name/email so commits can be created if needed
    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"
    return RepoHandle(pygit2_repo, repo_path)


@pytest.fixture
def simple_repo(tmp_path: Path) -> RepoHandle:
    """A repo with one commit containing one file."""
    repo_path = tmp_path / "simple-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))

    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"

    test_file = repo_path / "hello.txt"
    test_file.write_text("Hello, world!\n")

    pygit2_repo.index.add("hello.txt")
    pygit2_repo.index.write()

    sig = pygit2.Signature("Test User", "test@example.com")
    tree = pygit2_repo.index.write_tree()
    pygit2_repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree, [])
    pygit2_repo.set_head("refs/heads/main")

    return RepoHandle(pygit2_repo, repo_path)


@pytest.fixture
def multi_commit_repo(tmp_path: Path) -> RepoHandle:
    """A repo with 3 commits for log/blame testing."""
    repo_path = tmp_path / "multi-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))
    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"
    sig = pygit2.Signature("Test User", "test@example.com")

    # Commit 1
    (repo_path / "file.txt").write_text("line1\n")
    pygit2_repo.index.add("file.txt")
    pygit2_repo.index.write()
    tree = pygit2_repo.index.write_tree()
    c1 = pygit2_repo.create_commit("refs/heads/main", sig, sig, "First commit", tree, [])
    pygit2_repo.set_head("refs/heads/main")

    # Commit 2
    (repo_path / "file.txt").write_text("line1\nline2\n")
    pygit2_repo.index.add("file.txt")
    pygit2_repo.index.write()
    tree = pygit2_repo.index.write_tree()
    c2 = pygit2_repo.create_commit("refs/heads/main", sig, sig, "Second commit", tree, [c1])

    # Commit 3
    (repo_path / "file.txt").write_text("line1\nline2\nline3\n")
    pygit2_repo.index.add("file.txt")
    pygit2_repo.index.write()
    tree = pygit2_repo.index.write_tree()
    pygit2_repo.create_commit("refs/heads/main", sig, sig, "Third commit", tree, [c2])

    return RepoHandle(pygit2_repo, repo_path)


@pytest.fixture
def detached_head_repo(tmp_path: Path) -> RepoHandle:
    """A repo in detached HEAD state."""
    repo_path = tmp_path / "detached-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))
    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"
    sig = pygit2.Signature("Test User", "test@example.com")

    (repo_path / "file.txt").write_text("content\n")
    pygit2_repo.index.add("file.txt")
    pygit2_repo.index.write()
    tree = pygit2_repo.index.write_tree()
    commit_oid = pygit2_repo.create_commit("refs/heads/main", sig, sig, "Initial commit", tree, [])
    pygit2_repo.set_head("refs/heads/main")
    pygit2_repo.set_head(commit_oid)

    return RepoHandle(pygit2_repo, repo_path)


@pytest.fixture
def binary_file_repo(tmp_path: Path) -> RepoHandle:
    """A repo with a binary file."""
    repo_path = tmp_path / "binary-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))
    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"
    sig = pygit2.Signature("Test User", "test@example.com")

    binary_file = repo_path / "image.png"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    pygit2_repo.index.add("image.png")
    pygit2_repo.index.write()
    tree = pygit2_repo.index.write_tree()
    pygit2_repo.create_commit("refs/heads/main", sig, sig, "Add binary file", tree, [])
    pygit2_repo.set_head("refs/heads/main")

    return RepoHandle(pygit2_repo, repo_path)


@pytest.fixture
def conflict_repo(tmp_path: Path) -> RepoHandle:
    """A repo with two branches ('main' and 'feature') with conflicting changes."""
    repo_path = tmp_path / "conflict-repo"
    repo_path.mkdir()
    pygit2_repo = pygit2.init_repository(str(repo_path))
    pygit2_repo.config["user.name"] = "Test User"
    pygit2_repo.config["user.email"] = "test@example.com"
    sig = pygit2.Signature("Test User", "test@example.com")

    # Base commit on main
    test_file = repo_path / "shared.txt"
    test_file.write_text("line 1\nbase content\nline 3\n")
    pygit2_repo.index.add("shared.txt")
    pygit2_repo.index.write()
    c1 = pygit2_repo.create_commit(
        "refs/heads/main", sig, sig, "Initial commit", pygit2_repo.index.write_tree(), []
    )
    pygit2_repo.set_head("refs/heads/main")

    # Branch 'feature'
    pygit2_repo.create_branch("feature", pygit2_repo[c1])

    # Commit on main
    test_file.write_text("line 1\nmain branch modification\nline 3\n")
    pygit2_repo.index.add("shared.txt")
    pygit2_repo.index.write()
    pygit2_repo.create_commit(
        "refs/heads/main", sig, sig, "Main modification", pygit2_repo.index.write_tree(), [c1]
    )

    # Commit on feature
    pygit2_repo.set_head("refs/heads/feature")
    pygit2_repo.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)
    test_file.write_text("line 1\nfeature branch modification\nline 3\n")
    pygit2_repo.index.add("shared.txt")
    pygit2_repo.index.write()
    pygit2_repo.create_commit(
        "refs/heads/feature", sig, sig, "Feature modification", pygit2_repo.index.write_tree(), [c1]
    )

    # Switch back to main
    pygit2_repo.set_head("refs/heads/main")
    pygit2_repo.checkout_head(strategy=pygit2.GIT_CHECKOUT_FORCE)

    return RepoHandle(pygit2_repo, repo_path)


def make_repo_forest(tmp_path: Path) -> tuple[Path, dict[str, set[Path] | Path]]:
    """Creates a multi-level directory tree containing various repo configurations
    for discovery testing.

    Returns (root_path, expected_dict) where expected_dict has keys:
    - 'valid': set of paths that MUST be discovered
    - 'deep': path that MUST NOT be discovered (depth > 3)
    - 'hidden': path that MUST NOT be discovered (dot-directory)
    - 'submodule': path that MUST NOT be discovered (nested inside repo root)
    - 'unreadable': unreadable directory path (skipped)
    """
    forest = tmp_path / "forest"
    forest.mkdir(exist_ok=True)

    # 1. Standard top-level repo (depth 1)
    r1 = forest / "repo1"
    r1.mkdir()
    pygit2.init_repository(str(r1))

    # 2. Nested repo inside one-level container (depth 2)
    sub = forest / "nested"
    sub.mkdir()
    r2 = sub / "repo2"
    r2.mkdir()
    pygit2.init_repository(str(r2))

    # 3. Worktree repo with a .git FILE (depth 1)
    wt = forest / "worktree1"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /fake/path/to/main/.git/worktrees/wt1\n")

    # 4. Deep repo beyond default depth cap (depth 4: forest/d1/d2/d3/repo_deep)
    deep = forest / "d1" / "d2" / "d3" / "repo_deep"
    deep.mkdir(parents=True)
    pygit2.init_repository(str(deep))

    # 5. Hidden directory repo (.hidden_repo)
    hidden = forest / ".hidden_repo"
    hidden.mkdir()
    pygit2.init_repository(str(hidden))

    # 6. Repo containing a submodule directory
    parent = forest / "parent_with_sub"
    parent.mkdir()
    pygit2.init_repository(str(parent))
    subm = parent / "submodule_repo"
    subm.mkdir()
    (subm / ".git").write_text("gitdir: ../.git/modules/submodule_repo\n")

    # 7. Symlink loop: link pointing to root
    try:
        (forest / "link_to_forest").symlink_to(forest, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass

    # 8. Unreadable directory (chmod 000)
    unreadable = forest / "unreadable_dir"
    try:
        unreadable.mkdir()
        unreadable.chmod(0o000)
    except OSError:
        pass

    valid = {r1.resolve(), r2.resolve(), wt.resolve(), parent.resolve()}
    return forest, {
        "valid": valid,
        "deep": deep.resolve(),
        "hidden": hidden.resolve(),
        "submodule": subm.resolve(),
        "unreadable": unreadable.resolve(),
    }
