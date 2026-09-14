"""Git write operations — subprocess-backed.

All git CLI invocations go through run_git(). This is the single place that
sets cwd, environment, and timeout. UI code never calls this module directly;
it goes through core.engine.
"""

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pygit2

from . import ssh_agent
from .engine import MergeResult, RebaseResult
from .exceptions import (
    AuthFailedError,
    AuthRequiredError,
    BranchAlreadyExistsError,
    BranchNotFullyMergedError,
    CLITimeoutError,
    DirtyTreeError,
    EmptyCommitMessageError,
    GitCommandError,
    MergeRequiredError,
    PushRejectedError,
)
from .git_credential_helper import _host_of

logger = logging.getLogger(__name__)


def _git_env() -> dict[str, str]:
    """Construct a clean, non-interactive environment for git subprocesses."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["LC_ALL"] = "C"
    ssh_agent.configure_ssh_env(env)
    return env


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
    env = _git_env()

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


_PROGRESS_RE = re.compile(r"^([\w ]+?):\s+(\d+)%(?:\s*\(\d+/\d+\))?")


def _parse_progress(line: str) -> tuple[int, str] | None:
    """Parse git sideband progress lines.

    Captures (percent, stage) e.g. (12, "Counting objects").
    Returns None if line does not match.
    """
    s = line.strip()
    if s.startswith("remote:"):
        s = s[len("remote:") :].strip()
    m = _PROGRESS_RE.match(s)
    if not m:
        return None
    stage = m.group(1).strip()
    pct = int(m.group(2))
    return (pct, stage)


def _classify_git_error(
    args: list[str],
    returncode: int,
    stderr: str,
    remote_url: str | None = None,
) -> Exception:
    """Classify non-zero git CLI exit into specific domain exceptions."""
    is_push = len(args) > 0 and args[0] == "push"
    is_pull = len(args) > 0 and args[0] == "pull"

    if is_push and "rejected" in stderr:
        return PushRejectedError(args, returncode, stderr)

    if is_pull and "Not possible to fast-forward" in stderr:
        return MergeRequiredError(args, returncode, stderr)

    parsed_host = _host_of(remote_url) if remote_url else None
    if not parsed_host and stderr:
        m = re.search(r"https?://([^/:\s']+)", stderr)
        if m:
            parsed_host = m.group(1).lower()
        else:
            m = re.search(r"git@([^/:\s']+)", stderr)
            if m:
                parsed_host = m.group(1).lower()

    if any(
        pattern in stderr
        for pattern in (
            "Authentication failed",
            "403",
            "401",
            "Permission denied (publickey)",
        )
    ):
        return AuthFailedError(host=parsed_host, stderr=stderr)

    if any(
        pattern in stderr
        for pattern in (
            "could not read Username",
            "could not read Password",
            "terminal prompts disabled",
        )
    ):
        return AuthRequiredError(host=parsed_host, stderr=stderr)

    return GitCommandError(args, returncode, stderr)


def run_git_streaming(
    repo_path: Path | str,
    args: list[str],
    *,
    timeout: int = 600,
    on_stderr_line: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[int, str, str]:
    """Execute a git command with concurrent pipe draining and cancellation support.

    Prevents 64 KiB buffer deadlocks by consuming stdout and stderr concurrently.
    Splits stderr on both \\r and \\n to stream in-place progress updates.
    Returns (returncode, stdout_text, stderr_text).
    """
    p = Path(repo_path)
    logger.debug("[git-streaming] Executing in '%s': git %s", p, " ".join(args))
    env = _git_env()
    cmd = ["git"] + args

    proc = subprocess.Popen(
        cmd,
        cwd=p,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    def _read_stdout():
        assert proc.stdout is not None
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            stdout_chunks.append(chunk.decode("utf-8", errors="replace"))

    def _read_stderr():
        assert proc.stderr is not None
        buffer = ""
        while True:
            chunk = proc.stderr.read(4096)
            if not chunk:
                if buffer and on_stderr_line:
                    on_stderr_line(buffer)
                break
            text = chunk.decode("utf-8", errors="replace")
            stderr_chunks.append(text)
            buffer += text
            while True:
                r_pos = buffer.find("\r")
                n_pos = buffer.find("\n")
                if r_pos == -1 and n_pos == -1:
                    break
                if r_pos != -1 and (n_pos == -1 or r_pos < n_pos):
                    split_pos = r_pos
                    sep_len = 1
                    if split_pos + 1 < len(buffer) and buffer[split_pos + 1] == "\n":
                        sep_len = 2
                else:
                    split_pos = n_pos
                    sep_len = 1
                fragment = buffer[:split_pos]
                buffer = buffer[split_pos + sep_len :]
                if on_stderr_line and fragment:
                    on_stderr_line(fragment)

    t_stdout = threading.Thread(target=_read_stdout, daemon=True)
    t_stderr = threading.Thread(target=_read_stderr, daemon=True)
    t_stdout.start()
    t_stderr.start()

    start_time = time.monotonic()

    while True:
        if proc.poll() is not None:
            break

        if cancel_event and cancel_event.is_set():
            logger.debug("[git-streaming] Cancel requested; terminating process %d", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "[git-streaming] Process %d did not terminate in 3s; killing", proc.pid
                )
                proc.kill()
                proc.wait(timeout=1.0)
            break

        elapsed = time.monotonic() - start_time
        if timeout and elapsed > timeout:
            logger.error(
                "[git-streaming] Process %d timed out after %ds; killing", proc.pid, timeout
            )
            proc.kill()
            proc.wait(timeout=1.0)
            t_stdout.join(timeout=1.0)
            t_stderr.join(timeout=1.0)
            stderr_str = "".join(stderr_chunks)
            raise CLITimeoutError(args, timeout, stderr_str)

        time.sleep(0.05)

    t_stdout.join(timeout=2.0)
    t_stderr.join(timeout=2.0)

    returncode = proc.returncode if proc.returncode is not None else -1
    stdout_str = "".join(stdout_chunks)
    stderr_str = "".join(stderr_chunks)

    if returncode != 0:
        logger.debug(
            "[git-streaming] Failed (exit %d): git %s\n  stderr: %s",
            returncode,
            " ".join(args),
            stderr_str.strip(),
        )
    else:
        logger.debug("[git-streaming] Succeeded (exit 0): git %s", " ".join(args))

    return (returncode, stdout_str, stderr_str)


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
