"""Git write operations — subprocess-backed."""

import os
import subprocess
from pathlib import Path

from .exceptions import GitCommandError


def run_git(
    repo_path: Path,
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise GitCommandError(args, -1, f"Command timed out after {timeout}s") from e

    if check and result.returncode != 0:
        raise GitCommandError(args, result.returncode, result.stderr.strip())

    return result


def commit(repo_path: Path, message: str, *, amend: bool = False) -> str:
    raise NotImplementedError


def create_branch(repo_path: Path, name: str, from_ref: str = "HEAD") -> None:
    raise NotImplementedError


def switch_branch(repo_path: Path, name: str) -> None:
    raise NotImplementedError


def delete_branch(repo_path: Path, name: str, *, force: bool = False) -> None:
    raise NotImplementedError


def rename_branch(repo_path: Path, old: str, new: str) -> None:
    raise NotImplementedError


def stash_push(repo_path: Path, message: str | None = None) -> str:
    raise NotImplementedError


def stash_apply(repo_path: Path, stash_id: str) -> None:
    raise NotImplementedError


def stash_drop(repo_path: Path, stash_id: str) -> None:
    raise NotImplementedError


def init_repo(repo_path: Path) -> None:
    raise NotImplementedError


def clone_repo(
    url: str,
    dest: Path,
    *,
    timeout: int = 600,
    progress_cb=None,
) -> None:
    raise NotImplementedError
