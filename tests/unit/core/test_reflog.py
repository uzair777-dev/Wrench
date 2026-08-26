"""Unit tests for core/reflog.py — reflog read and restore-to-ref."""

from wrench.core import reflog


class TestReflog:
    def test_get_reflog_returns_entries(self, multi_commit_repo):
        entries = reflog.get_reflog(multi_commit_repo)
        assert len(entries) >= 3
        assert any("First commit" in e.message or "commit:" in e.message for e in entries)

    def test_restore_to_ref(self, multi_commit_repo):
        entries = reflog.get_reflog(multi_commit_repo)
        first_commit_sha = entries[-1].sha

        reflog.restore_to_ref(multi_commit_repo, first_commit_sha)
        assert str(multi_commit_repo.pygit2_repo.head.target) == first_commit_sha
