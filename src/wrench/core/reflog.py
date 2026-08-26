"""FR-1.10: Reflog read and restore-to-ref."""

from .engine import ReflogEntry, RepoHandle


def get_reflog(repo: RepoHandle) -> list[ReflogEntry]:
    raise NotImplementedError


def restore_to_ref(repo: RepoHandle, sha: str) -> None:
    raise NotImplementedError
