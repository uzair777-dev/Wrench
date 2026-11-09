"""Unit tests for StageHookModificationsAndRetryAction and RunPreCommitFixAction."""

import subprocess
from unittest.mock import patch

import pygit2

from wrench.core.engine import RepoHandle
from wrench.core.recovery.actions import (
    RunPreCommitFixAction,
    StageHookModificationsAndRetryAction,
)


class TestStageHookModificationsAndRetryAction:
    def test_stage_and_commit_success_preserves_message(self, simple_repo: RepoHandle) -> None:
        file_path = simple_repo.path / "hello.txt"
        file_path.write_text("Hello, formatted world!\n")

        action = StageHookModificationsAndRetryAction()
        res = action.execute(
            simple_repo.path,
            context={"message": "feat(lifecycle): automatic hook retry"},
        )

        assert res.success is True
        assert "Files re-staged and commit completed successfully!" in res.message

        # Verify commit exists on head with exact message
        head_commit = simple_repo.pygit2_repo.head.peel()
        assert head_commit.message.strip() == "feat(lifecycle): automatic hook retry"

        # Verify working tree and index are clean
        status = simple_repo.pygit2_repo.status()
        assert len(status) == 0

    def test_stage_without_commit_message_returns_ready_to_commit(
        self, simple_repo: RepoHandle
    ) -> None:
        file_path = simple_repo.path / "hello.txt"
        file_path.write_text("Hello, uncommitted formatting!\n")

        action = StageHookModificationsAndRetryAction()
        res = action.execute(simple_repo.path, context={})

        assert res.success is True
        assert "Formatted files re-staged in index. Ready to commit." in res.message

        # The modification must be staged in the git index
        status = simple_repo.pygit2_repo.status()
        assert "hello.txt" in status
        assert status["hello.txt"] & pygit2.GIT_STATUS_INDEX_MODIFIED

    def test_stage_git_add_failure_returns_action_failure(self, simple_repo: RepoHandle) -> None:
        action = StageHookModificationsAndRetryAction()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["git", "add", "-u"], stderr="fatal: unable to write new index file"
            )
            res = action.execute(simple_repo.path, context={"message": "fix: retry"})

        assert res.success is False
        assert "Failed to stage formatted working-tree files" in res.message
        assert res.error is not None

    def test_stage_success_but_commit_retry_fails(self, simple_repo: RepoHandle) -> None:
        file_path = simple_repo.path / "hello.txt"
        file_path.write_text("Hello, still failing lint!\n")

        action = StageHookModificationsAndRetryAction()

        orig_run = subprocess.run

        def side_effect(cmd, *args, **kwargs):
            if cmd[0] == "git" and cmd[1] == "commit":
                raise subprocess.CalledProcessError(1, cmd, stderr="hook failed: syntax error")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=side_effect):
            res = action.execute(simple_repo.path, context={"message": "feat: should fail hook"})

        assert res.success is False
        assert "Files re-staged, but committing still failed" in res.message
        assert "hook failed: syntax error" in (res.error or "")

    def test_stage_commit_unexpected_exception(self, simple_repo: RepoHandle) -> None:
        file_path = simple_repo.path / "hello.txt"
        file_path.write_text("Hello, unexpected error!\n")

        action = StageHookModificationsAndRetryAction()

        orig_run = subprocess.run

        def side_effect(cmd, *args, **kwargs):
            if cmd[0] == "git" and cmd[1] == "commit":
                raise OSError("Disk full or permission denied")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=side_effect):
            res = action.execute(simple_repo.path, context={"message": "feat: should crash"})

        assert res.success is False
        assert "Unexpected error retrying commit" in res.message
        assert "Disk full or permission denied" in (res.error or "")


class TestRunPreCommitFixAction:
    def test_run_pre_commit_fix_with_precommit_binary(self, simple_repo: RepoHandle) -> None:
        venv_bin = simple_repo.path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        fake_precommit = venv_bin / "pre-commit"
        fake_precommit.write_text("#!/bin/sh\necho 'fixing...' >&2\nexit 0\n", encoding="utf-8")
        fake_precommit.chmod(0o755)

        (simple_repo.path / "hello.txt").write_text("Fixed content\n")

        action = RunPreCommitFixAction()
        res = action.execute(simple_repo.path)

        assert res.success is True
        assert "pre-commit" in res.message
        assert "re-staged modified files" in res.message

        status = simple_repo.pygit2_repo.status()
        assert status["hello.txt"] & pygit2.GIT_STATUS_INDEX_MODIFIED

    def test_run_pre_commit_fix_with_ruff_fallback(self, simple_repo: RepoHandle) -> None:
        venv_bin = simple_repo.path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        fake_ruff = venv_bin / "ruff"
        fake_ruff.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_ruff.chmod(0o755)

        (simple_repo.path / "hello.txt").write_text("Ruff fixed content\n")

        # Mock find_project_binary so pre-commit is not found, but ruff is
        with patch("wrench.core.recovery.actions.find_project_binary") as mock_find:

            def find_side_effect(repo_path, tool_name):
                if tool_name == "pre-commit":
                    return None
                if tool_name == "ruff":
                    return fake_ruff
                return None

            mock_find.side_effect = find_side_effect

            action = RunPreCommitFixAction()
            res = action.execute(simple_repo.path)

        assert res.success is True
        assert "ruff check --fix" in res.message
        assert "re-staged modified files" in res.message

    def test_run_pre_commit_fix_git_add_failure(self, simple_repo: RepoHandle) -> None:
        action = RunPreCommitFixAction()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, ["git", "add", "-u"], stderr="fatal: lockfile exists"
            )
            res = action.execute(simple_repo.path)

        assert res.success is False
        assert "Ran auto-fixes, but failed to re-stage modified files" in res.message
        assert res.error is not None

    def test_run_pre_commit_fix_no_tools_found_stages_existing(
        self, simple_repo: RepoHandle
    ) -> None:
        # Mock find_project_binary to return None for all linters
        with patch("wrench.core.recovery.actions.find_project_binary", return_value=None):
            (simple_repo.path / "hello.txt").write_text("Unstaged change\n")

            action = RunPreCommitFixAction()
            res = action.execute(simple_repo.path)

        assert res.success is True
        assert "Ready to commit" in res.message

        status = simple_repo.pygit2_repo.status()
        assert status["hello.txt"] & pygit2.GIT_STATUS_INDEX_MODIFIED
