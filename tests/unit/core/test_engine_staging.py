"""Unit tests for core/engine.py façade and staging operations."""

import pytest

from wrench.core import engine
from wrench.core.exceptions import BinaryFileStagingError, WrenchRepoNotFoundError


class TestEngineFacade:
    def test_open_nonexistent_repo_raises(self, tmp_path):
        with pytest.raises(WrenchRepoNotFoundError):
            engine.open_repo(tmp_path / "does-not-exist")

    def test_open_valid_repo(self, simple_repo):
        handle = engine.open_repo(simple_repo.path)
        assert handle.path == simple_repo.path
        status = engine.get_status(handle)
        assert status.current_branch == "main"

    def test_list_branches(self, simple_repo):
        branches = engine.list_branches(simple_repo)
        assert "main" in branches


class TestStagingGranularity:
    def test_stage_and_unstage_file(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("modified content\n")
        status = engine.get_status(simple_repo)
        assert len(status.unstaged) == 1
        assert len(status.staged) == 0

        engine.stage_file(simple_repo, "hello.txt")
        status = engine.get_status(simple_repo)
        assert len(status.staged) == 1
        assert len(status.unstaged) == 0

        engine.unstage_file(simple_repo, "hello.txt")
        status = engine.get_status(simple_repo)
        assert len(status.staged) == 0
        assert len(status.unstaged) == 1

    def test_stage_deleted_file(self, simple_repo):
        hello_file = simple_repo.path / "hello.txt"
        hello_file.unlink()
        status = engine.get_status(simple_repo)
        assert any(f.path == "hello.txt" for f in status.unstaged)

        engine.stage_file(simple_repo, "hello.txt")
        status = engine.get_status(simple_repo)
        assert any(f.path == "hello.txt" for f in status.staged)

        # Commit deletion
        sha = engine.commit(simple_repo, "Delete hello.txt")
        assert sha is not None
        status = engine.get_status(simple_repo)
        assert len(status.staged) == 0
        assert len(status.unstaged) == 0

    def test_stage_hunk(self, simple_repo):
        # Create a file with multiple distinct hunks separated by context lines
        content = "\n".join([f"line {i}" for i in range(1, 30)]) + "\n"
        (simple_repo.path / "multi_hunk.txt").write_text(content)
        engine.stage_file(simple_repo, "multi_hunk.txt")
        engine.commit(simple_repo, "Initial multi-hunk file")

        # Modify top lines and bottom lines to create 2 hunks
        lines = [f"line {i}" for i in range(1, 30)]
        lines[1] = "line 2 MODIFIED"
        lines[25] = "line 26 MODIFIED"
        (simple_repo.path / "multi_hunk.txt").write_text("\n".join(lines) + "\n")

        diff = engine.get_diff(simple_repo, "multi_hunk.txt", staged=False)
        assert len(diff.hunks) >= 2

        # Stage only the first hunk
        engine.stage_hunk(simple_repo, "multi_hunk.txt", diff.hunks[0].id)

        # Verify: staged diff has 1 hunk, unstaged diff has 1 hunk
        staged_diff = engine.get_diff(simple_repo, "multi_hunk.txt", staged=True)
        unstaged_diff = engine.get_diff(simple_repo, "multi_hunk.txt", staged=False)

        assert len(staged_diff.hunks) == 1
        assert any("line 2 MODIFIED" in line.content for line in staged_diff.hunks[0].lines)
        assert len(unstaged_diff.hunks) == 1
        assert any("line 26 MODIFIED" in line.content for line in unstaged_diff.hunks[0].lines)

    def test_binary_file_staging_raises(self, binary_file_repo):
        (binary_file_repo.path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 100)
        with pytest.raises(BinaryFileStagingError):
            engine.stage_hunk(binary_file_repo, "image.png", "hunk-0")

    def test_discard_tracked_file(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("modified uncommitted content\n")
        status = engine.get_status(simple_repo)
        assert len(status.unstaged) == 1

        engine.discard_file(simple_repo, "hello.txt")
        status = engine.get_status(simple_repo)
        assert len(status.unstaged) == 0
        assert (simple_repo.path / "hello.txt").read_text() == "Hello, world!\n"

    def test_discard_untracked_file(self, simple_repo):
        untracked = simple_repo.path / "temp_untracked.txt"
        untracked.write_text("temporary file\n")
        status = engine.get_status(simple_repo)
        assert "temp_untracked.txt" in status.untracked

        engine.discard_file(simple_repo, "temp_untracked.txt")
        status = engine.get_status(simple_repo)
        assert "temp_untracked.txt" not in status.untracked
        assert not untracked.exists()

    def test_stash_push_and_pop(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("stash me\n")
        engine.stash_create(simple_repo, "work in progress")
        status = engine.get_status(simple_repo)
        assert len(status.unstaged) == 0

        engine.stash_pop(simple_repo, 0)
        status = engine.get_status(simple_repo)
        assert len(status.unstaged) == 1
        assert (simple_repo.path / "hello.txt").read_text() == "stash me\n"

    def test_identity_facade(self, simple_repo):
        engine.set_identity(simple_repo, "Test User", "test@example.com")
        name, email = engine.check_identity(simple_repo)
        assert name == "Test User"
        assert email == "test@example.com"

    def test_reflog_and_restore_facade(self, simple_repo):
        (simple_repo.path / "first.txt").write_text("first\n")
        engine.stage_file(simple_repo, "first.txt")
        sha1 = engine.commit(simple_repo, "First commit")

        (simple_repo.path / "second.txt").write_text("second\n")
        engine.stage_file(simple_repo, "second.txt")
        engine.commit(simple_repo, "Second commit")

        entries = engine.get_reflog(simple_repo)
        assert len(entries) >= 2

        engine.restore_to_ref(simple_repo, sha1)
        status = engine.get_status(simple_repo)
        assert status.head_sha == sha1
