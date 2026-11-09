"""FR-1.10: Reflog read and restore-to-ref.

Reads the reflog of HEAD. restore_to_ref resets current HEAD to the
specified reflog entry's target SHA.
"""

from .engine import ReflogEntry, RepoHandle
from .reflog_ops import list_reflog, reset_to_reflog_entry


def get_reflog(repo: RepoHandle) -> list[ReflogEntry]:
    """Read the reflog for HEAD."""
    return list_reflog(repo, ref="HEAD")


def restore_to_ref(repo: RepoHandle, sha: str) -> None:
    """Reset current branch HEAD hard to the given commit SHA."""
    reset_to_reflog_entry(repo, sha, mode="hard")
