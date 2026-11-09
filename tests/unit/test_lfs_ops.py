"""Unit tests for Git LFS operations (lfs_ops.py)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wrench.core.engine import GitEngine, commit, init_repo, open_repo, stage_file
from wrench.core.exceptions import LfsUnavailableError
from wrench.core.lfs_ops import (
    _require_lfs,
    _reset_lfs_cache,
    is_lfs_installed,
    is_lfs_pointer,
    lfs_available,
    lfs_files,
    lfs_pull,
    lfs_push,
    lfs_status,
    lfs_track,
    lfs_untrack,
    parse_lfs_pointer,
)

SAMPLE_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    "oid sha256:4d7a214614ab2935c943f9e0ff69d22ecd543a79b39fc813087da0960bc07fa5\n"
    "size 12345\n"
)


def test_is_lfs_pointer_detection():
    # Valid pointer
    assert is_lfs_pointer(SAMPLE_POINTER) is True

    # Empty and whitespace
    assert is_lfs_pointer("") is False
    assert is_lfs_pointer("   \n  ") is False

    # Partial / near-miss headers
    assert is_lfs_pointer("version 1.0") is False
    assert is_lfs_pointer("version https://git-lfs.github.com/spec/v2") is False
    assert is_lfs_pointer("something else\nversion https://git-lfs.github.com/spec/v1") is False


def test_parse_lfs_pointer():
    parsed = parse_lfs_pointer(SAMPLE_POINTER)
    assert parsed is not None
    oid, size = parsed
    assert oid == "4d7a214614ab2935c943f9e0ff69d22ecd543a79b39fc813087da0960bc07fa5"
    assert size == "12345"

    # Non-pointer
    assert parse_lfs_pointer("regular file text") is None

    # Pointer with missing size
    malformed = "version https://git-lfs.github.com/spec/v1\noid sha256:abcd\n"
    assert parse_lfs_pointer(malformed) is None


def test_lfs_probe_caching():
    _reset_lfs_cache()

    with patch("wrench.core.lfs_ops.run_git") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert is_lfs_installed() is True
        assert lfs_available() is True
        # Cached: run_git should have been called only once
        assert mock_run.call_count == 1

        assert is_lfs_installed() is True
        assert mock_run.call_count == 1

    _reset_lfs_cache()
    with patch("wrench.core.lfs_ops.run_git") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert is_lfs_installed() is False
        assert mock_run.call_count == 1


def test_require_lfs_raises_when_unavailable():
    _reset_lfs_cache()
    with patch("wrench.core.lfs_ops.is_lfs_installed", return_value=False):
        with pytest.raises(LfsUnavailableError) as exc_info:
            _require_lfs()
        assert "not installed" in str(exc_info.value)


def test_lfs_files_and_status_in_real_repo(tmp_path: Path):
    # Initialize a real git repo
    repo_path = tmp_path / "lfs_test_repo"
    repo_path.mkdir()
    init_repo(repo_path)
    repo = open_repo(repo_path)
    repo.pygit2_repo.config["user.name"] = "Test User"
    repo.pygit2_repo.config["user.email"] = "test@example.com"

    # Disable filter invocation when git-lfs binary is absent in test environment
    from wrench.core.write_ops import run_git

    run_git(repo_path, ["config", "--local", "filter.lfs.required", "false"])
    run_git(repo_path, ["config", "--local", "filter.lfs.clean", ""])
    run_git(repo_path, ["config", "--local", "filter.lfs.smudge", ""])
    run_git(repo_path, ["config", "--local", "filter.lfs.process", ""])

    # Write .gitattributes tracking *.bin
    gitattrs = repo_path / ".gitattributes"
    gitattrs.write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")

    # Write a pointer file and a regular file
    bin_file = repo_path / "archive.bin"
    bin_file.write_text(SAMPLE_POINTER, encoding="utf-8")

    txt_file = repo_path / "notes.txt"
    txt_file.write_text("just normal text\n", encoding="utf-8")

    # Stage and commit
    stage_file(repo, ".gitattributes")
    stage_file(repo, "archive.bin")
    stage_file(repo, "notes.txt")
    commit(repo, "Add LFS pointer file and notes")

    # Test lfs_files detection via git check-attr
    paths = ["archive.bin", "notes.txt", "untracked.bin"]
    tracked = lfs_files(repo, paths)
    assert "archive.bin" in tracked
    assert "untracked.bin" in tracked
    assert "notes.txt" not in tracked

    # Test lfs_status
    statuses = lfs_status(repo)
    assert len(statuses) >= 1
    archive_status = next((s for s in statuses if s.path == "archive.bin"), None)
    assert archive_status is not None
    assert archive_status.is_pointer is True
    assert archive_status.oid == "4d7a214614ab2935c943f9e0ff69d22ecd543a79b39fc813087da0960bc07fa5"
    assert archive_status.size == 12345

    # Test GitEngine facade
    engine = GitEngine(repo)
    engine_tracked = engine.lfs_files(["archive.bin", "notes.txt"])
    assert "archive.bin" in engine_tracked
    assert "notes.txt" not in engine_tracked

    engine_statuses = engine.lfs_status()
    assert len(engine_statuses) == len(statuses)
    assert GitEngine.is_lfs_pointer(SAMPLE_POINTER) is True
    assert GitEngine.parse_lfs_pointer(SAMPLE_POINTER) is not None


def test_lfs_track_and_ops_mocked(tmp_path: Path):
    repo_path = tmp_path / "mock_repo"
    repo_path.mkdir()
    init_repo(repo_path)
    repo = open_repo(repo_path)
    repo.pygit2_repo.config["user.name"] = "Test User"
    repo.pygit2_repo.config["user.email"] = "test@example.com"

    with patch("wrench.core.lfs_ops.is_lfs_installed", return_value=True):
        with patch("wrench.core.lfs_ops.run_git") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="")

            lfs_track(repo, "*.psd")
            mock_run.assert_called_with(repo.path, ["lfs", "track", "--", "*.psd"])

            lfs_untrack(repo, "*.psd")
            mock_run.assert_called_with(repo.path, ["lfs", "untrack", "--", "*.psd"])

            lfs_pull(repo)
            mock_run.assert_called_with(repo.path, ["lfs", "pull"], timeout=600)

            lfs_push(repo, remote="origin")
            # repo has a head branch (e.g. master or main)
            mock_run.assert_called()
            args = mock_run.call_args[0][1]
            assert args[0:3] == ["lfs", "push", "origin"]
