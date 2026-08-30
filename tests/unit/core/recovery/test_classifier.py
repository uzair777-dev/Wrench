"""Unit tests for Smart Error Classifier across diverse failure modes."""

from wrench.core.exceptions import DirtyTreeError, RepoBusyError, StaleLockDetectedError
from wrench.core.recovery.classifier import ErrorCategory, diagnose_error


class TestClassifier:
    def test_classify_repo_busy(self):
        report = diagnose_error(RepoBusyError("restore_snapshot", "merge"))
        assert report.category == ErrorCategory.REPO_BUSY
        assert report.title == "Repository Busy"
        assert len(report.actions) >= 1

    def test_classify_pre_commit_hook_failure(self):
        err = "git command failed (exit 1): commit -m test"
        stderr = "hook id: ruff\nFailed\nhook id: black\nFailed"
        report = diagnose_error(err, stderr=stderr)

        assert report.category == ErrorCategory.HOOK_FAILURE
        assert "Pre-Commit Hook" in report.title
        assert any(a.action_id == "auto_format_and_retry" for a in report.actions)
        assert any(a.action_id == "commit_no_verify" for a in report.actions)

    def test_classify_stale_lock(self):
        report = diagnose_error(StaleLockDetectedError("/path/to/.git/index.lock"))
        assert report.category == ErrorCategory.STALE_LOCK
        assert any(a.action_id == "release_stale_lock" for a in report.actions)

    def test_classify_dirty_tree_collision(self):
        report = diagnose_error(DirtyTreeError(["file1.txt", "file2.txt"]))
        assert report.category == ErrorCategory.DIRTY_TREE_COLLISION
        assert any(a.action_id == "auto_stash_and_retry" for a in report.actions)

    def test_classify_untracked_overwrite_collision(self):
        stderr = (
            "error: The following untracked working tree files would be overwritten by checkout:\n"
            "\tuntracked_file.txt\n"
            "\tsubdir/another.txt\n"
            "Please move or remove them before you switch branches."
        )
        report = diagnose_error("checkout failed", stderr=stderr)
        assert report.category == ErrorCategory.UNTRACKED_OVERWRITE_COLLISION
        assert any(a.action_id == "quarantine_untracked" for a in report.actions)

    def test_classify_corrupt_index(self):
        stderr = "error: bad index file\nfatal: index file corrupt"
        report = diagnose_error("git status failed", stderr=stderr)
        assert report.category == ErrorCategory.CORRUPT_INDEX
        assert any(a.action_id == "rebuild_corrupt_index" for a in report.actions)

    def test_classify_push_rejected(self):
        stderr = "To github.com:user/repo.git\n ! [rejected] main -> main (non-fast-forward)"
        report = diagnose_error("push failed", stderr=stderr)
        assert report.category == ErrorCategory.PUSH_REJECTED
        assert any(a.action_id == "pull_and_rebase" for a in report.actions)

    def test_classify_interrupted_merge(self):
        report = diagnose_error("a merge is in progress. Please complete or abort it first.")
        assert report.category == ErrorCategory.INTERRUPTED_OPERATION
        assert any(a.action_id == "abort_interrupted_operation" for a in report.actions)

    def test_classify_generic_fallback(self):
        report = diagnose_error("unknown unexpected error occurred")
        assert report.category == ErrorCategory.GENERIC_ERROR
        assert len(report.actions) >= 1
