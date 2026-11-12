"""Git write operations — subprocess-backed.

All git CLI invocations go through run_git(). This is the single place that
sets cwd, environment, and timeout. UI code never calls this module directly;
it goes through core.engine.
"""

import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import pygit2

from . import ssh_agent
from .exceptions import (
    AuthFailedError,
    AuthRequiredError,
    BranchAlreadyExistsError,
    BranchNotFullyMergedError,
    CLITimeoutError,
    CloneAbortedError,
    DirtyTreeError,
    EmptyCommitMessageError,
    FileTooLargeRejectedError,
    GitCommandError,
    GitNetworkTransferError,
    MergeRequiredError,
    NothingToCommitError,
    ProtectedBranchRejectedError,
    PushRejectedError,
    RepoPermissionDeniedError,
    SecretScanningRejectedError,
    SignedCommitsRequiredError,
    WorkflowScopeRequiredError,
    WrenchRepoNotFoundError,
)
from .git_credential_helper import _host_of
from .models import CloneResult, CommitGraphStats, MergeResult, RebaseResult
from .paths import resolve_git_dir
from .security_sanitizer import redact_secrets, validate_clone_url, validate_git_ref

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
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    p = Path(repo_path)
    safe_args = redact_secrets(" ".join(args))
    logger.debug("[git] Executing in '%s': git %s", p, safe_args)
    env = _git_env()

    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=p,
            capture_output=True,
            text=True,
            input=input_text,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        logger.error(
            "[git] Command timed out after %ds in '%s': git %s",
            timeout,
            repo_path,
            safe_args,
        )
        raise GitCommandError(args, -1, f"Command timed out after {timeout}s") from e

    if result.returncode != 0:
        logger.debug(
            "[git] Failed (exit %d): git %s\n  stderr: %s\n  stdout: %s",
            result.returncode,
            safe_args,
            redact_secrets(result.stderr.strip()),
            result.stdout.strip(),
        )
        if check:
            raise GitCommandError(
                args,
                result.returncode,
                redact_secrets(result.stderr.strip()),
                stdout=result.stdout.strip(),
            )
    else:
        logger.debug("[git] Succeeded (exit 0): git %s", safe_args)

    return result


_CRED_CONFIG_LOCKS_GUARD = threading.Lock()
_CRED_CONFIG_LOCKS: dict[Path, threading.Lock] = {}


def _resolve_local_git_config_path(repo_path: Path) -> Path | None:
    """Resolve the repository's local git config file (following linked worktree commondir)."""
    try:
        git_dir = resolve_git_dir(repo_path)
    except (WrenchRepoNotFoundError, OSError):
        return None

    common_dir = git_dir
    commondir_file = git_dir / "commondir"
    if commondir_file.is_file():
        try:
            raw = commondir_file.read_text(encoding="utf-8", errors="replace").strip()
            if raw:
                candidate = Path(raw)
                common_dir = (
                    candidate
                    if candidate.is_absolute()
                    else (git_dir / candidate).resolve()
                )
        except OSError:
            common_dir = git_dir
    return (common_dir / "config").resolve()


def _get_cred_config_lock(key: Path) -> threading.Lock:
    with _CRED_CONFIG_LOCKS_GUARD:
        lock = _CRED_CONFIG_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _CRED_CONFIG_LOCKS[key] = lock
        return lock


def ensure_wrench_credential_config(
    repo_path: Path | str,
    pygit2_repo: pygit2.Repository | None = None,
) -> None:
    """Ensure credential.helper='wrench' and credential.useHttpPath='true' in local config.

    Reads strictly the repository's local config file (not aggregated global/system config)
    via pygit2 so global settings cannot mask missing repo config, and serializes writes
    per config path to prevent concurrent ``.git/config.lock`` collisions.
    """
    p = Path(repo_path)
    local_cfg_path = _resolve_local_git_config_path(p)
    lock_key = local_cfg_path if local_cfg_path is not None else p.resolve()
    lock = _get_cred_config_lock(lock_key)

    with lock:
        cfg: pygit2.Config | None = None
        if local_cfg_path is not None and local_cfg_path.is_file():
            try:
                local_cfg = pygit2.Config()
                local_level = getattr(
                    getattr(getattr(pygit2, "enums", None), "ConfigLevel", None),
                    "LOCAL",
                    getattr(pygit2, "GIT_CONFIG_LEVEL_LOCAL", 5),
                )
                local_cfg.add_file(str(local_cfg_path), local_level)
                cfg = local_cfg
            except (pygit2.GitError, OSError, ValueError) as exc:
                logger.debug(
                    "Could not inspect local pygit2 config at %s (%s); falling back to CLI",
                    local_cfg_path,
                    exc,
                )
        elif local_cfg_path is None and pygit2_repo is not None:
            # Explicit in-memory/mock fallback only when no on-disk git_dir could be resolved
            try:
                cfg = pygit2_repo.config
            except (pygit2.GitError, AttributeError):
                cfg = None

        helper_val: str | None = None
        has_multivar_helper = False
        http_path_val: str | None = None
        if cfg is not None:
            try:
                multivars = [str(v).strip() for v in cfg.get_multivar("credential.helper")]
                has_multivar_helper = len(multivars) > 1
                if multivars:
                    helper_val = multivars[-1]
            except (KeyError, ValueError, pygit2.GitError):
                try:
                    helper_val = str(cfg["credential.helper"]).strip()
                except (KeyError, ValueError, pygit2.GitError):
                    helper_val = None

            try:
                http_path_val = str(cfg["credential.useHttpPath"]).strip().lower()
            except (KeyError, ValueError, pygit2.GitError):
                http_path_val = None

        if helper_val != "wrench":
            helper_args = ["config", "--local"]
            if has_multivar_helper:
                helper_args.append("--replace-all")
            helper_args.extend(["credential.helper", "wrench"])
            run_git(p, helper_args)
        if http_path_val != "true":
            run_git(p, ["config", "--local", "credential.useHttpPath", "true"])


# ── Progress-type matrix (Phase 4.6) ────────────────────────────────────
# Surface                  | Type          | Source
# ─────────────────────────┼───────────────┼─────────────────────────────
# Clone/Push/Pull/Fetch    | determinate   | existing "stage: NN%" parse
# Rebase (n/m)             | determinate   | NEW: Rebasing (n/m)
# LFS pull/push            | determinate   | NEW: Git LFS: (N of M files)
# Submodule init/update    | countable     | NEW: per-submodule callback (Phase 5 wires)
# Discovery scan           | countable     | existing "Found N..." — unchanged
# Backup/open/switch/snap  | indeterminate | spinner + rotating line; no bar
#
_PROGRESS_RE = re.compile(r"^([\w ]+?):\s+(\d+)%(?:\s*\(\d+/\d+\))?")
_REBASE_RE = re.compile(r"^Rebasing\s+\((\d+)/(\d+)\)")
_LFS_RE = re.compile(r"^Git LFS:\s+\((\d+)\s+of\s+(\d+)\s+files?\)")


def _parse_progress(line: str) -> tuple[int, str] | None:
    """Parse git sideband progress lines.

    Captures (percent, stage) e.g. (12, "Counting objects").
    Returns None if line does not match.
    Percent is a real fraction — never estimated, never faked.
    """
    s = line.strip()
    if s.startswith("remote:"):
        s = s[len("remote:") :].strip()

    # 1. Rebase fraction: Rebasing (3/10) -> (30, "Rebasing")
    m = _REBASE_RE.match(s)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        pct = (current * 100) // total if total > 0 else 0
        return (pct, "Rebasing")

    # 2. LFS fraction: Git LFS: (5 of 20 files) -> (25, "Git LFS")
    m = _LFS_RE.match(s)
    if m:
        current, total = int(m.group(1)), int(m.group(2))
        pct = (current * 100) // total if total > 0 else 0
        return (pct, "Git LFS")

    # 3. Standard stage: NN% pattern (existing — clone/push/pull/fetch)
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
    is_push = "push" in args
    is_pull = "pull" in args

    # --- Push-specific classification (order matters: specific before generic) ---

    # 1. GitHub Actions Workflow scope required
    if is_push and (
        "without `workflow` scope" in stderr
        or "without 'workflow' scope" in stderr
        or (
            "workflow" in stderr.lower()
            and "scope" in stderr.lower()
            and "refusing" in stderr.lower()
        )
    ):
        return WorkflowScopeRequiredError(args, returncode, stderr)

    # 2. Secret Scanning Push Protection (GH007)
    if is_push and ("GH007" in stderr or "reveal a private secret" in stderr.lower()):
        sec_type_match = re.search(r"Secret type:\s*([^\r\n]+)", stderr)
        file_loc_match = re.search(r"File:\s*([^\r\n]+)", stderr)
        unblock_match = re.search(
            r"(https://github\.com/[^\s]+/secret-scanning/unblock-secret/[^\s\)]+)",
            stderr,
        )
        return SecretScanningRejectedError(
            args,
            returncode,
            stderr,
            secret_type=sec_type_match.group(1).strip() if sec_type_match else None,
            file_location=file_loc_match.group(1).strip() if file_loc_match else None,
            unblock_url=unblock_match.group(1).strip() if unblock_match else None,
        )

    # 3. Protected Branch / Rulesets (GH006)
    if is_push and (
        "GH006" in stderr
        or "protected branch" in stderr.lower()
        or "changes must be made through a pull request" in stderr.lower()
    ):
        branch_match = re.search(r"! \[remote rejected\]\s+([^\s]+)\s*->\s*([^\s\(\)]+)", stderr)
        reason_match = re.search(
            r"(?:remote:\s*)([^\r\n]*(?:pull request|review)[^\r\n]*)",
            stderr,
            re.IGNORECASE,
        ) or re.search(
            r"(?:remote:\s*)([^\r\n]*(?:protected branch)[^\r\n]*)",
            stderr,
            re.IGNORECASE,
        )
        target_branch = branch_match.group(2) if branch_match else None
        reason_text = (
            reason_match.group(1).strip() if reason_match else "Protected branch update failed"
        )
        return ProtectedBranchRejectedError(
            args,
            returncode,
            stderr,
            branch_name=target_branch,
            reason=reason_text,
        )

    # 4. Large Files Quota (GH001)
    if is_push and ("GH001" in stderr or "large files detected" in stderr.lower()):
        file_match = re.search(
            r"File\s+([^\s]+)\s+is\s+(\d+(?:\.\d+)?)\s*MB;"
            r"\s*this exceeds GitHub's file size limit of\s+(\d+(?:\.\d+)?)\s*MB",
            stderr,
        )
        fname = file_match.group(1) if file_match else None
        fsize = float(file_match.group(2)) if file_match else None
        flimit = float(file_match.group(3)) if file_match else 100.0
        return FileTooLargeRejectedError(
            args,
            returncode,
            stderr,
            filename=fname,
            filesize_mb=fsize,
            limit_mb=flimit,
        )

    # 5. Signed Commits Required (GH008)
    if is_push and (
        "GH008" in stderr
        or "requires signed commits" in stderr.lower()
        or "no valid signature" in stderr.lower()
    ):
        return SignedCommitsRequiredError(args, returncode, stderr)

    # 6. Repository Permission Denied (push-specific 403)
    if is_push and (
        ("permission to" in stderr.lower() and "denied to" in stderr.lower())
        or "write access to repository not granted" in stderr.lower()
    ):
        return RepoPermissionDeniedError(args, returncode, stderr)

    # 7. Network / RPC / Timeout / Protocol failures during push
    if is_push and (
        "RPC failed" in stderr
        or "HTTP 408" in stderr
        or "HTTP 413" in stderr
        or "HTTP 502" in stderr
        or "HTTP 503" in stderr
        or "HTTP 504" in stderr
        or "HTTP 524" in stderr
        or "curl 22" in stderr
        or "curl 28" in stderr
        or "curl 35" in stderr
        or "curl 92" in stderr
        or "curl 56" in stderr
        or "curl 18" in stderr
        or "curl 55" in stderr
        or "Operation timed out" in stderr
        or "Connection timed out" in stderr
        or ("send-pack: unexpected disconnect" in stderr and "hung up unexpectedly" in stderr)
    ):
        payload_mb: float | None = None
        size_match = re.search(r"Writing objects:.*,\s*([\d\.]+)\s*(KiB|MiB|GiB|B)", stderr)
        if size_match:
            val = float(size_match.group(1))
            unit = size_match.group(2)
            if unit == "B":
                payload_mb = val / (1024.0 * 1024.0)
            elif unit == "KiB":
                payload_mb = val / 1024.0
            elif unit == "MiB":
                payload_mb = val
            elif unit == "GiB":
                payload_mb = val * 1024.0

        status_code: int | None = None
        status_match = re.search(r"HTTP\s+(\d{3})", stderr)
        if status_match:
            status_code = int(status_match.group(1))

        curl_code: int | None = None
        curl_match = re.search(r"curl\s+(\d+)", stderr)
        if curl_match:
            curl_code = int(curl_match.group(1))

        is_timeout_err = (
            status_code in (408, 504, 524)
            or (curl_code == 28)
            or (curl_code == 22 and any(c in stderr for c in ("408", "504", "524")))
            or "timed out" in stderr.lower()
        )
        if is_timeout_err:
            kind = "timeout_408"
        elif status_code == 413 or "Request Entity Too Large" in stderr:
            kind = "payload_too_large_413"
        elif (
            status_code in (502, 503) or "Bad Gateway" in stderr or "Service Unavailable" in stderr
        ):
            kind = "gateway_error"
        elif curl_code == 92 or "HTTP/2 stream" in stderr:
            kind = "http2_stream_92"
        elif curl_code in (55, 56) or "SSL_read" in stderr or "Connection reset by peer" in stderr:
            kind = "connection_reset_56"
        elif curl_code == 18 or "outstanding read data" in stderr:
            kind = "partial_transfer_18"
        elif "send-pack: unexpected disconnect" in stderr:
            kind = "sideband_disconnect"
        else:
            kind = "timeout_408" if status_code == 408 else "connection_reset_56"

        return GitNetworkTransferError(
            args,
            returncode,
            stderr,
            kind=kind,
            status_code=status_code,
            curl_code=curl_code,
            payload_mb=payload_mb,
        )

    # 8. Generic push rejected (non-fast-forward, etc.) — MUST BE LAST push check
    if is_push and "rejected" in stderr:
        return PushRejectedError(args, returncode, stderr)

    # --- Pull-specific classification ---
    if is_pull and "Not possible to fast-forward" in stderr:
        return MergeRequiredError(args, returncode, stderr)

    # --- General auth/network classification (applies to all git commands) ---
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
    safe_args = redact_secrets(" ".join(args))
    logger.debug("[git-streaming] Executing in '%s': git %s", p, safe_args)
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
            safe_args,
            redact_secrets(stderr_str.strip()),
        )
    else:
        logger.debug("[git-streaming] Succeeded (exit 0): git %s", safe_args)

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
    except Exception as e:
        logger.debug("Failed extracting conflicts from pygit2 index: %s", e)
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

    try:
        run_git(repo_path, args)
    except GitCommandError as e:
        combined = f"{e.stdout}\n{e.stderr}".lower()
        if "nothing to commit" in combined or "no changes added to commit" in combined:
            raise NothingToCommitError(
                "Nothing to commit, working tree clean",
                stderr=e.stderr,
                stdout=e.stdout,
            ) from e
        raise

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


def push(
    repo_path: Path | str,
    remote: str,
    branch: str,
    *,
    force: bool = False,
    extra_config: dict[str, str] | None = None,
    timeout: float = 1800.0,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Push branch to remote using --progress and --force-with-lease if force=True."""
    p = Path(repo_path)
    args: list[str] = []
    if extra_config:
        for k, v in extra_config.items():
            args.extend(["-c", f"{k}={v}"])
    args.extend(["push", "--progress"])
    if force:
        args.append("--force-with-lease")
    args.extend([remote, branch])

    def on_line(line: str):
        if progress_cb:
            prog = _parse_progress(line)
            if prog:
                progress_cb(prog[0], prog[1])

    code, stdout, stderr = run_git_streaming(
        p,
        args,
        timeout=timeout,
        on_stderr_line=on_line,
        cancel_event=cancel_event,
    )
    if cancel_event and cancel_event.is_set():
        raise GitCommandError(args, -1, "Push operation was cancelled by user")
    if code != 0:
        remote_url = None
        try:
            url_res = run_git(p, ["remote", "get-url", remote], check=False)
            if url_res.returncode == 0 and url_res.stdout.strip():
                remote_url = url_res.stdout.strip()
        except Exception as e:
            logger.debug("Failed getting remote URL: %s", e)
        raise _classify_git_error(args, code, stderr, remote_url=remote_url)


def push_incremental_batches(
    repo_path: Path | str,
    remote: str,
    branch: str,
    *,
    chunk_size: int = 20,
    force: bool = False,
    extra_config: dict[str, str] | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Push commits in incremental batches to avoid payload timeout on large histories.

    1. Determines unpushed commits between remote/branch and HEAD.
    2. If multiple commits exist, pushes checkpoints every `chunk_size` commits.
    3. Concludes by pushing final HEAD.
    """
    p = Path(repo_path)
    clean_branch = branch.replace("refs/heads/", "")
    tracking_ref = f"refs/remotes/{remote}/{clean_branch}"

    # Check if tracking branch exists
    proc_verify = run_git(p, ["rev-parse", "--verify", tracking_ref], check=False)
    if proc_verify.returncode == 0:
        rev_range = f"{tracking_ref}..refs/heads/{clean_branch}"
    else:
        rev_range = f"refs/heads/{clean_branch}"

    proc_list = run_git(p, ["rev-list", "--reverse", rev_range], check=False)
    commits = [c.strip() for c in proc_list.stdout.splitlines() if c.strip()]

    # If 1 or 0 commits, push directly
    if len(commits) <= 1:
        push(
            p,
            remote,
            clean_branch,
            force=force,
            extra_config=extra_config,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )
        return

    # Calculate chunks
    total_commits = len(commits)
    checkpoint_indices = list(range(chunk_size - 1, total_commits, chunk_size))
    if checkpoint_indices and checkpoint_indices[-1] == total_commits - 1:
        checkpoint_indices.pop()

    total_steps = len(checkpoint_indices) + 1
    step = 0

    for idx in checkpoint_indices:
        if cancel_event and cancel_event.is_set():
            raise GitCommandError(["push"], -1, "Push operation was cancelled by user")
        step += 1
        commit_sha = commits[idx]
        if progress_cb:
            progress_cb(
                int((step / total_steps) * 100),
                f"Pushing batch {step}/{total_steps} (commit {idx + 1}/{total_commits})",
            )
        push(
            p,
            remote,
            f"{commit_sha}:refs/heads/{clean_branch}",
            force=force,
            extra_config=extra_config,
            cancel_event=cancel_event,
        )

    # Final step: push HEAD
    if cancel_event and cancel_event.is_set():
        raise GitCommandError(["push"], -1, "Push operation was cancelled by user")
    step += 1
    if progress_cb:
        progress_cb(100, f"Pushing final branch tip ({total_commits}/{total_commits})")
    push(
        p,
        remote,
        clean_branch,
        force=force,
        extra_config=extra_config,
        cancel_event=cancel_event,
    )


def pull(
    repo_path: Path | str,
    remote: str,
    branch: str,
    *,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Pull branch from remote using --progress and --ff-only."""
    p = Path(repo_path)
    args = ["pull", "--progress", "--ff-only", remote, branch]

    def on_line(line: str):
        if progress_cb:
            prog = _parse_progress(line)
            if prog:
                progress_cb(prog[0], prog[1])

    code, stdout, stderr = run_git_streaming(
        p,
        args,
        timeout=600,
        on_stderr_line=on_line,
        cancel_event=cancel_event,
    )
    if cancel_event and cancel_event.is_set():
        raise GitCommandError(args, -1, "Pull operation was cancelled by user")
    if code != 0:
        remote_url = None
        try:
            url_res = run_git(p, ["remote", "get-url", remote], check=False)
            if url_res.returncode == 0 and url_res.stdout.strip():
                remote_url = url_res.stdout.strip()
        except Exception as e:
            logger.debug("Failed getting remote URL: %s", e)
        raise _classify_git_error(args, code, stderr, remote_url=remote_url)


def fetch(
    repo_path: Path | str,
    remote: str,
    *,
    db_conn: sqlite3.Connection | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Fetch from remote with --progress and --prune, recording timestamp in settings."""
    p = Path(repo_path)
    args = ["fetch", "--progress", "--prune", remote]

    def on_line(line: str):
        if progress_cb:
            prog = _parse_progress(line)
            if prog:
                progress_cb(prog[0], prog[1])

    code, stdout, stderr = run_git_streaming(
        p,
        args,
        timeout=600,
        on_stderr_line=on_line,
        cancel_event=cancel_event,
    )
    if cancel_event and cancel_event.is_set():
        raise GitCommandError(args, -1, "Fetch operation was cancelled by user")
    if code != 0:
        remote_url = None
        try:
            url_res = run_git(p, ["remote", "get-url", remote], check=False)
            if url_res.returncode == 0 and url_res.stdout.strip():
                remote_url = url_res.stdout.strip()
        except Exception as e:
            logger.debug("Failed getting remote URL: %s", e)
        raise _classify_git_error(args, code, stderr, remote_url=remote_url)

    # Record fetch timestamp in settings
    try:
        conn = db_conn
        should_close = False
        if conn is None:
            from wrench.storage import db

            conn = db.get_connection()
            should_close = True

        try:
            from wrench.storage import repo_registry, settings

            now_iso = datetime.now(timezone.utc).isoformat()
            rec = None
            try:
                rec = repo_registry.get_repo_by_path(conn, str(p))
            except Exception as e:
                logger.debug("Failed getting repo record in fetch: %s", e)

            if rec:
                settings.set_setting(conn, f"repo.{rec.id}.remote_last_fetch.{remote}", now_iso)
            settings.set_setting(conn, f"remote_last_fetch.{remote}", now_iso)
        finally:
            if should_close and conn:
                conn.close()

    except Exception as e:
        logger.warning("[git] Failed to record fetch timestamp in settings: %s", e)


def clone_repo(
    url: str,
    dest: Path | str,
    *,
    timeout: int = 600,
    progress_cb: Callable[[int, str], None] | None = None,
    cancel_event: threading.Event | None = None,
    branch: str | None = None,
    recursive: bool = False,
    filter_spec: str | None = None,
    sparse: bool = False,
) -> CloneResult:
    """Clone a repository into a temporary directory and atomically move on success."""
    clean_url = validate_clone_url(url)
    clean_branch: str | None = None
    if branch is not None and branch.strip():
        clean_branch = validate_git_ref(branch)

    if filter_spec not in (None, "", "none", "blob:none", "tree:0"):
        raise ValueError(f"Unsupported partial-clone filter specification: {filter_spec}")

    d = Path(dest)
    if d.exists():
        if d.is_file() or any(d.iterdir()):
            raise GitCommandError(
                ["clone", redact_secrets(clean_url), str(d)],
                1,
                f"Destination path '{d}' exists and is not empty.",
            )

    d.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="wrench-clone-", dir=d.parent))

    def on_line(line: str):
        if progress_cb:
            prog = _parse_progress(line)
            if prog:
                progress_cb(prog[0], prog[1])

    clone_args = [
        "-c",
        "credential.helper=wrench",
        "-c",
        "credential.useHttpPath=true",
        "clone",
        "--progress",
    ]
    if filter_spec and filter_spec != "none":
        clone_args.extend(["--filter", filter_spec])
    if sparse:
        clone_args.append("--sparse")
    if clean_branch:
        clone_args.extend(["--branch", clean_branch])
    if recursive:
        clone_args.append("--recursive")
    clone_args.extend(["--", clean_url, str(temp_dir.name)])

    try:
        code, stdout, stderr = run_git_streaming(
            d.parent,
            clone_args,
            timeout=timeout,
            on_stderr_line=on_line,
            cancel_event=cancel_event,
        )

        if cancel_event and cancel_event.is_set():
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise CloneAbortedError("Clone operation was cancelled by user.")

        if code != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise _classify_git_error(
                ["clone", "--", redact_secrets(clean_url), str(d)],
                code,
                redact_secrets(stderr),
                remote_url=clean_url,
            )

        if d.exists() and any(d.iterdir()):
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise GitCommandError(
                ["clone", "--", redact_secrets(clean_url), str(d)],
                1,
                f"Destination path '{d}' already exists.",
            )

        shutil.move(str(temp_dir), str(d))

        # Write credential config into fresh clone (only if not already set)
        ensure_wrench_credential_config(d)

        return CloneResult(path=d)

    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


clone_repository = clone_repo


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
        handle = engine.open_repo(p, configure_credentials=False)
        snapshots.take_snapshot(handle, "pre_risky_op")
    except Exception as e:
        logger.debug("Failed taking pre_risky_op snapshot: %s", e)

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
        handle = engine.open_repo(p, configure_credentials=False)
        snapshots.take_snapshot(handle, "pre_risky_op")
    except Exception as e:
        logger.debug("Failed taking pre_risky_op snapshot: %s", e)

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


def write_commit_graph(
    repo_path: Path | str,
    *,
    reachable: bool = True,
    changed_paths: bool = True,
    timeout: int = 120,
) -> CommitGraphStats:
    """Write/update .git/objects/info/commit-graph in a lock- and empty-repo-safe manner."""
    p = Path(repo_path)
    git_dir = resolve_git_dir(p)

    try:
        repo = pygit2.Repository(str(p))
        if repo.head_is_unborn:
            return CommitGraphStats(written=False, duration_ms=0, skipped_reason="empty_repo")
    except pygit2.GitError as exc:
        logger.debug("Unable to open repo before commit-graph write (%s): %s", p, exc)

    graph_lock = git_dir / "objects" / "info" / "commit-graph.lock"
    index_lock = git_dir / "index.lock"
    if graph_lock.exists() or index_lock.exists():
        return CommitGraphStats(written=False, duration_ms=0, skipped_reason="locked")

    args = ["commit-graph", "write"]
    if reachable:
        args.append("--reachable")
    if changed_paths:
        args.append("--changed-paths")
    args.append("--no-progress")

    started = time.monotonic()
    try:
        run_git(p, args, timeout=timeout, check=True)
    except GitCommandError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stderr_lower = (exc.stderr or "").lower()
        if (
            ".lock" in stderr_lower
            or "file exists" in stderr_lower
            or "another git process" in stderr_lower
        ):
            logger.info("Skipping background commit-graph maintenance due to git lock: %s", p)
            return CommitGraphStats(
                written=False,
                duration_ms=elapsed_ms,
                skipped_reason="locked",
            )
        raise

    elapsed_ms = int((time.monotonic() - started) * 1000)
    graph_file = git_dir / "objects" / "info" / "commit-graph"
    graph_chain = git_dir / "objects" / "info" / "commit-graphs" / "commit-graph-chain"
    size_bytes = 0
    if graph_file.is_file():
        size_bytes = graph_file.stat().st_size
    elif graph_chain.is_file():
        size_bytes = graph_chain.stat().st_size

    return CommitGraphStats(
        written=True,
        duration_ms=elapsed_ms,
        skipped_reason=None,
        graph_file_size_bytes=size_bytes,
    )
