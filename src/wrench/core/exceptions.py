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


class CloneAbortedError(WrenchGitError):
    """User cancelled a clone via cancel_event; temp directory was cleaned up."""

    def __init__(
        self, message: str = "Clone operation was cancelled by user.", *, stderr: str | None = None
    ):
        super().__init__(message, stderr=stderr)


class AuthRequiredError(WrenchGitError):
    """Credentials required by remote host but none found in storage."""

    def __init__(
        self,
        host: str | None = None,
        path_component: str | None = None,
        *,
        stderr: str | None = None,
    ):
        self.host = host
        self.path_component = path_component
        detail = f" for host '{host}'" if host else ""
        super().__init__(f"Authentication credentials required{detail}.", stderr=stderr)


class AuthFailedError(WrenchGitError):
    """Stored credentials rejected by remote host or SSH agent authentication failed."""

    def __init__(self, host: str | None = None, *, stderr: str | None = None):
        self.host = host
        detail = f" for host '{host}'" if host else ""
        super().__init__(
            f"Authentication failed{detail}. Check account token or SSH keys.",
            stderr=stderr,
        )


class PushRejectedError(GitCommandError):
    """git push exited non-zero with 'rejected' in stderr (non-fast-forward / remote moved)."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
    ):
        if isinstance(stderr_or_args, list):
            super().__init__(stderr_or_args, returncode, stderr or "")
        else:
            super().__init__(["push"], returncode, stderr_or_args)


class WorkflowScopeRequiredError(GitCommandError):
    """git push rejected because GitHub requires 'workflow' OAuth scope to edit workflows."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
    ):
        if isinstance(stderr_or_args, list):
            super().__init__(stderr_or_args, returncode, stderr or "")
        else:
            super().__init__(["push"], returncode, stderr_or_args)


class SecretScanningRejectedError(PushRejectedError):
    """Raised when GitHub Secret Scanning (GH007) blocks a push containing leaked credentials."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
        *,
        secret_type: str | None = None,
        file_location: str | None = None,
        unblock_url: str | None = None,
    ) -> None:
        super().__init__(stderr_or_args, returncode, stderr)
        self.secret_type = secret_type
        self.file_location = file_location
        self.unblock_url = unblock_url


class ProtectedBranchRejectedError(PushRejectedError):
    """Raised when branch protection rules or rulesets (GH006) block a direct push."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
        *,
        branch_name: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(stderr_or_args, returncode, stderr)
        self.branch_name = branch_name
        self.reason = reason


class FileTooLargeRejectedError(PushRejectedError):
    """Raised when a file exceeds remote file size quota (e.g. GitHub 100MB limit - GH001)."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
        *,
        filename: str | None = None,
        filesize_mb: float | None = None,
        limit_mb: float = 100.0,
    ) -> None:
        super().__init__(stderr_or_args, returncode, stderr)
        self.filename = filename
        self.filesize_mb = filesize_mb
        self.limit_mb = limit_mb


class SignedCommitsRequiredError(PushRejectedError):
    """Raised when remote branch requires signed commits (GH008)."""


class RepoPermissionDeniedError(PushRejectedError):
    """Raised when authenticated user lacks push permissions on the repository (HTTP 403)."""


class MergeRequiredError(GitCommandError):
    """git pull --ff-only failed because branches diverged."""

    def __init__(
        self,
        stderr_or_args: str | list[str] = "",
        returncode: int = 1,
        stderr: str | None = None,
    ):
        if isinstance(stderr_or_args, list):
            super().__init__(stderr_or_args, returncode, stderr or "")
        else:
            super().__init__(["pull"], returncode, stderr_or_args)


class RemoteExistsError(WrenchGitError):
    """Remote name already exists."""

    def __init__(self, name: str, *, stderr: str | None = None):
        self.name = name
        super().__init__(f"Remote '{name}' already exists.", stderr=stderr)


class RemoteNotFoundError(WrenchGitError):
    """Remote name was not found in repository."""

    def __init__(self, name: str, *, stderr: str | None = None):
        self.name = name
        super().__init__(f"Remote '{name}' not found.", stderr=stderr)


class CLITimeoutError(GitCommandError):
    """The git subprocess exceeded its timeout."""

    def __init__(
        self,
        args_or_msg: list[str] | str = "",
        returncode_or_timeout: int | float = -1,
        stderr: str = "",
    ):
        if isinstance(args_or_msg, list):
            super().__init__(args_or_msg, int(returncode_or_timeout), stderr)
        else:
            super().__init__(["git"], -1, args_or_msg)
