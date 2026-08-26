"""Unit tests for core/read_ops.py — pygit2-backed read operations."""

from wrench.core import read_ops


class TestGetStatus:
    def test_empty_repo_has_branch_name(self, empty_repo):
        status = read_ops.get_status(empty_repo)
        assert status.current_branch is not None  # e.g. "main" or "master"
        assert status.is_detached is False
        assert status.staged == []
        assert status.unstaged == []
        assert status.untracked == []

    def test_detached_head(self, detached_head_repo):
        status = read_ops.get_status(detached_head_repo)
        assert status.is_detached is True
        assert status.current_branch is None
        assert status.detached_head_sha is not None

    def test_untracked_file(self, simple_repo):
        (simple_repo.path / "new_file.txt").write_text("new content\n")
        status = read_ops.get_status(simple_repo)
        assert "new_file.txt" in status.untracked

    def test_modified_file(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("changed!\n")
        status = read_ops.get_status(simple_repo)
        assert len(status.unstaged) == 1
        assert status.unstaged[0].path == "hello.txt"
        assert status.unstaged[0].change_type == "modified"


class TestGetLog:
    def test_empty_repo_returns_empty(self, empty_repo):
        commits = read_ops.get_log(empty_repo)
        assert commits == []

    def test_returns_commits_in_order(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo)
        assert len(commits) == 3
        assert commits[0].message == "Third commit"
        assert commits[2].message == "First commit"

    def test_limit_works(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo, limit=2)
        assert len(commits) == 2

    def test_parent_shas_populated(self, multi_commit_repo):
        commits = read_ops.get_log(multi_commit_repo)
        assert len(commits[0].parent_shas) == 1
        assert len(commits[2].parent_shas) == 0


class TestGetDiff:
    def test_binary_file_marked_as_binary(self, binary_file_repo):
        (binary_file_repo.path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff" * 100)
        diff = read_ops.get_diff(binary_file_repo, "image.png", staged=False)
        assert diff.is_binary is True
        assert diff.hunks == []

    def test_text_file_diff(self, simple_repo):
        (simple_repo.path / "hello.txt").write_text("Hello, world!\nLine 2\n")
        diff = read_ops.get_diff(simple_repo, "hello.txt", staged=False)
        assert diff.is_binary is False
        assert len(diff.hunks) == 1
        assert any(line.origin == "+" and "Line 2" in line.content for line in diff.hunks[0].lines)


class TestBlame:
    def test_blame_file(self, multi_commit_repo):
        lines = read_ops.blame_file(multi_commit_repo, "file.txt")
        assert len(lines) == 3
        assert lines[0].line_content == "line1"
        assert lines[1].line_content == "line2"
        assert lines[2].line_content == "line3"
