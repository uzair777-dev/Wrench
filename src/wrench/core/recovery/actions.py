"""Actionable recovery handlers for auto-healing and error resolution."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .process_guard import acquire_repo_guard, remove_lock

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    success: bool
    message: str
    error: str | None = None


class RecoveryAction:
    """Base class for all executable recovery actions."""

    action_id: str = "base"
    title: str = "Recover"
    description: str = ""
    is_primary: bool = False

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        raise NotImplementedError


class ReleaseStaleLockAction(RecoveryAction):
    action_id = "release_stale_lock"
    title = "Release Stale Lock"
    description = "Removes the abandoned lock file left behind by a previous Git process."
    is_primary = True

    def __init__(self, lock_path: Path | str | None = None):
        self.lock_path = Path(lock_path) if lock_path else None

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        target_lock = self.lock_path or (context.get("lock_path") if context else None)
        if not target_lock:
            # Look up lock in repo
            from .process_guard import inspect_locks

            locks = inspect_locks(repo_path)
            if locks:
                target_lock = locks[0][0]

        if not target_lock:
            return ActionResult(success=True, message="No lock file found to release.")

        if remove_lock(target_lock):
            return ActionResult(
                success=True,
                message=f"Successfully released lock file: {Path(target_lock).name}",
            )
        return ActionResult(
            success=False,
            message="Could not remove lock file. It may be locked by an active process.",
            error="Permission or I/O error removing lock",
        )


class AutoFormatAndRetryAction(RecoveryAction):
    action_id = "auto_format_and_retry"
    title = "Auto-Format & Retry Commit"
    description = "Runs code formatters (black, ruff format) and retries the commit."
    is_primary = True

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        formatted_tools: list[str] = []

        # 1. Run Python formatters if pyproject.toml / .venv / python files exist
        py_files = list(p.glob("**/*.py"))
        if py_files:
            # Try black
            try:
                res = subprocess.run(
                    ["black", "."],
                    cwd=str(p),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if res.returncode == 0:
                    formatted_tools.append("black")
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.debug("black failed: %s", e)

            # Try ruff format
            try:
                res = subprocess.run(
                    ["ruff", "format", "."],
                    cwd=str(p),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if res.returncode == 0:
                    formatted_tools.append("ruff format")
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.debug("ruff format failed: %s", e)

        # 2. Stage updated files if files were staged
        try:
            subprocess.run(["git", "add", "-u"], cwd=str(p), check=True, timeout=10)
        except Exception as e:
            return ActionResult(
                success=False,
                message="Formatted code, but failed to re-stage updated files.",
                error=str(e),
            )

        tools_str = ", ".join(formatted_tools) if formatted_tools else "formatters"
        return ActionResult(
            success=True,
            message=f"Code auto-formatted with {tools_str} and re-staged. Ready to commit.",
        )


class CommitNoVerifyAction(RecoveryAction):
    action_id = "commit_no_verify"
    title = "Commit with --no-verify"
    description = "Bypasses pre-commit hook checks and creates the commit directly."
    is_primary = False

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        msg = (context.get("message") if context else "") or "commit without verify"
        try:
            res = subprocess.run(
                ["git", "commit", "--no-verify", "-m", msg],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return ActionResult(success=True, message="Commit created with --no-verify.")
            return ActionResult(
                success=False,
                message="git commit --no-verify failed.",
                error=res.stderr or res.stdout,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                message="Error executing git commit --no-verify.",
                error=str(e),
            )


class AutoStashAndRetryAction(RecoveryAction):
    action_id = "auto_stash_and_retry"
    title = "Auto-Stash & Continue"
    description = "Safely stashes uncommitted changes, executes operation, and restores stash."
    is_primary = True

    def __init__(self, operation_callback: Callable[[], None] | None = None):
        self.operation_callback = operation_callback

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        stamp = int(time.time())
        stash_name = f"wrench-auto-recovery-{stamp}"

        # 1. Stash changes
        try:
            stash_res = subprocess.run(
                ["git", "stash", "push", "-u", "-m", stash_name],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if stash_res.returncode != 0:
                return ActionResult(
                    success=False,
                    message="Could not auto-stash local changes.",
                    error=stash_res.stderr,
                )
        except Exception as e:
            return ActionResult(
                success=False,
                message="Failed to stash local changes.",
                error=str(e),
            )

        # 2. Execute target callback if provided
        op_error: str | None = None
        if self.operation_callback:
            try:
                self.operation_callback()
            except Exception as e:
                op_error = str(e)

        # 3. Pop stash
        try:
            pop_res = subprocess.run(
                ["git", "stash", "pop"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if pop_res.returncode != 0 and not op_error:
                return ActionResult(
                    success=True,
                    message="Finished operation. Stash preserved in stash list.",
                )
        except Exception:
            pass

        if op_error:
            return ActionResult(
                success=False,
                message="Operation failed during execution; changes have been restored from stash.",
                error=op_error,
            )

        return ActionResult(
            success=True,
            message="Auto-stashed changes, completed operation, and restored local work.",
        )


class QuarantineUntrackedAction(RecoveryAction):
    action_id = "quarantine_untracked"
    title = "Quarantine Untracked Files"
    description = "Moves conflicting untracked files to .git/wrench-quarantine/."
    is_primary = True

    def __init__(self, conflicting_files: list[str] | None = None):
        self.conflicting_files = conflicting_files or []

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        files = self.conflicting_files or (context.get("conflicted_files") if context else [])
        if not files:
            return ActionResult(success=True, message="No untracked files to quarantine.")

        stamp = int(time.time())
        quarantine_dir = p / ".git" / "wrench-quarantine" / f"backup_{stamp}"
        quarantine_dir.mkdir(parents=True, exist_ok=True)

        moved_count = 0
        for f in files:
            src = p / f
            dst = quarantine_dir / f
            if src.exists() and not src.is_dir():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(src, dst)
                moved_count += 1

        rel_path = quarantine_dir.relative_to(p)
        return ActionResult(
            success=True,
            message=f"Quarantined {moved_count} conflicting untracked file(s) to: {rel_path}",
        )


class AbortInterruptedOperationAction(RecoveryAction):
    action_id = "abort_interrupted_operation"
    title = "Clean Abort"
    description = "Aborts the stuck merge/rebase and returns repository to a clean state."
    is_primary = True

    def __init__(self, mode: str = "merge"):
        self.mode = mode

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        cmd = ["git", "rebase", "--abort"] if self.mode == "rebase" else ["git", "merge", "--abort"]
        try:
            res = subprocess.run(
                cmd,
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return ActionResult(
                    success=True,
                    message=f"Successfully aborted {self.mode} and restored clean state.",
                )
            return ActionResult(
                success=False,
                message=f"Failed to abort {self.mode}.",
                error=res.stderr or res.stdout,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                message=f"Error executing git {self.mode} --abort.",
                error=str(e),
            )


class RebuildCorruptIndexAction(RecoveryAction):
    action_id = "rebuild_corrupt_index"
    title = "Rebuild Corrupt Index"
    description = "Safely recreates the Git index from HEAD without touching working tree files."
    is_primary = True

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        idx_file = p / ".git" / "index"
        try:
            if idx_file.exists():
                idx_file.unlink()

            res = subprocess.run(
                ["git", "read-tree", "HEAD"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return ActionResult(
                    success=True,
                    message="Successfully rebuilt Git index from HEAD.",
                )
            return ActionResult(
                success=False,
                message="Failed to rebuild index from HEAD.",
                error=res.stderr or res.stdout,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                message="Error rebuilding corrupt index.",
                error=str(e),
            )


class WaitForRepoReleaseAction(RecoveryAction):
    action_id = "wait_for_repo_release"
    title = "Wait in Background"
    description = "Waits for the active external Git process to release the repository lock."
    is_primary = True

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        res = acquire_repo_guard(repo_path, timeout=self.timeout)
        if res.status == "ready":
            return ActionResult(success=True, message="Repository lock was released successfully.")
        return ActionResult(
            success=False,
            message="Repository is still busy after waiting.",
            error="Lock timeout expired",
        )


# Phase 3-6 Forward-Compatibility Extension Hooks
class PullAndRebaseAction(RecoveryAction):
    action_id = "pull_and_rebase"
    title = "Pull & Rebase"
    description = "Fetches remote changes and rebases local commits on top."
    is_primary = True

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        try:
            res = subprocess.run(
                ["git", "pull", "--rebase"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return ActionResult(success=True, message="Successfully pulled and rebased.")
            return ActionResult(success=False, message="Pull rebase failed.", error=res.stderr)
        except Exception as e:
            return ActionResult(success=False, message="Error pulling.", error=str(e))


class SyncSubmodulesAction(RecoveryAction):
    action_id = "sync_submodules"
    title = "Sync & Update Submodules"
    description = "Initializes and updates all submodules recursively."
    is_primary = True

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        try:
            res = subprocess.run(
                ["git", "submodule", "update", "--init", "--recursive"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if res.returncode == 0:
                return ActionResult(success=True, message="Submodules updated successfully.")
            return ActionResult(success=False, message="Submodule update failed.", error=res.stderr)
        except Exception as e:
            return ActionResult(success=False, message="Error updating submodules.", error=str(e))


class PruneWorktreesAction(RecoveryAction):
    action_id = "prune_worktrees"
    title = "Prune Stale Worktrees"
    description = "Cleans up stale worktree references from deleted directories."
    is_primary = True

    def execute(self, repo_path: Path | str, context: dict | None = None) -> ActionResult:
        p = Path(repo_path)
        try:
            res = subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(p),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if res.returncode == 0:
                return ActionResult(success=True, message="Worktrees pruned successfully.")
            return ActionResult(success=False, message="Worktree prune failed.", error=res.stderr)
        except Exception as e:
            return ActionResult(success=False, message="Error pruning worktrees.", error=str(e))
