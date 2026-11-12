"""Visual Interactive Rebase core sequencer (VP-2, FR-3.5, FR-10.1)."""

from __future__ import annotations

import itertools
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

import pygit2

from .exceptions import (
    CLITimeoutError,
    DirtyTreeError,
    EmptyCommitMessageError,
    GitCommandError,
    RepoBusyError,
    StaleLockDetectedError,
    WrenchGitError,
    WrenchRepoNotFoundError,
)
from .models import RebaseResult, RebaseTodoEntry
from .paths import resolve_git_dir
from .security_sanitizer import redact_secrets
from .write_ops import _check_clean_working_tree, _extract_conflicts, _git_env

logger = logging.getLogger(__name__)

VALID_REBASE_ACTIONS: tuple[str, ...] = (
    "pick",
    "reword",
    "edit",
    "squash",
    "fixup",
    "drop",
)
MAX_INTERACTIVE_REBASE_COMMITS: int = 1000
_OID_RE = re.compile(r"^[0-9a-fA-F]{4,64}$")


def _validate_commit_ref_or_oid(ref: str) -> str:
    """Validate a base commit OID or ref before passing it to git CLI."""
    if not isinstance(ref, str) or not ref:
        raise WrenchGitError("Base commit reference must not be empty.")
    if ref.startswith("-"):
        raise WrenchGitError(f"Invalid base commit reference starting with '-': {ref!r}")
    if ".." in ref:
        raise WrenchGitError(f"Invalid base commit reference containing '..': {ref!r}")
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in ref):
        raise WrenchGitError(f"Invalid whitespace or control character in ref: {ref!r}")
    return ref


def _validate_todo_entries(entries: Sequence[RebaseTodoEntry]) -> None:
    """Validate interactive rebase todo instructions before writing plan JSON."""
    if not entries:
        raise WrenchGitError("Interactive rebase plan must contain at least one commit.")

    first_action = entries[0].action
    if first_action in ("squash", "fixup"):
        raise WrenchGitError("Cannot squash/fixup the first commit — no previous commit above it")

    for entry in entries:
        if entry.action not in VALID_REBASE_ACTIONS:
            raise WrenchGitError(f"Unsupported interactive rebase action: {entry.action!r}")
        if not _OID_RE.match(entry.oid):
            raise WrenchGitError(f"Invalid commit OID in rebase plan: {entry.oid!r}")
        if entry.short_oid and not _OID_RE.match(entry.short_oid):
            raise WrenchGitError(f"Invalid short OID in rebase plan: {entry.short_oid!r}")
        if entry.action == "reword" and entry.new_message is not None:
            if not entry.new_message.strip():
                raise EmptyCommitMessageError("Reworded commit message must not be empty.")


def build_interactive_rebase_cli_args(
    base_oid: str,
    *,
    autostash: bool = True,
    autosquash: bool = True,
) -> list[str]:
    """Construct the exact `git rebase -i` argument list with `--` separator (SEC-1)."""
    clean_base = _validate_commit_ref_or_oid(base_oid)
    args = ["rebase", "-i"]
    if autostash:
        args.append("--autostash")
    if autosquash:
        args.append("--autosquash")
    args.extend(["--", clean_base])
    return args


def get_interactive_rebase_target_label(
    repo_path: Path | str,
    base_oid: str,
) -> tuple[str, str, bool]:
    """Return `(head_label, base_label, is_detached)` using pygit2 without subprocesses."""
    p = Path(repo_path)
    try:
        repo = pygit2.Repository(str(p))
    except pygit2.GitError as exc:
        raise WrenchRepoNotFoundError(str(exc)) from exc

    is_detached = bool(repo.head_is_detached)
    if repo.head_is_unborn:
        head_label = "unborn HEAD"
    elif is_detached:
        head_label = "detached HEAD"
    else:
        head_label = repo.head.shorthand

    clean_base = _validate_commit_ref_or_oid(base_oid)
    base_label = clean_base[:7]
    try:
        target_commit = repo.revparse_single(clean_base).peel(pygit2.Commit)
        target_id = target_commit.id
        base_label = str(target_id)[:7]
        for ref_name in repo.references:
            try:
                ref = repo.references[ref_name]
                resolved = ref.resolve()
                if resolved.target == target_id:
                    if ref_name.startswith("refs/heads/"):
                        base_label = ref_name.removeprefix("refs/heads/")
                        break
                    if ref_name.startswith("refs/tags/"):
                        base_label = ref_name.removeprefix("refs/tags/")
            except pygit2.GitError, KeyError:
                continue
    except pygit2.GitError:
        pass

    return head_label, base_label, is_detached


def list_commits_for_interactive_rebase_checked(
    repo_path: Path | str,
    base_oid: str,
    *,
    limit: int = MAX_INTERACTIVE_REBASE_COMMITS,
) -> tuple[list[RebaseTodoEntry], bool]:
    """Return `(entries, is_truncated)` in oldest-first `git rebase -i` order via pygit2."""
    p = Path(repo_path)
    try:
        repo = pygit2.Repository(str(p))
    except pygit2.GitError as exc:
        raise WrenchRepoNotFoundError(str(exc)) from exc

    if repo.head_is_unborn:
        return ([], False)

    clean_base = _validate_commit_ref_or_oid(base_oid)
    try:
        head_commit = repo.head.peel(pygit2.Commit)
    except (pygit2.GitError, KeyError) as exc:
        raise WrenchGitError(f"Failed to resolve HEAD commit: {exc}") from exc

    try:
        base_commit = repo.revparse_single(clean_base).peel(pygit2.Commit)
    except (pygit2.GitError, KeyError) as exc:
        raise WrenchGitError(f"Failed to resolve base commit '{clean_base}': {exc}") from exc

    merge_base_oid = repo.merge_base(head_commit.id, base_commit.id)
    if merge_base_oid is None or merge_base_oid != base_commit.id:
        raise WrenchGitError(f"Base commit '{clean_base}' is not an ancestor of HEAD.")

    if head_commit.id == base_commit.id:
        return ([], False)

    capped = max(1, min(int(limit), MAX_INTERACTIVE_REBASE_COMMITS))
    walker = repo.walk(head_commit.id, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE)
    walker.hide(base_commit.id)

    collected = list(itertools.islice(walker, capped + 1))
    is_truncated = len(collected) > capped
    if is_truncated:
        collected = collected[:capped]

    entries: list[RebaseTodoEntry] = []
    for commit in collected:
        oid_str = str(commit.id)
        msg_lines = commit.message.splitlines() if commit.message else []
        summary = msg_lines[0].strip() if msg_lines else ""
        author_name = (commit.author.name if commit.author else "") or "Unknown"
        entries.append(
            RebaseTodoEntry(
                action="pick",
                oid=oid_str,
                short_oid=oid_str[:7],
                summary=summary,
                author=author_name,
                new_message=None,
            )
        )

    return (entries, is_truncated)


def list_commits_for_interactive_rebase(
    repo_path: Path | str,
    base_oid: str,
    *,
    limit: int = MAX_INTERACTIVE_REBASE_COMMITS,
) -> list[RebaseTodoEntry]:
    """Return commits in `base_oid..HEAD` in oldest-first order (capped at `limit`)."""
    entries, _is_truncated = list_commits_for_interactive_rebase_checked(
        repo_path,
        base_oid,
        limit=limit,
    )
    return entries


def _ensure_pythonpath_contains_wrench(env: dict[str, str]) -> None:
    package_root = str(Path(__file__).resolve().parents[2])
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p] if existing else []
    if package_root not in parts:
        env["PYTHONPATH"] = os.pathsep.join([package_root, *parts]) if parts else package_root


def run_interactive_rebase(
    repo_path: Path | str,
    base_oid: str,
    entries: Sequence[RebaseTodoEntry],
    *,
    autostash: bool = True,
    autosquash: bool = True,
    timeout: int = 300,
) -> RebaseResult:
    """Execute `git -C <repo> rebase -i` using a `0o600` JSON plan and editor helper."""
    p = Path(repo_path)
    try:
        repo = pygit2.Repository(str(p))
    except pygit2.GitError as exc:
        raise WrenchRepoNotFoundError(str(exc)) from exc

    if repo.head_is_unborn:
        raise WrenchGitError(
            "Cannot perform interactive rebase on an empty repository (unborn HEAD)."
        )

    _validate_todo_entries(entries)
    args = build_interactive_rebase_cli_args(
        base_oid,
        autostash=autostash,
        autosquash=autosquash,
    )
    git_dir = resolve_git_dir(p)

    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        raise RepoBusyError("interactive rebase", "rebase")

    index_lock = git_dir / "index.lock"
    if index_lock.exists():
        raise StaleLockDetectedError(str(index_lock))

    if not autostash:
        _check_clean_working_tree(p)

    messages_by_oid: dict[str, str] = {}
    pending_message_slots: list[str | None] = []
    serialized_entries: list[dict[str, str | None]] = []
    for entry in entries:
        serialized_entries.append(
            {
                "action": entry.action,
                "oid": entry.oid,
                "short_oid": entry.short_oid,
                "summary": entry.summary,
                "new_message": entry.new_message,
            }
        )
        if entry.action in ("reword", "squash"):
            pending_message_slots.append(entry.new_message)
            if entry.new_message is not None:
                messages_by_oid[entry.oid] = entry.new_message

    plan_payload = {
        "version": 1,
        "git_dir": str(git_dir),
        "entries": serialized_entries,
        "messages_by_oid": messages_by_oid,
        "pending_message_slots": pending_message_slots,
    }

    with tempfile.TemporaryDirectory(prefix="wrench-rebase-") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        os.chmod(tmp_dir, 0o700)
        plan_path = tmp_dir / "plan.json"
        plan_path.write_text(json.dumps(plan_payload, indent=2), encoding="utf-8")
        os.chmod(plan_path, 0o600)

        env = _git_env()
        _ensure_pythonpath_contains_wrench(env)
        helper_cmd = (
            f"{shlex.quote(sys.executable)} -m wrench.core.rebase_editor_helper "
            f"{shlex.quote(str(plan_path))}"
        )
        env["GIT_SEQUENCE_EDITOR"] = helper_cmd
        env["GIT_EDITOR"] = helper_cmd

        cmd = ["git", *args]
        logger.debug("[git] Executing interactive rebase in '%s': %s", p, " ".join(args))
        try:
            result = subprocess.run(
                cmd,
                cwd=p,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CLITimeoutError(
                args,
                timeout,
                redact_secrets(str(exc)),
                timeout=float(timeout),
            ) from exc

    rebase_active = (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()
    conflicts = _extract_conflicts(p)

    if result.returncode == 0:
        if rebase_active:
            return RebaseResult(status="paused", conflicted_files=conflicts)
        return RebaseResult(status="complete")

    clean_stderr = redact_secrets((result.stderr or "").strip())
    clean_stdout = redact_secrets((result.stdout or "").strip())
    if (
        conflicts
        or "CONFLICT" in clean_stdout
        or "Could not apply" in clean_stdout
        or "resolve all conflicts" in clean_stderr
    ):
        return RebaseResult(status="conflict", conflicted_files=conflicts)

    lower_err = clean_stderr.lower()
    if "index.lock" in lower_err or ".lock" in lower_err or "another git process" in lower_err:
        raise StaleLockDetectedError(str(index_lock))

    if "your local changes" in lower_err or "cannot rebase: you have unstaged changes" in lower_err:
        raise DirtyTreeError([], stderr=clean_stderr)

    raise GitCommandError(args, result.returncode, clean_stderr, stdout=clean_stdout)
