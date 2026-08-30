"""Wrench-specific exceptions for the core git engine."""


class WrenchGitError(Exception):
    """Base class for all Wrench git-related errors."""

    def __init__(self, message: str, *, stderr: str | None = None):
        super().__init__(message)
        self.stderr = stderr


class WrenchRepoNotFoundError(WrenchGitError):
    """The repo path does not exist or is not a valid git repository."""


class EmptyCommitMessageError(WrenchGitError):
    """Commit was attempted with an empty or whitespace-only message."""


class BranchAlreadyExistsError(WrenchGitError):
    """A branch with that name already exists."""


class BranchNotFullyMergedError(WrenchGitError):
    """Branch deletion refused because it has unmerged commits (use force=True)."""


class PatchApplyError(WrenchGitError):
    """git apply --cached failed for a hunk/line staging operation."""


class BinaryFileStagingError(WrenchGitError):
    """Hunk/line-level staging was attempted on a binary file."""


class IdentityRequiredError(WrenchGitError):
    """user.name and/or user.email are not configured."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(f"Git identity not configured. Missing: {', '.join(missing)}")


class StaleLockDetectedError(WrenchGitError):
    """A stale .git/index.lock file was found."""

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        super().__init__(f"Stale lock file detected: {lock_path}")


class GitCommandError(WrenchGitError):
    """A git subprocess command exited with a nonzero code."""

    def __init__(self, args: list[str], returncode: int, stderr: str):
        self.args_list = args
        self.returncode = returncode
        cmd_str = " ".join(args)
        error_detail = f"\n\nError output:\n{stderr.strip()}" if stderr and stderr.strip() else ""
        super().__init__(
            f"git command failed (exit {returncode}): {cmd_str}{error_detail}",
            stderr=stderr,
        )


class DirtyTreeError(WrenchGitError):
    """Raised when an operation (e.g. merge, rebase) requires a clean working tree."""

    def __init__(self, dirty_files: list[str], *, stderr: str | None = None):
        self.dirty_files = dirty_files
        files_str = ", ".join(dirty_files) if dirty_files else "uncommitted changes"
        super().__init__(f"Working tree has uncommitted changes: {files_str}", stderr=stderr)


class RepoBusyError(WrenchGitError):
    """Raised when snapshot restore or reflog reset is attempted mid-merge or mid-rebase."""

    def __init__(self, operation: str, state: str, *, stderr: str | None = None):
        self.operation = operation
        self.state = state
        super().__init__(
            f"Cannot perform {operation} while repository is in {state} state.",
            stderr=stderr,
        )
