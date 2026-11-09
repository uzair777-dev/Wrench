"""Unit tests for Git submodule operations (submodules.py)."""

from pathlib import Path

import pytest

from wrench.core.engine import GitEngine, commit, init_repo, open_repo, stage_file
from wrench.core.submodules import (
    add_submodule,
    init_submodule,
    list_submodules,
    submodule_status,
    sync_submodules,
    update_submodules,
)
from wrench.core.write_ops import run_git


@pytest.fixture
def child_repo(tmp_path: Path):
    child_path = tmp_path / "child_repo"
    child_path.mkdir()
    init_repo(child_path)
    repo = open_repo(child_path)
    repo.pygit2_repo.config["user.name"] = "Test User"
    repo.pygit2_repo.config["user.email"] = "test@example.com"

    readme = child_path / "README.md"
    readme.write_text("# Child Repo\n", encoding="utf-8")
    stage_file(repo, "README.md")
    commit(repo, "Initial child commit")
    return repo


@pytest.fixture
def parent_repo(tmp_path: Path):
    parent_path = tmp_path / "parent_repo"
    parent_path.mkdir()
    init_repo(parent_path)
    repo = open_repo(parent_path)
    repo.pygit2_repo.config["user.name"] = "Test User"
    repo.pygit2_repo.config["user.email"] = "test@example.com"

    readme = parent_path / "README.md"
    readme.write_text("# Parent Repo\n", encoding="utf-8")
    stage_file(repo, "README.md")
    commit(repo, "Initial parent commit")
    return repo


def test_submodules_in_repo_without_submodules(parent_repo):
    # No .gitmodules file exists
    submodules = list_submodules(parent_repo)
    assert submodules == []

    # Probing status for nonexistent submodule returns clean uninitialized status without raising
    status = submodule_status(parent_repo, "nonexistent")
    assert status.path == "nonexistent"
    assert status.is_dirty is False


def test_add_and_list_submodules(parent_repo, child_repo):
    child_url = f"file://{child_repo.path}"
    add_submodule(parent_repo, child_url, "libs/child")

    submodules = list_submodules(parent_repo)
    assert len(submodules) == 1
    sm = submodules[0]
    assert sm.path == "libs/child"
    assert "child_repo" in sm.url
    assert sm.initialized is True

    # Check status
    stat = submodule_status(parent_repo, "libs/child")
    assert stat.path == "libs/child"
    assert len(stat.current_commit) == 40
    assert stat.is_dirty is False

    # Check dirty status if file added inside submodule
    dirty_file = Path(parent_repo.path) / "libs/child" / "dirty.txt"
    dirty_file.write_text("unsaved change\n", encoding="utf-8")
    stat_dirty = submodule_status(parent_repo, "libs/child")
    assert stat_dirty.is_dirty is True

    # Test sync and update
    sync_submodules(parent_repo)
    update_submodules(parent_repo, path="libs/child")

    # Test GitEngine facade methods
    engine = GitEngine(parent_repo)
    assert len(engine.list_submodules()) == 1
    engine_stat = engine.submodule_status("libs/child")
    assert engine_stat.path == "libs/child"


def test_uninitialized_submodule_lifecycle(tmp_path: Path, parent_repo, child_repo):
    # Add submodule in parent and commit
    child_url = f"file://{child_repo.path}"
    add_submodule(parent_repo, child_url, "vendor/sub")
    stage_file(parent_repo, ".gitmodules")
    stage_file(parent_repo, "vendor/sub")
    commit(parent_repo, "Add vendor/sub submodule")

    # Clone parent to a new location without --recurse-submodules
    clone_path = tmp_path / "cloned_parent"
    run_git(
        tmp_path,
        [
            "-c",
            "protocol.file.allow=always",
            "clone",
            f"file://{parent_repo.path}",
            str(clone_path),
        ],
    )
    cloned_repo = open_repo(clone_path)

    # In clean clone, submodule should be detected as uninitialized
    submodules = list_submodules(cloned_repo)
    assert len(submodules) == 1
    assert submodules[0].path == "vendor/sub"
    assert submodules[0].initialized is False

    # submodule_status must not raise on uninitialized submodule
    stat = submodule_status(cloned_repo, "vendor/sub")
    assert stat.is_dirty is False

    # Initialize via init_submodule
    init_submodule(cloned_repo, "vendor/sub")

    # Now submodule should be initialized
    submodules_after = list_submodules(cloned_repo)
    assert submodules_after[0].initialized is True
