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
