"""Cross-platform active Git process & lock contention guard."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

STALE_THRESHOLD_SECONDS = 5.0


def is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is actively running."""
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except ImportError:
        pass

    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        # Process exists but owned by another user
        return True
    except Exception:
        return False


def get_process_cmdline(pid: int) -> str:
    """Get the command line of a process if accessible."""
    if pid <= 0:
        return ""
    try:
        import psutil

        p = psutil.Process(pid)
        return " ".join(p.cmdline()) or p.name()
    except Exception:
        pass

    # Linux /proc fallback
    proc_cmdline = Path(f"/proc/{pid}/cmdline")
    if proc_cmdline.exists():
        try:
            raw = proc_cmdline.read_bytes()
            parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\x00") if p]
            return " ".join(parts)
        except Exception:
            pass
    return ""


def find_active_git_processes_for_repo(repo_path: Path | str) -> list[tuple[int, str]]:
    """Scan system processes to detect any git processes operating on repo_path."""
    active_processes: list[tuple[int, str]] = []
    repo_str = str(Path(repo_path).resolve())

    # Check via /proc on Linux if psutil is not available
    proc_dir = Path("/proc")
    if proc_dir.exists():
        try:
            for entry in proc_dir.iterdir():
                if entry.name.isdigit():
                    pid = int(entry.name)
                    cmd = get_process_cmdline(pid)
                    if (
                        cmd
                        and ("git" in cmd)
                        and (repo_str in cmd or "pull" in cmd or "fetch" in cmd)
                    ):
                        active_processes.append((pid, cmd))

        except Exception:
            pass
    return active_processes


def inspect_locks(repo_path: Path | str) -> list[tuple[Path, int | None, str, float]]:
    """Inspect repository for any active or stale .lock files.

    Returns:
        List of tuples: (lock_path, pid_if_found, process_name_or_cmd, age_seconds)
    """
    p = Path(repo_path)
    git_dir = p / ".git" if (p / ".git").is_dir() else p
    if not git_dir.exists():
        return []

    found_locks: list[tuple[Path, int | None, str, float]] = []
    now = time.time()

    # Known lock file locations
    candidate_locks = [
        git_dir / "index.lock",
        git_dir / "HEAD.lock",
        git_dir / "MERGE_RR.lock",
        git_dir / "config.lock",
        git_dir / "rebase-merge",
        git_dir / "rebase-apply",
    ]

    # Search refs/heads locks
    refs_heads = git_dir / "refs" / "heads"
    if refs_heads.exists():
        try:
            for lock in refs_heads.glob("*.lock"):
                candidate_locks.append(lock)
        except Exception:
            pass

    for lock_path in candidate_locks:
        if not lock_path.exists():
            continue
        try:
            stat = lock_path.stat()
            age = now - stat.st_mtime
            pid: int | None = None
            cmd = ""

            # Check if lock file contains PID (some tools write PID to lock file)
            if lock_path.is_file():
                try:
                    content = lock_path.read_text(encoding="utf-8", errors="replace").strip()
                    if content.isdigit():
                        pid = int(content)
                except Exception:
                    pass

            # If no PID in file, look for active git processes for this repo
            if pid is None:
                active_procs = find_active_git_processes_for_repo(repo_path)
                if active_procs:
                    pid, cmd = active_procs[0]
            else:
                cmd = get_process_cmdline(pid)

            found_locks.append((lock_path, pid, cmd or "git process", age))
        except FileNotFoundError:
            continue
        except Exception as e:
            logger.debug("Error inspecting lock %s: %s", lock_path, e)

    return found_locks


@dataclass
class GuardResult:
    status: str  # "ready" | "busy" | "stale_lock"
    lock_path: Path | None = None
    pid: int | None = None
    process_cmd: str | None = None
    age_seconds: float = 0.0


def acquire_repo_guard(
    repo_path: Path | str,
    timeout: float = 3.0,
    poll_interval: float = 0.3,
) -> GuardResult:
    """Check repository lock status with adaptive auto-wait.

    If an active process is holding a lock, pauses and retries up to `timeout` seconds.
    If the lock clears, returns status="ready".
    If lock persists with active process, returns status="busy".
    If lock persists with dead process or age >= 5.0s, returns status="stale_lock".
    """
    deadline = time.time() + max(0.0, timeout)

    while True:
        locks = inspect_locks(repo_path)
        if not locks:
            return GuardResult(status="ready")

        lock_path, pid, cmd, age = locks[0]

        is_alive = is_pid_alive(pid) if pid is not None else False

        # If process is actively alive or lock is very fresh (< STALE_THRESHOLD_SECONDS)
        if is_alive or (age < STALE_THRESHOLD_SECONDS and pid is None):
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(min(poll_interval, remaining))
                continue
            return GuardResult(
                status="busy",
                lock_path=lock_path,
                pid=pid,
                process_cmd=cmd or "git background operation",
                age_seconds=age,
            )

        # Process is dead or lock is older than threshold -> stale lock
        return GuardResult(
            status="stale_lock",
            lock_path=lock_path,
            pid=pid,
            process_cmd=cmd or "inactive process",
            age_seconds=age,
        )


def remove_lock(lock_path: Path | str) -> bool:
    """Safely remove a stale lock file or directory."""
    p = Path(lock_path)
    if not p.exists():
        return True
    try:
        if p.is_dir():
            import shutil

            shutil.rmtree(p)
        else:
            p.unlink()
        logger.info("Successfully removed lock file: %s", lock_path)
        return True
    except Exception as e:
        logger.warning("Failed to remove lock %s: %s", lock_path, e)
        return False
