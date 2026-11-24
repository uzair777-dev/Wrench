"""Git worktrees lifecycle management and cross-worktree operations (VP-3)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from wrench.core import write_ops
from wrench.core.exceptions import (
    GitCommandError,
    WorktreeAlreadyCheckedOutError,
    WrenchGitError,
)
from wrench.core.models import WorktreeInfo

logger = logging.getLogger(__name__)


def list_worktrees(repo_path: Path | str) -> list[WorktreeInfo]:
    """Parse git worktree list --porcelain -z into structured WorktreeInfo entries."""
    r_path = Path(repo_path)
    try:
        res = write_ops.run_git(
            r_path,
            ["worktree", "list", "--porcelain", "-z"],
            check=True,
        )
    except GitCommandError as e:
        logger.warning("git worktree list failed for %s: %s", r_path, e.stderr)
        return []

    entries: list[WorktreeInfo] = []
    # In -z mode, lines within a record are separated by \0, and records are separated by \0\0
    stdout_bytes = res.stdout if isinstance(res.stdout, bytes) else res.stdout.encode("utf-8")
    blocks = stdout_bytes.strip(b"\x00").split(b"\x00\x00") if stdout_bytes else []

    for idx, block in enumerate(blocks):
        if not block:
            continue
        lines = block.split(b"\x00")
        wt_path = ""
        head_oid = ""
        branch_name: str | None = None
        is_bare = False
        is_locked = False
        lock_reason: str | None = None
        is_prunable = False
        is_detached = False

        for line_b in lines:
            if not line_b:
                continue
            line = line_b.decode("utf-8", errors="replace")
            if line.startswith("worktree "):
                wt_path = line[len("worktree ") :].strip()
            elif line.startswith("HEAD "):
                head_oid = line[len("HEAD ") :].strip()
            elif line.startswith("branch "):
                ref = line[len("branch ") :].strip()
                if ref.startswith("refs/heads/"):
                    branch_name = ref[len("refs/heads/") :]
                else:
                    branch_name = ref
            elif line == "bare":
                is_bare = True
            elif line.startswith("locked"):
                is_locked = True
                reason_part = line[len("locked") :].strip()
                if reason_part:
                    lock_reason = reason_part
            elif line.startswith("prunable"):
                is_prunable = True
            elif line == "detached":
                is_detached = True

        if wt_path:
            entries.append(
                WorktreeInfo(
                    path=wt_path,
                    head_oid=head_oid,
                    branch_name=branch_name,
                    is_bare=is_bare,
                    is_locked=is_locked,
                    lock_reason=lock_reason,
                    is_prunable=is_prunable,
                    is_main=(idx == 0),
                    is_detached=is_detached,
                )
            )

    return entries


def format_worktree_path(
    repo_path: Path | str,
    branch_name: str,
    template: str | None = None,
) -> Path:
    """Resolve destination worktree directory from template."""
    p = Path(repo_path).resolve()
    repo_name = p.name
    branch_slug = re.sub(r"[^\w\-.]", "-", branch_name).strip("-")
    if not branch_slug:
        branch_slug = "worktree"
    tmpl = template or "../{repo_name}-{branch_slug}"
    resolved_rel = tmpl.format(
        repo_name=repo_name,
        branch_slug=branch_slug,
        slug=branch_slug,
        branch=branch_slug,
        branch_name=branch_name,
    )
    # Resolve relative to repo directory (p)
    return (p / resolved_rel).resolve()


def add_worktree(
    repo_path: Path | str,
    target_path: Path | str,
    branch: str | None = None,
    *,
    branch_name: str | None = None,
    create_branch: bool = False,
    new_branch: bool = False,
    commit: str | None = None,
) -> WorktreeInfo:
    """Create a new linked git worktree."""
    r_path = Path(repo_path)
    tgt = Path(target_path).resolve()
    eff_branch = branch or branch_name or ""
    eff_create = create_branch or new_branch

    if tgt.exists() and any(tgt.iterdir()):
        raise WrenchGitError(f"Target directory exists and is not empty: {tgt}")

    cmd = ["worktree", "add"]
    if eff_create:
        cmd.extend(["-b", eff_branch, str(tgt)])
        if commit:
            cmd.extend(["--", commit])
    else:
        cmd.extend([str(tgt)])
        if eff_branch:
            cmd.extend(["--", eff_branch])

    try:
        write_ops.run_git(r_path, cmd, check=True)
    except GitCommandError as e:
        stderr_text = e.stderr or ""
        if "already checked out at" in stderr_text or "already used by worktree at" in stderr_text:
            match = re.search(r"already (?:checked out|used by worktree) at '([^']+)'", stderr_text)
            existing_path = match.group(1) if match else "unknown"
            raise WorktreeAlreadyCheckedOutError(eff_branch, existing_path) from e
        raise WrenchGitError(f"git worktree add failed: {stderr_text}") from e

    wts = list_worktrees(r_path)
    for w in wts:
        if Path(w.path).resolve() == tgt:
            return w

    return WorktreeInfo(
        path=str(tgt),
        head_oid="",
        branch_name=eff_branch,
        is_bare=False,
        is_locked=False,
        is_main=False,
    )


def lock_worktree(
    repo_path: Path | str,
    worktree_path: Path | str,
    reason: str = "",
) -> None:
    """Lock a worktree to prevent accidental pruning or removal."""
    cmd = ["worktree", "lock", str(worktree_path)]
    if reason.strip():
        cmd.extend(["--reason", reason.strip()])
    write_ops.run_git(repo_path, cmd, check=True)


def unlock_worktree(repo_path: Path | str, worktree_path: Path | str) -> None:
    """Unlock a locked worktree."""
    write_ops.run_git(repo_path, ["worktree", "unlock", str(worktree_path)], check=True)


def remove_worktree(
    repo_path: Path | str,
    worktree_path: Path | str,
    *,
    force: bool = False,
) -> None:
    """Remove a linked worktree from disk and git reference database."""
    cmd = ["worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(worktree_path))
    write_ops.run_git(repo_path, cmd, check=True)


def prune_worktrees(repo_path: Path | str) -> None:
    """Prune stale linked worktree references for deleted directories."""
    write_ops.run_git(repo_path, ["worktree", "prune"], check=True)


def cross_worktree_cherry_pick(
    target_worktree_path: Path | str,
    commit_oid: str,
) -> None:
    """Cherry-pick a commit into the target worktree's current branch."""
    write_ops.run_git(target_worktree_path, ["cherry-pick", "--", commit_oid], check=True)
