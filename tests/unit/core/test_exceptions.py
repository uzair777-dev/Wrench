"""Unit tests for Phase 3 exceptions in core/exceptions.py."""

from wrench.core.exceptions import (
    AuthFailedError,
    AuthRequiredError,
    CLITimeoutError,
    CloneAbortedError,
    GitCommandError,
    MergeRequiredError,
    PushRejectedError,
    RemoteExistsError,
    RemoteNotFoundError,
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
