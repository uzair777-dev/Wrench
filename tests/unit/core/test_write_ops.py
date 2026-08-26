"""Unit tests for git write operations (core/write_ops.py)."""

import pytest

from wrench.core import write_ops
from wrench.core.exceptions import (
    BranchAlreadyExistsError,
    BranchNotFullyMergedError,
    EmptyCommitMessageError,
)


class TestCommit:
    def test_empty_commit_message_raises(self, simple_repo):
        with pytest.raises(EmptyCommitMessageError):
            write_ops.commit(simple_repo.path, "")
        with pytest.raises(EmptyCommitMessageError):
            write_ops.commit(simple_repo.path, "   \n\t  ")

    def test_commit_creates_new_commit(self, simple_repo):
        # Stage a new change
        (simple_repo.path / "hello.txt").write_text("Modified text\n")
        simple_repo.pygit2_repo.index.add("hello.txt")
        simple_repo.pygit2_repo.index.write()

        sha = write_ops.commit(simple_repo.path, "Add modified text")
        assert len(sha) == 40
        assert str(simple_repo.pygit2_repo.head.target) == sha

    def test_amend_commit(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("Amended text\n")
        simple_repo.pygit2_repo.index.add("hello.txt")
        simple_repo.pygit2_repo.index.write()

        amended_sha = write_ops.commit(simple_repo.path, "Amended message", amend=True)
        head_commit = simple_repo.pygit2_repo.head.peel()
        assert str(head_commit.id) == amended_sha
        assert head_commit.message.strip() == "Amended message"


class TestBranches:
    def test_create_and_switch_branch(self, simple_repo):
        write_ops.create_branch(simple_repo.path, "feature-x")
        assert "feature-x" in simple_repo.pygit2_repo.branches.local

        write_ops.switch_branch(simple_repo.path, "feature-x")
        assert simple_repo.pygit2_repo.head.shorthand == "feature-x"

    def test_create_duplicate_branch_raises(self, simple_repo):
        write_ops.create_branch(simple_repo.path, "feature-dup")
        with pytest.raises(BranchAlreadyExistsError):
            write_ops.create_branch(simple_repo.path, "feature-dup")

    def test_rename_branch(self, simple_repo):
        write_ops.create_branch(simple_repo.path, "old-name")
        write_ops.rename_branch(simple_repo.path, "old-name", "new-name")
        assert "new-name" in simple_repo.pygit2_repo.branches.local
        assert "old-name" not in simple_repo.pygit2_repo.branches.local

    def test_delete_branch_merged(self, simple_repo):
        write_ops.create_branch(simple_repo.path, "to-delete")
        write_ops.delete_branch(simple_repo.path, "to-delete")
        assert "to-delete" not in simple_repo.pygit2_repo.branches.local

    def test_delete_unmerged_branch_requires_force(self, simple_repo):
        write_ops.create_branch(simple_repo.path, "unmerged-branch")
        write_ops.switch_branch(simple_repo.path, "unmerged-branch")

        (simple_repo.path / "unmerged.txt").write_text("unmerged")
        simple_repo.pygit2_repo.index.add("unmerged.txt")
        simple_repo.pygit2_repo.index.write()
        write_ops.commit(simple_repo.path, "Unmerged commit")

        write_ops.switch_branch(simple_repo.path, "main")

        with pytest.raises(BranchNotFullyMergedError):
            write_ops.delete_branch(simple_repo.path, "unmerged-branch", force=False)

        # Deleting with force=True succeeds
        write_ops.delete_branch(simple_repo.path, "unmerged-branch", force=True)
        assert "unmerged-branch" not in simple_repo.pygit2_repo.branches.local


class TestStash:
    def test_stash_push_apply_drop(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("Uncommitted work\n")

        stash_id = write_ops.stash_push(simple_repo.path, "my stash")
        assert stash_id == "stash@{0}"
        # File should be restored to clean state
        assert (simple_repo.path / "hello.txt").read_text() == "Hello, world!\n"

        write_ops.stash_apply(simple_repo.path, stash_id)
        assert (simple_repo.path / "hello.txt").read_text() == "Uncommitted work\n"

        write_ops.stash_drop(simple_repo.path, stash_id)
