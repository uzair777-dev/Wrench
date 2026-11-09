"""Git submodule management (list, status, init, update, sync, add)."""

import logging
from pathlib import Path

import pygit2

from .exceptions import GitCommandError
from .lfs_ops import lfs_available
from .models import Submodule, SubmoduleStatus
from .write_ops import run_git

logger = logging.getLogger(__name__)


def _run_submodule_cmd(repo_path: Path | str, args: list[str]) -> None:
    """Run a submodule git command with automatic file:// transport fallback."""
    p = Path(repo_path)
    try:
        run_git(p, args)
    except GitCommandError as e:
        err = (e.stderr or "") + (e.stdout or "")
        if "transport 'file' not allowed" in err or "protocol 'file' is not allowed" in err:
            logger.debug("[submodules] Retrying with protocol.file.allow=always: %s", args)
            run_git(p, ["-c", "protocol.file.allow=always"] + args)
        else:
            raise


def list_submodules(repo) -> list[Submodule]:
    """List all configured submodules in the repository."""
    # Fast-path check: avoid overhead if no .gitmodules exists
    gitmodules_path = Path(repo.path) / ".gitmodules"
    if not gitmodules_path.exists():
        return []

    results: list[Submodule] = []
    try:
        submodules_coll = getattr(repo.pygit2_repo, "submodules", None)
        if submodules_coll:
            for sm in submodules_coll:
                sub_path = Path(repo.path) / sm.path
                is_init = (sub_path / ".git").exists() or (sub_path / "HEAD").exists()
                results.append(
                    Submodule(
                        path=sm.path,
                        url=sm.url or "",
                        initialized=is_init,
                    )
                )
        else:
            # Fallback to listall_submodules
            names = repo.pygit2_repo.listall_submodules()
            for name in names:
                sub_path = Path(repo.path) / name
                is_init = (sub_path / ".git").exists() or (sub_path / "HEAD").exists()
                results.append(
                    Submodule(
                        path=name,
                        url="",
                        initialized=is_init,
                    )
                )
    except Exception as e:
        logger.debug("[submodules] Error listing submodules: %s", e)

    return results


def submodule_status(repo, path: str) -> SubmoduleStatus:
    """Return status of a specific submodule. Never raises on uninitialized submodules."""
    sub_path = Path(repo.path) / path
    is_init = (sub_path / ".git").exists() or (sub_path / "HEAD").exists()

    if not is_init:
        # Uninitialized: return clean/empty commit without raising
        current_commit = ""
        try:
            submodules_coll = getattr(repo.pygit2_repo, "submodules", None)
            if submodules_coll and path in submodules_coll:
                sm = submodules_coll[path]
                if sm.head_id:
                    current_commit = str(sm.head_id)
        except Exception as e:
            logger.debug("[submodules] Could not lookup uninitialized head_id: %s", e)
        return SubmoduleStatus(path=path, current_commit=current_commit, is_dirty=False)

    current_commit = ""
    is_dirty = False
    try:
        sub_repo = pygit2.Repository(str(sub_path))
        if not sub_repo.head_is_unborn:
            current_commit = str(sub_repo.head.target)
        status_dict = sub_repo.status()
        is_dirty = len(status_dict) > 0
    except Exception as e:
        logger.debug("[submodules] Error probing submodule status for %s: %s", path, e)

    return SubmoduleStatus(path=path, current_commit=current_commit, is_dirty=is_dirty)


def init_submodule(repo, path: str | None = None) -> None:
    """Initialize and update repository submodules."""
    cmd = ["submodule", "update", "--init", "--recursive"]
    if path:
        cmd.extend(["--", path])
    _run_submodule_cmd(repo.path, cmd)

    # Post-init LFS filter setup inside submodules
    _ensure_lfs_in_submodules(repo)


init_submodules = init_submodule


def update_submodules(repo, path: str | None = None, recursive: bool = True) -> None:
    """Update repository submodules."""
    cmd = ["submodule", "update"]
    if recursive:
        cmd.append("--recursive")
    if path:
        cmd.extend(["--", path])
    _run_submodule_cmd(repo.path, cmd)

    # Post-update LFS filter setup inside submodules
    _ensure_lfs_in_submodules(repo)


def sync_submodules(repo, path: str | None = None) -> None:
    """Synchronize submodule remote URLs with .gitmodules."""
    cmd = ["submodule", "sync"]
    if path:
        cmd.extend(["--", path])
    _run_submodule_cmd(repo.path, cmd)


def add_submodule(repo, url: str, path: str) -> None:
    """Add a new submodule to the repository."""
    cmd = ["submodule", "add", "--", url, path]
    _run_submodule_cmd(repo.path, cmd)


def _ensure_lfs_in_submodules(repo) -> None:
    """Run guarded lfs install --local in initialized submodules tracking LFS."""
    if not lfs_available():
        return
    for sm in list_submodules(repo):
        if sm.initialized:
            sub_path = Path(repo.path) / sm.path
            sub_gitattrs = sub_path / ".gitattributes"
            if sub_gitattrs.exists():
                try:
                    content = sub_gitattrs.read_text(encoding="utf-8", errors="replace")
                    if "filter=lfs" in content:
                        run_git(sub_path, ["lfs", "install", "--local"], check=False)
                except Exception as e:
                    logger.debug(
                        "[submodules] Failed LFS filter install in submodule %s: %s", sm.path, e
                    )
