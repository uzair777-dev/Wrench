"""Git write operations — subprocess-backed.

All git CLI invocations go through run_git(). This is the single place that
sets cwd, environment, and timeout. UI code never calls this module directly;
it goes through core.engine.
"""

import logging
import os
import shutil
import subprocess
from pathlib import Path

import pygit2

from .engine import MergeResult, RebaseResult
from .exceptions import (
    BranchAlreadyExistsError,
    BranchNotFullyMergedError,
    DirtyTreeError,
    EmptyCommitMessageError,
    GitCommandError,
)

logger = logging.getLogger(__name__)


def run_git(
    repo_path: Path | str,
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    p = Path(repo_path)
    logger.debug("[git] Executing in '%s': git %s", p, " ".join(args))
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["LC_ALL"] = "C"

    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=p,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        logger.error(
            "[git] Command timed out after %ds in '%s': git %s",
            timeout,
            repo_path,
            " ".join(args),
        )
        raise GitCommandError(args, -1, f"Command timed out after {timeout}s") from e

    if result.returncode != 0:
        logger.debug(
            "[git] Failed (exit %d): git %s\n  stderr: %s\n  stdout: %s",
            result.returncode,
            " ".join(args),
            result.stderr.strip(),
            result.stdout.strip(),
        )
        if check:
            raise GitCommandError(args, result.returncode, result.stderr.strip())
    else:
        logger.debug("[git] Succeeded (exit 0): git %s", " ".join(args))

    return result


def _check_clean_working_tree(repo_path: Path) -> None:
    """Raise DirtyTreeError if staged or unstaged changes exist."""
    try:
        r = pygit2.Repository(str(repo_path))
        status = r.status()
        dirty_files = [f for f, flags in status.items() if not (flags & pygit2.GIT_STATUS_WT_NEW)]
        if dirty_files:
            raise DirtyTreeError(dirty_files)
    except pygit2.GitError:
        pass


def _extract_conflicts(repo_path: Path) -> list[str]:
    """Extract list of conflicted file paths from index."""
    conflicts: list[str] = []
    try:
        r = pygit2.Repository(str(repo_path))
        r.index.read()
        if r.index.conflicts is not None:
            for entry_tuple in r.index.conflicts:
                for entry in entry_tuple:
                    if entry is not None and entry.path not in conflicts:
                        conflicts.append(entry.path)
    except Exception:
        pass
    return sorted(conflicts)


def commit(repo_path: Path, message: str, *, amend: bool = False) -> str:
    """Create a commit. Returns the new commit SHA.

    Validates the message is non-empty BEFORE calling git.
    """
    if not message or not message.strip():
        raise EmptyCommitMessageError("Commit message must not be empty")

    args = ["commit", "-m", message]
    if amend:
        args.append("--amend")

    run_git(repo_path, args)
    rev_result = run_git(repo_path, ["rev-parse", "HEAD"])
    return rev_result.stdout.strip()


def create_branch(repo_path: Path, name: str, from_ref: str = "HEAD") -> None:
    """Create a new branch. Raises BranchAlreadyExistsError on collision."""
    try:
        run_git(repo_path, ["branch", name, from_ref])
    except GitCommandError as e:
        if "already exists" in (e.stderr or ""):
            raise BranchAlreadyExistsError(
                f"Branch '{name}' already exists", stderr=e.stderr
            ) from e
        raise


def switch_branch(repo_path: Path, name: str) -> None:
    """Switch to a branch. Uses 'git switch', not 'git checkout'."""
    run_git(repo_path, ["switch", name])


def delete_branch(repo_path: Path, name: str, *, force: bool = False) -> None:
    """Delete a branch. Uses -d (safe) or -D (force)."""
    flag = "-D" if force else "-d"
    try:
        run_git(repo_path, ["branch", flag, name])
    except GitCommandError as e:
        if "not fully merged" in (e.stderr or "") or "not fully merged" in str(e):
            raise BranchNotFullyMergedError(
                f"Branch '{name}' has unmerged commits. Use force=True to delete anyway.",
                stderr=e.stderr,
            ) from e
        raise


def rename_branch(repo_path: Path, old: str, new: str) -> None:
    """Rename a branch."""
    run_git(repo_path, ["branch", "-m", old, new])


def create_tag(repo_path: Path | str, name: str, target: str = "HEAD") -> None:
    """Create a tag pointing to target ref/SHA."""
    run_git(repo_path, ["tag", name, target])


def stash_push(repo_path: Path, message: str | None = None) -> str:
    """Create a real stash entry (modifies working tree)."""
    args = ["stash", "push"]
    if message:
        args.extend(["-m", message])
    run_git(repo_path, args)
    return "stash@{0}"


def stash_pop(repo_path: Path | str, stash_id: str | int = 0) -> None:
    """Apply a stash entry and drop it."""
    id_str = f"stash@{{{stash_id}}}" if isinstance(stash_id, int) else str(stash_id)
    run_git(repo_path, ["stash", "pop", id_str])


def stash_apply(repo_path: Path | str, stash_id: str) -> None:
    """Apply a stash entry without removing it."""
    run_git(repo_path, ["stash", "apply", stash_id])


def stash_drop(repo_path: Path | str, stash_id: str) -> None:
    """Remove a stash entry."""
    run_git(repo_path, ["stash", "drop", stash_id])


def discard_file(repo_path: Path | str, file_path: str) -> None:
    """Discard changes in a file (restore tracked, unlink untracked)."""
    p = Path(repo_path)
    target = p / file_path

    # Check if tracked by git
    result = run_git(p, ["ls-files", file_path], check=False)
    if result.returncode == 0 and result.stdout.strip():
        # Tracked file: restore in index and working tree
        run_git(p, ["checkout", "HEAD", "--", file_path], check=False)
    else:
        # Untracked file: delete from filesystem
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists() or target.is_symlink():
            target.unlink(missing_ok=True)


def init_repo(repo_path: Path | str) -> None:
    """Initialize a new git repository."""
    p = Path(repo_path)
    p.mkdir(parents=True, exist_ok=True)
    run_git(p, ["init"])


def clone_repo(
    url: str,
    dest: Path | str,
    *,
    timeout: int = 600,
    progress_cb=None,
) -> None:
    """Clone a repository."""
    d = Path(dest)
    d.parent.mkdir(parents=True, exist_ok=True)
    run_git(
        d.parent,
        ["clone", url, str(d.name)],
        timeout=timeout,
    )


# --- Phase 2: Merge & Rebase Operations ---


def merge(repo_path: Path | str, source_branch: str) -> MergeResult:
    """Merge a branch into current HEAD.

    Checks clean working tree first, takes pre_risky_op snapshot, runs git merge.
    Returns MergeResult (conflict is a status, not an exception).
    """
    p = Path(repo_path)
    _check_clean_working_tree(p)

    # Snapshot first
    from . import engine, snapshots

    try:
        handle = engine.open_repo(p)
        snapshots.take_snapshot(handle, "pre_risky_op")
    except Exception:
        pass

    result = run_git(p, ["merge", source_branch], check=False)

    if result.returncode == 0:
        stdout = result.stdout.strip()
        if "Already up to date." in stdout or "Already up-to-date." in stdout:
            return MergeResult(status="up_to_date")
        rev_res = run_git(p, ["rev-parse", "HEAD"])
        return MergeResult(status="merged", commit_sha=rev_res.stdout.strip())

    # Non-zero exit code: check if conflict or dirty tree error
    if "would be overwritten by merge" in result.stderr or "Your local changes" in result.stderr:
        raise DirtyTreeError([], stderr=result.stderr)

    conflicts = _extract_conflicts(p)
    if (
        conflicts
        or "Automatic merge failed; fix conflicts" in result.stdout
        or "CONFLICT" in result.stdout
    ):
        return MergeResult(status="conflict", conflicted_files=conflicts)

    raise GitCommandError(["merge", source_branch], result.returncode, result.stderr)


def merge_abort(repo_path: Path | str) -> None:
    """Abort an in-progress merge."""
    p = Path(repo_path)
    run_git(p, ["merge", "--abort"])


def rebase(repo_path: Path | str, onto: str) -> RebaseResult:
    """Rebase current branch onto the given ref.

    Checks clean working tree, takes pre_risky_op snapshot, runs git rebase.
    Returns RebaseResult.
    """
    p = Path(repo_path)
    _check_clean_working_tree(p)

    from . import engine, snapshots

    try:
        handle = engine.open_repo(p)
        snapshots.take_snapshot(handle, "pre_risky_op")
    except Exception:
        pass

    result = run_git(p, ["rebase", onto], check=False)

    if result.returncode == 0:
        return RebaseResult(status="complete")

    if "would be overwritten by merge" in result.stderr or "Your local changes" in result.stderr:
        raise DirtyTreeError([], stderr=result.stderr)

    conflicts = _extract_conflicts(p)
    if (
        conflicts
        or "Could not apply" in result.stdout
        or "CONFLICT" in result.stdout
        or "resolve all conflicts" in result.stderr
    ):
        return RebaseResult(status="conflict", conflicted_files=conflicts)

    raise GitCommandError(["rebase", onto], result.returncode, result.stderr)


def rebase_continue(repo_path: Path | str) -> RebaseResult:
    """Continue an in-progress rebase after conflict resolution."""
    p = Path(repo_path)
    result = run_git(p, ["rebase", "--continue"], check=False)

    if result.returncode == 0:
        return RebaseResult(status="complete")

    conflicts = _extract_conflicts(p)
    if (
        conflicts
        or "Could not apply" in result.stdout
        or "CONFLICT" in result.stdout
        or "resolve all conflicts" in result.stderr
    ):
        return RebaseResult(status="conflict", conflicted_files=conflicts)

    raise GitCommandError(["rebase", "--continue"], result.returncode, result.stderr)


def rebase_abort(repo_path: Path | str) -> None:
    """Abort an in-progress rebase."""
    p = Path(repo_path)
    run_git(p, ["rebase", "--abort"])
