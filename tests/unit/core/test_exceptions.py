"""Unit tests for Phase 3 exceptions in core/exceptions.py."""

from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CLITimeoutError,
    CloneAbortedError,
    FileTooLargeRejectedError,  # NEW
    GitCommandError,
    MergeRequiredError,
    ProtectedBranchRejectedError,  # NEW
    PushRejectedError,
    RemoteExistsError,
    RemoteNotFoundError,
    RepoPermissionDeniedError,  # NEW
    SecretScanningRejectedError,  # NEW
    SignedCommitsRequiredError,  # NEW
    WorkflowScopeRequiredError,
    WrenchGitError,
)


class TestPhase3Exceptions:
    def test_exception_inheritance(self):
        assert issubclass(CloneAbortedError, WrenchGitError)
        assert issubclass(AuthRequiredError, WrenchGitError)
        assert issubclass(AuthFailedError, WrenchGitError)
        assert issubclass(PushRejectedError, GitCommandError)
        assert issubclass(WorkflowScopeRequiredError, GitCommandError)
        assert issubclass(MergeRequiredError, GitCommandError)
        assert issubclass(RemoteExistsError, WrenchGitError)
        assert issubclass(RemoteNotFoundError, WrenchGitError)
        assert issubclass(CLITimeoutError, GitCommandError)

    def test_auth_required_error_fields(self):
        err = AuthRequiredError(host="github.com", path_component="uzair/wrench.git")
        assert err.host == "github.com"
        assert err.path_component == "uzair/wrench.git"
        assert "github.com" in str(err)

    def test_auth_failed_error_fields(self):
        err = AuthFailedError(host="gitlab.com")
        assert err.host == "gitlab.com"
        assert "gitlab.com" in str(err)

    def test_remote_exists_and_not_found(self):
        err1 = RemoteExistsError("origin")
        assert "origin" in str(err1)
        err2 = RemoteNotFoundError("upstream")
        assert "upstream" in str(err2)

    def test_git_command_error_derivatives(self):
        err = PushRejectedError(["push", "origin", "main"], 1, "error: failed to push some refs")
        assert err.returncode == 1
        assert "failed to push" in err.stderr

        timeout_err = CLITimeoutError(["fetch", "origin"], -1, "Command timed out after 600s")
        assert timeout_err.returncode == -1


class TestPushProtectionExceptions:
    """Tests for server-side push protection exception subclasses."""

    def test_secret_scanning_inherits_push_rejected(self):
        err = SecretScanningRejectedError(
            "Secret detected",
            secret_type="GitHub Personal Access Token",
            file_location="config.py:12",
            unblock_url="https://github.com/org/repo/security/secret-scanning/unblock-secret/abc",
            returncode=1,
            stderr="remote: error: GH007",
        )
        assert isinstance(err, PushRejectedError)
        assert isinstance(err, GitCommandError)
        assert err.secret_type == "GitHub Personal Access Token"
        assert err.file_location == "config.py:12"
        assert "unblock-secret/abc" in err.unblock_url

    def test_secret_scanning_accepts_args_list(self):
        """Must work with _classify_git_error which passes args as a list."""
        err = SecretScanningRejectedError(["push", "origin", "main"], 1, "remote: error: GH007")
        assert isinstance(err, PushRejectedError)
        assert err.returncode == 1

    def test_protected_branch_fields(self):
        err = ProtectedBranchRejectedError(
            "Branch protected",
            branch_name="master",
            reason="Changes must be made through a pull request",
        )
        assert isinstance(err, PushRejectedError)
        assert err.branch_name == "master"
        assert "pull request" in err.reason

    def test_file_too_large_fields(self):
        err = FileTooLargeRejectedError(
            "File too large",
            filename="large_dataset.bin",
            filesize_mb=124.5,
            limit_mb=100.0,
        )
        assert isinstance(err, PushRejectedError)
        assert err.filename == "large_dataset.bin"
        assert err.filesize_mb == 124.5
        assert err.limit_mb == 100.0

    def test_signed_commits_required(self):
        err = SignedCommitsRequiredError("Signing required")
        assert isinstance(err, PushRejectedError)

    def test_repo_permission_denied(self):
        err = RepoPermissionDeniedError("Access denied")
        assert isinstance(err, PushRejectedError)
