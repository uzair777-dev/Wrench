"""Unit tests for Git reflog operations (reflog_ops.py)."""

from pathlib import Path

import pytest

from wrench.core.engine import GitEngine, commit, init_repo, open_repo, stage_file
from wrench.core.models import ReflogEntry
from wrench.core.reflog import get_reflog
from wrench.core.reflog_ops import (
    create_branch_from_reflog,
    list_reflog,
    reset_to_reflog_entry,
)


@pytest.fixture
def repo_with_history(tmp_path: Path):
    repo_path = tmp_path / "reflog_test_repo"
    repo_path.mkdir()
    init_repo(repo_path)
    repo = open_repo(repo_path)

    f = repo_path / "file.txt"

    f.write_text("v1\n", encoding="utf-8")
    stage_file(repo, "file.txt")
    sha1 = commit(repo, "commit 1: v1")

    f.write_text("v2\n", encoding="utf-8")
    stage_file(repo, "file.txt")
    sha2 = commit(repo, "commit 2: v2")

    f.write_text("v3\n", encoding="utf-8")
    stage_file(repo, "file.txt")
    sha3 = commit(repo, "commit 3: v3")

    return repo, [sha1, sha2, sha3]


def test_list_reflog(repo_with_history):
    repo, shas = repo_with_history
    entries = list_reflog(repo, ref="HEAD", limit=50)
    assert len(entries) >= 3

    # Check entry attributes
    for e in entries:
        assert isinstance(e, ReflogEntry)
        assert len(e.sha) == 40
        assert e.timestamp != ""

    # Legacy reflog.py function check
    legacy_entries = get_reflog(repo)
    assert len(legacy_entries) >= 3


def test_reset_to_reflog_entry(repo_with_history):
    repo, shas = repo_with_history
    sha1 = shas[0]

    # Reset hard to first commit
    reset_to_reflog_entry(repo, sha1, mode="hard")

    current_head = str(repo.pygit2_repo.head.target)
    assert current_head == sha1

    file_content = (Path(repo.path) / "file.txt").read_text(encoding="utf-8")
    assert file_content == "v1\n"


def test_create_branch_from_reflog(repo_with_history):
    repo, shas = repo_with_history
    sha2 = shas[1]

    create_branch_from_reflog(repo, "recovered_feature", sha2)

    branch = repo.pygit2_repo.lookup_branch("recovered_feature")
    assert branch is not None
    assert str(branch.target) == sha2


def test_git_engine_reflog_facade(repo_with_history):
    repo, shas = repo_with_history
    engine = GitEngine(repo)

    entries = engine.list_reflog(limit=10)
    assert len(entries) >= 3

    sha2 = shas[1]
    engine.create_branch_from_reflog("engine_branch", sha2)
    assert repo.pygit2_repo.lookup_branch("engine_branch") is not None

    engine.reset_to_reflog_entry(sha2, mode="hard")
    assert str(repo.pygit2_repo.head.target) == sha2
