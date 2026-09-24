"""Smart error classifier for Git operations, hooks, locks, and corrupted states."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .actions import (
    AbortInterruptedOperationAction,
    AutoFormatAndRetryAction,
    AutoStashAndRetryAction,
    CommitNoVerifyAction,
    PullAndRebaseAction,
    QuarantineUntrackedAction,
    RebuildCorruptIndexAction,
    RecoveryAction,
    ReleaseStaleLockAction,
    WaitForRepoReleaseAction,
)


class ErrorCategory(str, Enum):
    REPO_BUSY = "repo_busy"
    HOOK_FAILURE = "hook_failure"
    STALE_LOCK = "stale_lock"
    DIRTY_TREE_COLLISION = "dirty_tree_collision"
    UNTRACKED_OVERWRITE_COLLISION = "untracked_overwrite_collision"
    INTERRUPTED_OPERATION = "interrupted_operation"
    PUSH_REJECTED = "push_rejected"
    AUTH_FAILURE = "auth_failure"
    CORRUPT_INDEX = "corrupt_index"
    STORAGE_CORRUPTION = "storage_corruption"
    GENERIC_ERROR = "generic_error"


@dataclass
class DiagnosticReport:
    category: ErrorCategory
    title: str
    description: str
    technical_details: str = ""
    actions: list[RecoveryAction] = field(default_factory=list)

    @property
    def primary_action(self) -> RecoveryAction | None:
        for a in self.actions:
            if a.is_primary:
                return a
        return self.actions[0] if self.actions else None


def diagnose_error(
    error: Exception | str,
    *,
    repo_path: Path | str | None = None,
    stderr: str | None = None,
    stdout: str | None = None,
    command: list[str] | str | None = None,
) -> DiagnosticReport:
    """Classify an error and return structured diagnostic details with recovery actions."""
    err_str = str(error)
    combined_err = f"{err_str}\n{stderr or ''}\n{stdout or getattr(error, 'stdout', '') or ''}"
    cmd_str = " ".join(command) if isinstance(command, list) else (command or "")

    # 0. Nothing to Commit / Clean Working Tree
    if (
        "NothingToCommitError" in type(error).__name__
        or "nothing to commit" in combined_err.lower()
        or "no changes added to commit" in combined_err.lower()
    ):
        return DiagnosticReport(
            category=ErrorCategory.GENERIC_ERROR,
            title="Nothing to Commit",
            description=(
                "Your working tree and staging area are clean; there are no changes to commit."
            ),
            technical_details=combined_err.strip(),
            actions=[],
        )

    # 1. Active Repo Contention / Repo Busy
    if (
        "RepoBusyError" in type(error).__name__
        or "repository is currently in the middle" in combined_err
    ):
        return DiagnosticReport(
            category=ErrorCategory.REPO_BUSY,
            title="Repository Busy",
            description=(
                "Another Git process or ongoing operation is currently accessing this repository."
            ),
            technical_details=combined_err,
            actions=[
                WaitForRepoReleaseAction(),
                AbortInterruptedOperationAction(),
            ],
        )

    # 2. Git Hooks & Pre-Commit Linter Failures
    if (
        "hook id:" in combined_err
        or "pre-commit" in combined_err
        or "commit-msg" in combined_err
        or "Files were modified by this hook" in combined_err
        or ("ruff" in combined_err and "Failed" in combined_err)
        or ("black" in combined_err and "Failed" in combined_err)
    ):
        hook_names = re.findall(r"hook id:\s*([a-zA-Z0-9_\-]+)", combined_err)
        hooks_info = f" ({', '.join(hook_names)})" if hook_names else ""
        return DiagnosticReport(
            category=ErrorCategory.HOOK_FAILURE,
            title=f"Pre-Commit Hook Rejected Commit{hooks_info}",
            description=(
                "Your repository's automated pre-commit hooks failed "
                "(code formatting or lint rules). "
                "You can auto-format and retry, review output, or commit with --no-verify."
            ),
            technical_details=combined_err,
            actions=[
                AutoFormatAndRetryAction(),
                CommitNoVerifyAction(),
            ],
        )

    # 3. Lock File Detected
    if (
        "index.lock" in combined_err
        or ".lock': File exists" in combined_err
        or "StaleLockDetectedError" in type(error).__name__
    ):
        return DiagnosticReport(
            category=ErrorCategory.STALE_LOCK,
            title="Git Lock File Detected",
            description=(
                "A Git lock file was found. It may belong to an active background process or be a "
                "stale leftover from an interrupted operation."
            ),
            technical_details=combined_err,
            actions=[
                ReleaseStaleLockAction(),
                WaitForRepoReleaseAction(),
            ],
        )

    # 4. Untracked Overwrite Clashes
    if "The following untracked working tree files would be overwritten" in combined_err:
        # Extract untracked file list
        lines = combined_err.splitlines()
        conflicted_files: list[str] = []
        capture = False
        for line in lines:
            if "untracked working tree files would be overwritten" in line:
                capture = True
                continue
            if capture:
                if line.startswith("\t") or line.startswith("  "):
                    conflicted_files.append(line.strip())
                elif "Please move or remove them" in line or not line.strip():
                    break

        return DiagnosticReport(
            category=ErrorCategory.UNTRACKED_OVERWRITE_COLLISION,
            title="Untracked Files Conflict",
            description=(
                f"Operation would overwrite {len(conflicted_files)} untracked file(s). "
                "You can quarantine them into a safe backup folder to proceed."
            ),
            technical_details=combined_err,
            actions=[
                QuarantineUntrackedAction(conflicting_files=conflicted_files),
                AutoStashAndRetryAction(),
            ],
        )

    # 5. Dirty Tree Collision
    if (
        "DirtyTreeError" in type(error).__name__
        or "local changes to the following files would be overwritten" in combined_err
        or "cannot merge with dirty working tree" in combined_err
        or "cannot rebase with dirty working tree" in combined_err
    ):
        return DiagnosticReport(
            category=ErrorCategory.DIRTY_TREE_COLLISION,
            title="Uncommitted Changes Collision",
            description=(
                "This operation requires a clean working tree. Your uncommitted changes would be "
                "overwritten. You can auto-stash your work to proceed safely."
            ),
            technical_details=combined_err,
            actions=[
                AutoStashAndRetryAction(),
            ],
        )

    # 6. Corrupt Index
    if (
        "fatal: index file corrupt" in combined_err
        or "bad index file" in combined_err
        or "index file smaller than expected" in combined_err
    ):
        return DiagnosticReport(
            category=ErrorCategory.CORRUPT_INDEX,
            title="Corrupted Git Index",
            description=(
                "The repository index file is corrupted or truncated. It can be safely rebuilt "
                "from HEAD without losing changes."
            ),
            technical_details=combined_err,
            actions=[
                RebuildCorruptIndexAction(),
            ],
        )

    # 7. Non-Fast-Forward / Push Rejected
    if (
        "[rejected" in combined_err
        or "non-fast-forward" in combined_err
        or "fetch first" in combined_err
        or "Updates were rejected because the remote contains work" in combined_err
    ):
        return DiagnosticReport(
            category=ErrorCategory.PUSH_REJECTED,
            title="Push Rejected (Remote Has Newer Commits)",
            description=(
                "The remote branch has commits that you do not have locally. "
                "Pull and rebase or merge before pushing."
            ),
            technical_details=combined_err,
            actions=[
                PullAndRebaseAction(),
            ],
        )

    # 8. Interrupted Operation (Merge / Rebase debris)
    if (
        "MERGE_HEAD exists" in combined_err
        or "a merge is in progress" in combined_err
        or "rebase in progress" in combined_err
    ):
        mode = "rebase" if "rebase" in combined_err else "merge"
        return DiagnosticReport(
            category=ErrorCategory.INTERRUPTED_OPERATION,
            title=f"Interrupted {mode.capitalize()} In Progress",
            description=(
                f"The repository is currently in the middle of a {mode}. "
                "You can abort it cleanly to return to your previous state."
            ),
            technical_details=combined_err,
            actions=[
                AbortInterruptedOperationAction(mode=mode),
            ],
        )

    # Generic Fallback
    return DiagnosticReport(
        category=ErrorCategory.GENERIC_ERROR,
        title="Git Operation Failed",
        description=f"Command '{cmd_str or 'git'}' encountered an error: {err_str}",
        technical_details=combined_err,
        actions=[
            AutoStashAndRetryAction(),
        ],
    )
