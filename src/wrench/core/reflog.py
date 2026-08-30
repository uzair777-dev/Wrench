"""FR-1.10: Reflog read and restore-to-ref.

Reads the reflog of HEAD. restore_to_ref resets current HEAD to the
specified reflog entry's target SHA.
"""

from datetime import datetime, timezone

from .engine import ReflogEntry, RepoHandle
from .write_ops import run_git


def get_reflog(repo: RepoHandle) -> list[ReflogEntry]:
    """Read the reflog for HEAD."""
    r = repo.pygit2_repo
    if r.head_is_unborn:
        return []

    entries: list[ReflogEntry] = []
    try:
        head_ref = r.references["HEAD"]
        for entry in head_ref.log():
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
    except (KeyError, Exception):
        # Fallback to git reflog command if pygit2 reflog lookup fails
        result = run_git(
            repo.path,
            ["reflog", "--format=%H|%gs|%aI"],
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


def restore_to_ref(repo: RepoHandle, sha: str) -> None:
    """Reset current branch HEAD hard to the given commit SHA."""
    from . import exceptions, read_ops, snapshots

    status = read_ops.get_status(repo)
    if getattr(status, "merge_in_progress", False):
        raise exceptions.RepoBusyError("reflog restore", "merge")
    if getattr(status, "rebase_in_progress", False):
        raise exceptions.RepoBusyError("reflog restore", "rebase")

    snapshots.take_snapshot(repo, "pre_risky_op")
    run_git(repo.path, ["reset", "--hard", sha])
    repo.pygit2_repo.index.read()
