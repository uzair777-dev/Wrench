"""FR-1.9: Detect and clear stale .git/index.lock files."""

from pathlib import Path


def check_lock(repo_path: Path) -> None:
    raise NotImplementedError


def remove_lock(repo_path: Path) -> None:
    raise NotImplementedError


def check_all_repos(conn) -> list[tuple[int, str, str]]:
    raise NotImplementedError
