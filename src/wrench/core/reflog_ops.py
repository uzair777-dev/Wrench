"""Git reflog operations (read reflog, restore to reflog entry, branch from reflog)."""

import logging
from datetime import datetime, timezone

from . import exceptions, read_ops, snapshots
from .models import ReflogEntry
from .write_ops import run_git

logger = logging.getLogger(__name__)


def list_reflog(repo, ref: str = "HEAD", limit: int = 100) -> list[ReflogEntry]:
    """Read reflog entries for the given reference (defaults to HEAD)."""
    r = repo.pygit2_repo
    if r.head_is_unborn:
        return []

    entries: list[ReflogEntry] = []
    try:
        if ref == "HEAD":
            ref_obj = r.references["HEAD"]
        elif ref in r.references:
            ref_obj = r.references[ref]
        else:
            ref_obj = r.lookup_reference(ref)

        if ref_obj is not None:
            for entry in ref_obj.log():
                timestamp = datetime.fromtimestamp(
                    entry.committer.time,
                    tz=timezone.utc,
                ).isoformat()
                entries.append(
                    ReflogEntry(
                        sha=str(entry.oid_new),
                        message=entry.message or "",
                        timestamp=timestamp,
                    )
                )
                if len(entries) >= limit:
                    break
    except Exception as e:
        logger.debug("[reflog] pygit2 reflog lookup failed for %s: %s", ref, e)

    if not entries:
        # Fallback to git CLI reflog show
        result = run_git(
            repo.path,
            ["reflog", "show", f"-n{limit}", "--format=%H|%gs|%aI", "--", ref],
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            for line in result.stdout.strip().splitlines():
                parts = line.split("|", 2)
                if len(parts) == 3:
                    entries.append(
                        ReflogEntry(
                            sha=parts[0],
                            message=parts[1],
                            timestamp=parts[2],
                        )
                    )

    return entries


def reset_to_reflog_entry(repo, sha: str, mode: str = "hard") -> None:
    """Reset current HEAD to the specified reflog SHA with automatic safety snapshot."""
    status = read_ops.get_status(repo)
    if getattr(status, "merge_in_progress", False):
        raise exceptions.RepoBusyError("reflog restore", "merge")
    if getattr(status, "rebase_in_progress", False):
        raise exceptions.RepoBusyError("reflog restore", "rebase")

    snapshots.take_snapshot(repo, "pre_risky_op")
    valid_modes = {"hard", "soft", "mixed"}
    reset_mode = mode if mode in valid_modes else "hard"
    run_git(repo.path, ["reset", f"--{reset_mode}", sha])
    repo.pygit2_repo.index.read()


def create_branch_from_reflog(repo, branch_name: str, sha: str) -> None:
    """Create a new branch pointing to a specific reflog SHA."""
    run_git(repo.path, ["branch", "--", branch_name, sha])
