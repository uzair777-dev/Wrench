"""Git read operations — pygit2-backed."""

from .engine import BlameLine, Commit, Diff, LogFilter, RepoHandle, RepoStatus


def get_status(repo: RepoHandle) -> RepoStatus:
    raise NotImplementedError


def get_diff(repo: RepoHandle, path: str, *, staged: bool) -> Diff:
    raise NotImplementedError


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Commit]:
    raise NotImplementedError


def blame_file(repo: RepoHandle, path: str) -> list[BlameLine]:
    raise NotImplementedError
