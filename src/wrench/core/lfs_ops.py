"""Git LFS operations: detection, tracking, pointers, status, and synchronization."""

import functools
import logging
import shutil
from pathlib import Path

from .exceptions import LfsUnavailableError
from .models import LfsFileStatus, LFSLock
from .write_ops import run_git

logger = logging.getLogger(__name__)

LFS_POINTER_PREFIX = "version https://git-lfs.github.com/spec/v1"


@functools.lru_cache(maxsize=1)
def is_lfs_installed() -> bool:
    """Probe if git-lfs is installed and available via git CLI.

    Cached for the process lifetime.
    """
    if shutil.which("git-lfs") is None:
        return False

    try:
        from .paths import data_dir

        probe_dir = data_dir()
        probe_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.debug("[lfs] Failed to get data_dir for probe cwd: %s", e)
        probe_dir = Path("/tmp")

    try:
        res = run_git(probe_dir, ["lfs", "version"], check=False)
        return res.returncode == 0
    except Exception as e:
        logger.debug("[lfs] git lfs version check failed: %s", e)
        return False


def lfs_available() -> bool:
    """Alias for is_lfs_installed()."""
    return is_lfs_installed()


def _reset_lfs_cache() -> None:
    """Reset cached LFS availability (for testing)."""
    is_lfs_installed.cache_clear()


def _require_lfs() -> None:
    """Raise LfsUnavailableError if git-lfs is not available."""
    if not is_lfs_installed():
        raise LfsUnavailableError(
            "Git LFS is not installed. Please install git-lfs to use LFS features."
        )


def is_lfs_pointer(content: str) -> bool:
    """Check if content string represents a Git LFS pointer file.

    Must match the complete header line, not just a prefix.
    """
    if not content or not isinstance(content, str):
        return False
    lines = content.splitlines()
    if not lines:
        return False
    return lines[0].strip() == LFS_POINTER_PREFIX


def parse_lfs_pointer(content: str) -> tuple[str, str] | None:
    """Parse OID and size from an LFS pointer body.

    Returns (oid, size) as strings, or None if invalid pointer.
    """
    if not is_lfs_pointer(content):
        return None

    oid: str | None = None
    size: str | None = None

    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("oid sha256:"):
            oid = trimmed[len("oid sha256:") :].strip()
        elif trimmed.startswith("size "):
            size = trimmed[len("size ") :].strip()

    if oid and size:
        return (oid, size)
    return None


def lfs_files(repo, paths: list[str]) -> set[str]:
    """Return the subset of paths that are tracked by Git LFS via check-attr."""
    if not paths:
        return set()

    res = run_git(
        repo.path,
        ["check-attr", "-z", "filter", "--", *paths],
        check=False,
    )
    if res.returncode != 0 or not res.stdout:
        return set()

    # stdout is NUL-separated triples: <path>\0<attr>\0<info>\0
    parts = res.stdout.split("\0")
    lfs_set: set[str] = set()
    for i in range(0, len(parts) - 2, 3):
        path, attr, value = parts[i], parts[i + 1], parts[i + 2]
        if attr == "filter" and value == "lfs":
            lfs_set.add(path)

    return lfs_set


def lfs_track(repo, pattern: str) -> None:
    """Track a file pattern with Git LFS."""
    _require_lfs()
    run_git(repo.path, ["lfs", "track", "--", pattern])


def lfs_untrack(repo, pattern: str) -> None:
    """Untrack a file pattern from Git LFS."""
    _require_lfs()
    run_git(repo.path, ["lfs", "untrack", "--", pattern])


def lfs_pull(repo) -> None:
    """Pull Git LFS objects for the current repository."""
    _require_lfs()
    run_git(repo.path, ["lfs", "pull"], timeout=600)


def lfs_push(repo, remote: str = "origin", branch: str | None = None) -> None:
    """Push Git LFS objects for the current branch to remote."""
    _require_lfs()
    if branch is None:
        try:
            branch = repo.pygit2_repo.head.shorthand
        except Exception as e:
            logger.debug("[lfs] Could not get branch shorthand: %s", e)
            branch = "HEAD"
    run_git(repo.path, ["lfs", "push", remote, branch], timeout=600)


def lfs_status(repo) -> list[LfsFileStatus]:
    """Inspect and return status of all LFS-tracked files in the repository."""
    candidate_paths: set[str] = set()

    # Index entries
    try:
        for entry in repo.pygit2_repo.index:
            candidate_paths.add(entry.path)
    except Exception as e:
        logger.debug("[lfs] Failed reading index entries: %s", e)

    # Check worktree files mentioned in .gitattributes if attributes exists
    gitattributes_path = Path(repo.path) / ".gitattributes"
    if gitattributes_path.exists():
        try:
            for p in Path(repo.path).rglob("*"):
                if p.is_file() and not any(
                    part.startswith(".") for part in p.relative_to(repo.path).parts
                ):
                    candidate_paths.add(str(p.relative_to(repo.path)))
        except Exception as e:
            logger.debug("[lfs] Failed reading worktree files: %s", e)

    if not candidate_paths:
        return []

    lfs_tracked = lfs_files(repo, sorted(candidate_paths))
    results: list[LfsFileStatus] = []

    for path in sorted(lfs_tracked):
        file_path = Path(repo.path) / path
        is_ptr = False
        oid: str | None = None
        size: int | None = None

        if file_path.exists() and file_path.is_file():
            try:
                # Read up to first 1024 bytes for pointer detection
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    sample = f.read(1024)
                if is_lfs_pointer(sample):
                    is_ptr = True
                    parsed = parse_lfs_pointer(sample)
                    if parsed:
                        oid = parsed[0]
                        if parsed[1].isdigit():
                            size = int(parsed[1])
                else:
                    size = file_path.stat().st_size
            except Exception as e:
                logger.debug("[lfs] Could not inspect file %s: %s", path, e)
        else:
            # File may be in index/HEAD only
            try:
                entry = repo.pygit2_repo.index[path]
                blob = repo.pygit2_repo[entry.id]
                sample = blob.data[:1024].decode("utf-8", errors="replace")
                if is_lfs_pointer(sample):
                    is_ptr = True
                    parsed = parse_lfs_pointer(sample)
                    if parsed:
                        oid = parsed[0]
                        if parsed[1].isdigit():
                            size = int(parsed[1])
            except Exception as e:
                logger.debug("[lfs] Could not read blob for %s: %s", path, e)

        results.append(
            LfsFileStatus(
                path=path,
                is_pointer=is_ptr,
                oid=oid,
                size=size,
            )
        )

    return results


def lfs_locks(repo) -> list[LFSLock]:
    """Query list of LFS locks from server."""
    _require_lfs()
    res = run_git(repo.path, ["lfs", "locks"], check=False)
    if res.returncode != 0:
        return []
    locks: list[LFSLock] = []
    for line in res.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            path = parts[0]
            owner = parts[1]
            lock_id = parts[2].strip("()") if len(parts) > 2 else ""
            locks.append(LFSLock(lock_id=lock_id, path=path, owner=owner))
    return locks


def lfs_lock(repo, path: str) -> None:
    """Lock a file path in Git LFS."""
    _require_lfs()
    run_git(repo.path, ["lfs", "lock", "--", path])


def lfs_unlock(repo, path: str, *, force: bool = False) -> None:
    """Unlock a file path in Git LFS."""
    _require_lfs()
    args = ["lfs", "unlock"]
    if force:
        args.append("--force")
    args.extend(["--", path])
    run_git(repo.path, args)
