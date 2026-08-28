"""FR-1.9: Detect and clear stale .git/index.lock files.

A lock file older than _STALE_THRESHOLD_SECONDS (5s) is considered stale
(e.g. left behind by a killed git process).
"""

import time
from pathlib import Path

from .exceptions import StaleLockDetectedError

_STALE_THRESHOLD_SECONDS = 5.0


def check_lock(repo_path: Path | str) -> None:
    """Check for a stale .git/index.lock.

    Raises StaleLockDetectedError if a stale lock exists.
    """
    p = Path(repo_path)
    lock_file = p / ".git" / "index.lock"
    if not lock_file.exists():
        return

    try:
        mtime = lock_file.stat().st_mtime
        age = time.time() - mtime
        if age >= _STALE_THRESHOLD_SECONDS:
            raise StaleLockDetectedError(str(lock_file))
    except FileNotFoundError:
        pass


def remove_lock(repo_path: Path | str) -> None:
    """Remove .git/index.lock."""
    p = Path(repo_path)
    lock_file = p / ".git" / "index.lock"
    if lock_file.exists():
        lock_file.unlink()


def check_all_repos(conn) -> list[tuple[int, str, str]]:
    """Check all registered repos for stale locks on startup."""
    from wrench.storage.repo_registry import list_repos

    results = []
    for repo in list_repos(conn):
        repo_path = Path(repo.path)
        if not repo_path.exists():
            continue
        try:
            check_lock(repo_path)
        except StaleLockDetectedError as e:
            results.append((repo.id, repo.display_name, str(e.lock_path)))
    return results
