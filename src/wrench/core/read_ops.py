"""Git read operations — pygit2-backed.

All read operations (status, diff, log, blame) go through this module.
UI code never calls this module directly — it goes through core.engine.
"""

import hashlib
import logging
import os
import re
import stat
import subprocess
import threading
from collections import OrderedDict
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import pygit2

from . import ssh_agent
from .engine import (
    BlameLine,
    Commit,
    Diff,
    DiffLine,
    FileChange,
    FileStat,
    Hunk,
    LogFilter,
    RefLabel,
    RepoHandle,
    RepoStatus,
)
from .models import LogPage
from .paths import resolve_git_dir

logger = logging.getLogger(__name__)

_HUNK_HDR_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_PORCELAIN_CONFLICT_CODES = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})
_PORCELAIN_STAGED_MAP = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "added",
    "T": "modified",
}
_PORCELAIN_UNSTAGED_MAP = {
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "T": "modified",
}
_GIT_NAME_STATUS_MAP = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "added",
    "T": "modified",
}


def _git_read_env() -> dict[str, str]:
    """Build non-interactive subprocess environment for read fallbacks (SEC-1)."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    env["LC_ALL"] = "C"
    ssh_agent.configure_ssh_env(env)
    return env


def _is_sparse_checkout_active(r: pygit2.Repository, repo_path: Path) -> bool:
    """Return True if an active sparse-checkout file and core.sparseCheckout config exist."""
    try:
        git_dir = resolve_git_dir(repo_path)
        if not (git_dir / "info" / "sparse-checkout").is_file():
            return False
    except Exception as exc:
        logger.debug("Unable to resolve git dir for sparse status check: %s", exc)
        return False

    try:
        fresh_r = pygit2.Repository(str(repo_path))
        return bool(fresh_r.config.get_bool("core.sparsecheckout"))
    except (KeyError, pygit2.GitError, ValueError, OSError) as exc:
        logger.debug("Sparse checkout config check fell back to False: %s", exc)
        return False


def _git_status_sparse(
    repo_path: Path,
) -> tuple[bool, list[FileChange], list[FileChange], list[str], list[FileChange]] | None:
    """Query git status honoring sparse-checkout skip-worktree bits via NUL-delimited CLI."""
    try:
        res = subprocess.run(
            ["git", "--no-optional-locks", "status", "--porcelain=v1", "-z", "-unormal"],
            cwd=repo_path,
            capture_output=True,
            text=False,
            env=_git_read_env(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Sparse git status fallback failed: %s", exc)
        return None

    if res.returncode != 0:
        logger.debug("Sparse git status returned %d", res.returncode)
        return None

    has_conflicts = False
    staged: list[FileChange] = []
    unstaged: list[FileChange] = []
    untracked: list[str] = []
    partially_staged: list[FileChange] = []

    tokens = res.stdout.split(b"\x00")
    i = 0
    while i < len(tokens):
        rec = tokens[i]
        i += 1
        if not rec or len(rec) < 4:
            continue
        xy = rec[:2].decode("ascii", errors="replace")
        filepath = rec[3:].decode("utf-8", errors="replace")
        orig_path: str | None = None
        if xy[0] in ("R", "C") or xy[1] in ("R", "C"):
            if i < len(tokens):
                orig_path = tokens[i].decode("utf-8", errors="replace")
                i += 1

        if xy == "??":
            untracked.append(filepath)
            continue
        if xy == "!!":
            continue
        if xy in _PORCELAIN_CONFLICT_CODES:
            has_conflicts = True

        staged_type = _PORCELAIN_STAGED_MAP.get(xy[0])
        unstaged_type = _PORCELAIN_UNSTAGED_MAP.get(xy[1])
        is_partial = bool(staged_type and unstaged_type)

        if staged_type:
            fc_staged = FileChange(
                path=filepath,
                change_type=staged_type,
                old_path=orig_path if staged_type == "renamed" else None,
                is_partially_staged=is_partial,
            )
            staged.append(fc_staged)
            if is_partial:
                partially_staged.append(fc_staged)

        if unstaged_type:
            unstaged.append(
                FileChange(
                    path=filepath,
                    change_type=unstaged_type,
                    old_path=orig_path if unstaged_type == "renamed" else None,
                    is_partially_staged=is_partial,
                )
            )

    return has_conflicts, staged, unstaged, untracked, partially_staged


# pygit2 status flags for INDEX (staged) changes
_STAGED_FLAGS = {
    pygit2.GIT_STATUS_INDEX_NEW: "added",
    pygit2.GIT_STATUS_INDEX_MODIFIED: "modified",
    pygit2.GIT_STATUS_INDEX_DELETED: "deleted",
    pygit2.GIT_STATUS_INDEX_RENAMED: "renamed",
}

# pygit2 status flags for WORKTREE (unstaged) changes
_UNSTAGED_FLAGS = {
    pygit2.GIT_STATUS_WT_MODIFIED: "modified",
    pygit2.GIT_STATUS_WT_DELETED: "deleted",
    pygit2.GIT_STATUS_WT_RENAMED: "renamed",
}

_DELTA_STATUS_MAP = {
    pygit2.GIT_DELTA_ADDED: "added",
    pygit2.GIT_DELTA_DELETED: "deleted",
    pygit2.GIT_DELTA_MODIFIED: "modified",
    pygit2.GIT_DELTA_RENAMED: "renamed",
    pygit2.GIT_DELTA_COPIED: "added",
}


try:
    from pygit2.enums import RepositoryState

    _STATE_MERGE = RepositoryState.MERGE
    _REBASE_STATES = {
        RepositoryState.REBASE,
        RepositoryState.REBASE_INTERACTIVE,
        RepositoryState.REBASE_MERGE,
        RepositoryState.APPLY_MAILBOX_OR_REBASE,
    }
except ImportError:
    _STATE_MERGE = 1
    _REBASE_STATES = {7, 8, 9, 11}


def get_status(repo: RepoHandle) -> RepoStatus:
    """Get the full working-tree and index status of a repo."""
    r = repo.pygit2_repo
    try:
        r.index.read()
    except Exception as e:
        logger.debug("Failed reading index in get_status: %s", e)

    # Determine branch state
    is_detached = r.head_is_detached
    head_is_unborn = r.head_is_unborn
    current_branch: str | None = None
    detached_head_sha: str | None = None

    if head_is_unborn:
        try:
            head_target = r.references["HEAD"].target
            if isinstance(head_target, str) and head_target.startswith("refs/heads/"):
                current_branch = head_target.removeprefix("refs/heads/")
            else:
                current_branch = str(head_target)
        except Exception:
            current_branch = "main"
        is_detached = False
    elif is_detached:
        current_branch = None
        detached_head_sha = str(r.head.target)
    else:
        current_branch = r.head.shorthand

    # Ahead/behind
    ahead = 0
    behind = 0
    if not head_is_unborn and not is_detached and current_branch:
        try:
            branch = r.branches.get(current_branch)
            if branch and branch.upstream:
                ahead, behind = r.ahead_behind(r.head.target, branch.upstream.target)
        except KeyError, pygit2.GitError:
            pass

    # Conflicts
    has_conflicts = False
    try:
        if r.index.conflicts is not None:
            has_conflicts = any(True for _ in r.index.conflicts)
    except Exception as e:
        logger.debug("Failed checking index conflicts: %s", e)

    # Merge / Rebase state from pygit2 repository state
    pygit_state = r.state()
    merge_in_progress = pygit_state == _STATE_MERGE
    rebase_in_progress = pygit_state in _REBASE_STATES

    # File status
    staged: list[FileChange] = []
    unstaged: list[FileChange] = []
    untracked: list[str] = []
    partially_staged: list[FileChange] = []

    sparse_parsed = (
        _git_status_sparse(repo.path) if _is_sparse_checkout_active(r, repo.path) else None
    )
    if sparse_parsed is not None:
        sparse_conflicts, staged, unstaged, untracked, partially_staged = sparse_parsed
        has_conflicts = has_conflicts or sparse_conflicts
    else:
        status_dict = r.status()
        for filepath, flags in status_dict.items():
            if flags & pygit2.GIT_STATUS_WT_NEW:
                untracked.append(filepath)
                continue

            staged_type: str | None = None
            for flag, change_type in _STAGED_FLAGS.items():
                if flags & flag:
                    staged_type = change_type
                    break

            unstaged_type: str | None = None
            for flag, change_type in _UNSTAGED_FLAGS.items():
                if flags & flag:
                    unstaged_type = change_type
                    break

            is_partial = bool(staged_type and unstaged_type)

            if staged_type:
                fc_staged = FileChange(
                    path=filepath,
                    change_type=staged_type,
                    is_partially_staged=is_partial,
                )
                staged.append(fc_staged)
                if is_partial:
                    partially_staged.append(fc_staged)

            if unstaged_type:
                fc_unstaged = FileChange(
                    path=filepath,
                    change_type=unstaged_type,
                    is_partially_staged=is_partial,
                )
                unstaged.append(fc_unstaged)

    head_sha = str(r.head.target) if not head_is_unborn and hasattr(r, "head") and r.head else None

    return RepoStatus(
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
        current_branch=current_branch,
        is_detached=is_detached,
        ahead=ahead,
        behind=behind,
        has_conflicts=has_conflicts,
        detached_head_sha=detached_head_sha,
        head_sha=head_sha,
        merge_in_progress=merge_in_progress,
        rebase_in_progress=rebase_in_progress,
        partially_staged=partially_staged,
    )


_BINARY_DIFF_FLAG = getattr(pygit2, "GIT_DIFF_FLAG_BINARY", 1)


def _patch_to_diff(
    patch: pygit2.Patch,
    target_path: str,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    """Convert a pygit2 Patch into Diff, enforcing optional line/byte caps early."""
    delta = patch.delta
    if delta.is_binary or bool(delta.flags & _BINARY_DIFF_FLAG):
        return Diff(path=target_path, is_binary=True, hunks=[])

    hunks: list[Hunk] = []
    collected_lines = 0
    collected_bytes = 0
    total_lines = 0
    truncated = False

    for i, hunk in enumerate(patch.hunks):
        hunk_lines = hunk.lines
        total_lines += len(hunk_lines)
        if truncated:
            continue

        lines: list[DiffLine] = []
        for line in hunk_lines:
            if (max_lines is not None and collected_lines >= max_lines) or (
                max_bytes is not None and collected_bytes >= max_bytes
            ):
                truncated = True
                break
            content = line.content.rstrip("\n")
            lines.append(
                DiffLine(
                    content=content,
                    origin=line.origin,
                    old_lineno=line.old_lineno if line.old_lineno >= 0 else None,
                    new_lineno=line.new_lineno if line.new_lineno >= 0 else None,
                )
            )
            collected_lines += 1
            collected_bytes += len(content.encode("utf-8", errors="replace"))

        if lines:
            hunks.append(
                Hunk(
                    id=f"hunk-{i}",
                    old_start=hunk.old_start,
                    old_count=hunk.old_lines,
                    new_start=hunk.new_start,
                    new_count=hunk.new_lines,
                    lines=lines,
                )
            )

    if truncated:
        return Diff(
            path=target_path,
            is_binary=False,
            hunks=hunks,
            is_truncated=True,
            total_lines=total_lines,
            truncated_reason=(
                f"Showing first {collected_lines:,} of {total_lines:,} lines "
                "(diff exceeded display cap)"
            ),
        )

    return Diff(
        path=target_path,
        is_binary=False,
        hunks=hunks,
        is_truncated=False,
        total_lines=total_lines,
        truncated_reason=None,
    )


def _parse_git_unified_diff(
    raw_text: str,
    target_path: str,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    """Parse git unified diff output into Diff model, honoring caps and binary markers."""
    hunks: list[Hunk] = []
    collected_lines = 0
    collected_bytes = 0
    total_lines = 0
    truncated = False

    cur_hunk_idx = 0
    cur_old_start = 0
    cur_old_count = 0
    cur_new_start = 0
    cur_new_count = 0
    cur_old_no = 0
    cur_new_no = 0
    old_rem = 0
    new_rem = 0
    cur_lines: list[DiffLine] | None = None

    def _flush_hunk() -> None:
        nonlocal cur_hunk_idx, cur_lines
        if cur_lines:
            hunks.append(
                Hunk(
                    id=f"hunk-{cur_hunk_idx}",
                    old_start=cur_old_start,
                    old_count=cur_old_count,
                    new_start=cur_new_start,
                    new_count=cur_new_count,
                    lines=cur_lines,
                )
            )
        cur_lines = None

    lines = raw_text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]

    for line in lines:
        in_hunk = old_rem > 0 or new_rem > 0
        if not in_hunk:
            if (line.startswith("Binary files ") and line.endswith(" differ")) or (
                line == "GIT binary patch"
            ):
                return Diff(path=target_path, is_binary=True, hunks=[])

            hdr_match = _HUNK_HDR_RE.match(line)
            if hdr_match:
                _flush_hunk()
                cur_old_start = int(hdr_match.group(1))
                cur_old_count = int(hdr_match.group(2)) if hdr_match.group(2) is not None else 1
                cur_new_start = int(hdr_match.group(3))
                cur_new_count = int(hdr_match.group(4)) if hdr_match.group(4) is not None else 1
                cur_old_no = cur_old_start
                cur_new_no = cur_new_start
                old_rem = cur_old_count
                new_rem = cur_new_count
                cur_lines = [] if not truncated else None
                cur_hunk_idx = len(hunks)
            continue

        if line == r"\ No newline at end of file":
            continue

        origin = line[:1]
        content = line[1:]
        if origin == " " and old_rem > 0 and new_rem > 0:
            old_no: int | None = cur_old_no
            new_no: int | None = cur_new_no
            cur_old_no += 1
            cur_new_no += 1
            old_rem -= 1
            new_rem -= 1
        elif origin == "+" and new_rem > 0:
            old_no = None
            new_no = cur_new_no
            cur_new_no += 1
            new_rem -= 1
        elif origin == "-" and old_rem > 0:
            old_no = cur_old_no
            new_no = None
            cur_old_no += 1
            old_rem -= 1
        else:
            continue

        total_lines += 1
        if truncated or cur_lines is None:
            continue

        if (max_lines is not None and collected_lines >= max_lines) or (
            max_bytes is not None and collected_bytes >= max_bytes
        ):
            truncated = True
            _flush_hunk()
            continue

        cur_lines.append(
            DiffLine(
                content=content,
                origin=origin,
                old_lineno=old_no,
                new_lineno=new_no,
            )
        )
        collected_lines += 1
        collected_bytes += len(content.encode("utf-8", errors="replace"))

    _flush_hunk()

    if truncated:
        return Diff(
            path=target_path,
            is_binary=False,
            hunks=hunks,
            is_truncated=True,
            total_lines=total_lines,
            truncated_reason=(
                f"Showing first {collected_lines:,} of {total_lines:,} lines "
                "(diff exceeded display cap)"
            ),
        )

    return Diff(
        path=target_path,
        is_binary=False,
        hunks=hunks,
        is_truncated=False,
        total_lines=total_lines,
        truncated_reason=None,
    )


_MAX_IN_MEMORY_BLOB_BYTES = 16 * 1024 * 1024
_REGULAR_BLOB_MODES = frozenset(
    {
        pygit2.GIT_FILEMODE_BLOB,
        pygit2.GIT_FILEMODE_BLOB_EXECUTABLE,
    }
)


class _FallbackDiffNeeded(Exception):
    """Internal control-flow signal when a single-file diff must delegate to git CLI."""


def _validate_repo_rel_path(repo_path: Path, rel_path: str) -> Path | None:
    """Validate repo-relative path against traversal or symlink-parent escape (SEC-1/SEC-2)."""
    if not isinstance(rel_path, str) or not rel_path:
        return None
    if "\0" in rel_path or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel_path):
        return None

    norm = rel_path.replace("\\", "/")
    if norm.startswith("/") or Path(rel_path).is_absolute():
        return None

    parts = norm.split("/")
    if any(seg in ("", ".", "..") for seg in parts):
        return None

    try:
        repo_root = repo_path.resolve()
        candidate = repo_root / Path(*parts)
        if not candidate.parent.resolve().is_relative_to(repo_root):
            return None
    except OSError:
        return None
    return candidate


def _repo_uses_diff_filters(r: pygit2.Repository, repo_path: Path) -> bool:
    if (repo_path / ".gitattributes").is_file():
        return True
    try:
        if (resolve_git_dir(repo_path) / "info" / "attributes").is_file():
            return True
    except Exception as exc:
        logger.debug("Skipping gitattributes check for '%s': %s", repo_path, exc)
    try:
        autocrlf = str(r.config["core.autocrlf"]).strip().lower()
        if autocrlf in ("true", "input"):
            return True
    except (KeyError, pygit2.GitError):
        return False
    return False


def _is_filemode_enabled(r: pygit2.Repository) -> bool:
    try:
        return bool(r.config.get_bool("core.filemode"))
    except (KeyError, pygit2.GitError, ValueError):
        return True


def _lookup_tree_entry(
    r: pygit2.Repository,
    root_tree: pygit2.Tree,
    rel_path: str,
):
    cur = root_tree
    parts = rel_path.split("/")
    for idx, seg in enumerate(parts):
        if seg not in cur:
            return None
        entry = cur[seg]
        if idx < len(parts) - 1:
            if entry.type != pygit2.GIT_OBJECT_TREE:
                return None
            if not r.odb.exists(entry.id):
                raise _FallbackDiffNeeded()
            obj = r[entry.id]
            if not isinstance(obj, pygit2.Tree):
                return None
            cur = obj
        else:
            return entry
    return None


def _lookup_index_entry(r: pygit2.Repository, rel_path: str):
    try:
        conflicts = r.index.conflicts
        if conflicts is not None and rel_path in conflicts:
            raise _FallbackDiffNeeded()
    except _FallbackDiffNeeded:
        raise
    except (KeyError, ValueError, pygit2.GitError):
        pass

    try:
        if rel_path in r.index:
            return r.index[rel_path]
    except (KeyError, ValueError, pygit2.GitError) as exc:
        logger.debug("Index entry lookup fallback for '%s': %s", rel_path, exc)
        raise _FallbackDiffNeeded() from exc
    return None


def _run_git_diff_fallback(
    repo_path: Path,
    args: list[str],
    target_path: str,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
    allow_diff_exit: bool = False,
) -> Diff:
    """Fallback diff via git CLI (shell=False) when partial-clone objects are missing locally."""
    try:
        res = subprocess.run(
            ["git", "--no-optional-locks", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_read_env(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git diff fallback failed for '%s': %s", target_path, exc)
        return Diff(path=target_path, is_binary=False, hunks=[])

    ok_codes = (0, 1) if allow_diff_exit else (0,)
    if res.returncode not in ok_codes or not res.stdout:
        return Diff(path=target_path, is_binary=False, hunks=[])

    return _parse_git_unified_diff(
        res.stdout,
        target_path,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def _git_commit_file_stats_fallback(repo_path: Path, sha: str) -> list[FileStat]:
    """Fallback commit file list via git diff-tree --name-status for treeless clones."""
    try:
        res = subprocess.run(
            ["git", "diff-tree", "-z", "--no-commit-id", "--name-status", "-r", "--root", sha],
            cwd=repo_path,
            capture_output=True,
            text=False,
            env=_git_read_env(),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git diff-tree stats fallback failed for %s: %s", sha[:8], exc)
        return []

    if res.returncode != 0 or not res.stdout:
        return []

    tokens = res.stdout.split(b"\x00")
    stats: list[FileStat] = []
    i = 0
    while i < len(tokens):
        code_raw = tokens[i]
        i += 1
        if not code_raw:
            continue
        code = code_raw.decode("ascii", errors="replace")
        letter = code[:1]
        change_type = _GIT_NAME_STATUS_MAP.get(letter, "modified")
        if letter in ("R", "C"):
            if i + 1 >= len(tokens):
                break
            _old_p = tokens[i]
            new_p = tokens[i + 1].decode("utf-8", errors="replace")
            i += 2
            file_path = new_p
        else:
            if i >= len(tokens):
                break
            file_path = tokens[i].decode("utf-8", errors="replace")
            i += 1
        stats.append(
            FileStat(
                path=file_path,
                change_type=change_type,
                additions=0,
                deletions=0,
            )
        )
    return stats


def get_diff(
    repo: RepoHandle,
    path: str,
    *,
    staged: bool,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    """Get the diff for a single file in working tree / index in O(1) without repo-wide scan."""
    target_file = _validate_repo_rel_path(repo.path, path)
    if target_file is None:
        return Diff(path=path, is_binary=False, hunks=[])

    r = repo.pygit2_repo
    try:
        r.index.read()
    except Exception as e:
        logger.debug("Failed reading index in get_diff: %s", e)

    try:
        if _repo_uses_diff_filters(r, repo.path):
            raise _FallbackDiffNeeded()

        if staged:
            if r.head_is_unborn:
                head_entry = None
            else:
                head_tree = r.head.peel(pygit2.Tree)
                head_entry = _lookup_tree_entry(r, head_tree, path)

            index_entry = _lookup_index_entry(r, path)
            if head_entry is None and index_entry is None:
                return Diff(path=path, is_binary=False, hunks=[])
            if (
                head_entry is not None
                and index_entry is not None
                and head_entry.id == index_entry.id
                and head_entry.filemode == index_entry.mode
            ):
                return Diff(path=path, is_binary=False, hunks=[])

            if head_entry is not None and head_entry.filemode not in _REGULAR_BLOB_MODES:
                raise _FallbackDiffNeeded()
            if index_entry is not None and index_entry.mode not in _REGULAR_BLOB_MODES:
                raise _FallbackDiffNeeded()
            if (
                head_entry is not None
                and index_entry is not None
                and head_entry.filemode != index_entry.mode
            ):
                raise _FallbackDiffNeeded()

            old_blob = None
            if head_entry is not None:
                if not r.odb.exists(head_entry.id):
                    raise _FallbackDiffNeeded()
                obj = r[head_entry.id]
                if not isinstance(obj, pygit2.Blob) or obj.size > _MAX_IN_MEMORY_BLOB_BYTES:
                    raise _FallbackDiffNeeded()
                old_blob = obj

            new_blob = None
            if index_entry is not None:
                if not r.odb.exists(index_entry.id):
                    raise _FallbackDiffNeeded()
                obj = r[index_entry.id]
                if not isinstance(obj, pygit2.Blob) or obj.size > _MAX_IN_MEMORY_BLOB_BYTES:
                    raise _FallbackDiffNeeded()
                new_blob = obj

            patch = pygit2.Patch.create_from(
                old_blob,
                new_blob,
                old_as_path=path,
                new_as_path=path,
            )
            return _patch_to_diff(patch, path, max_lines=max_lines, max_bytes=max_bytes)

        # Unstaged diff (index vs workdir) for a single validated path
        if _is_sparse_checkout_active(r, repo.path):
            raise _FallbackDiffNeeded()

        index_entry = _lookup_index_entry(r, path)
        try:
            st = os.lstat(target_file)
        except FileNotFoundError:
            st = None
        except OSError as exc:
            raise _FallbackDiffNeeded() from exc

        if index_entry is None and st is None:
            return Diff(path=path, is_binary=False, hunks=[])

        if st is not None:
            if stat.S_ISLNK(st.st_mode):
                if index_entry is not None:
                    raise _FallbackDiffNeeded()
                link_bytes = os.readlink(target_file).encode("utf-8", errors="replace")
                if len(link_bytes) > _MAX_IN_MEMORY_BLOB_BYTES:
                    raise _FallbackDiffNeeded()
                patch = pygit2.Patch.create_from(
                    None,
                    link_bytes,
                    old_as_path=path,
                    new_as_path=path,
                )
                return _patch_to_diff(patch, path, max_lines=max_lines, max_bytes=max_bytes)

            if stat.S_ISDIR(st.st_mode):
                if index_entry is not None and index_entry.mode == pygit2.GIT_FILEMODE_COMMIT:
                    raise _FallbackDiffNeeded()
                return Diff(path=path, is_binary=False, hunks=[])

            if not stat.S_ISREG(st.st_mode):
                raise _FallbackDiffNeeded()

            repo_root = repo.path.resolve()
            if not target_file.resolve().is_relative_to(repo_root):
                return Diff(path=path, is_binary=False, hunks=[])

            if index_entry is None:
                if st.st_size > _MAX_IN_MEMORY_BLOB_BYTES:
                    return _run_git_diff_fallback(
                        repo.path,
                        ["diff", "--no-color", "--no-index", "--", "/dev/null", path],
                        path,
                        max_lines=max_lines,
                        max_bytes=max_bytes,
                        allow_diff_exit=True,
                    )
                work_bytes = target_file.read_bytes()
                patch = pygit2.Patch.create_from(
                    None,
                    work_bytes,
                    old_as_path=path,
                    new_as_path=path,
                )
                return _patch_to_diff(patch, path, max_lines=max_lines, max_bytes=max_bytes)

            # Tracked regular file in workdir
            if index_entry.mode not in _REGULAR_BLOB_MODES:
                raise _FallbackDiffNeeded()
            if _is_filemode_enabled(r):
                if (index_entry.mode == pygit2.GIT_FILEMODE_BLOB_EXECUTABLE) != bool(
                    st.st_mode & 0o111
                ):
                    raise _FallbackDiffNeeded()
            if st.st_size > _MAX_IN_MEMORY_BLOB_BYTES or not r.odb.exists(index_entry.id):
                raise _FallbackDiffNeeded()
            old_obj = r[index_entry.id]
            if not isinstance(old_obj, pygit2.Blob) or old_obj.size > _MAX_IN_MEMORY_BLOB_BYTES:
                raise _FallbackDiffNeeded()
            work_bytes = target_file.read_bytes()
            if old_obj.data == work_bytes:
                return Diff(path=path, is_binary=False, hunks=[])
            patch = pygit2.Patch.create_from(
                old_obj,
                work_bytes,
                old_as_path=path,
                new_as_path=path,
            )
            return _patch_to_diff(patch, path, max_lines=max_lines, max_bytes=max_bytes)

        # Tracked file deleted in working tree (st is None, index_entry is not None)
        if index_entry.mode not in _REGULAR_BLOB_MODES or not r.odb.exists(index_entry.id):
            raise _FallbackDiffNeeded()
        old_obj = r[index_entry.id]
        if not isinstance(old_obj, pygit2.Blob) or old_obj.size > _MAX_IN_MEMORY_BLOB_BYTES:
            raise _FallbackDiffNeeded()
        patch = pygit2.Patch.create_from(
            old_obj,
            None,
            old_as_path=path,
            new_as_path=path,
        )
        return _patch_to_diff(patch, path, max_lines=max_lines, max_bytes=max_bytes)
    except (_FallbackDiffNeeded, KeyError, pygit2.GitError, OSError) as exc:
        logger.debug("Single-file get_diff CLI fallback for '%s': %s", path, exc)
        git_args = (
            ["diff", "--no-color", "--cached", "--", path]
            if staged
            else ["diff", "--no-color", "--", path]
        )
        return _run_git_diff_fallback(
            repo.path,
            git_args,
            path,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )


def get_commit_diff(
    repo: RepoHandle,
    sha: str,
    path: str | None = None,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    """Get diff of a historical commit against its first parent (or empty tree for root)."""
    r = repo.pygit2_repo
    try:
        commit = r.get(sha)
        if not commit or not isinstance(commit, pygit2.Commit):
            return Diff(path=path or "", is_binary=False, hunks=[])

        if commit.parents:
            parent_tree = commit.parents[0].tree
        else:
            empty_tree_id = r.TreeBuilder().write()
            parent_tree = r[empty_tree_id]

        diff = r.diff(parent_tree, commit.tree)

        for idx, delta in enumerate(diff.deltas):
            target_path = delta.new_file.path or delta.old_file.path
            if path is not None and target_path != path:
                continue

            return _patch_to_diff(
                diff[idx],
                target_path,
                max_lines=max_lines,
                max_bytes=max_bytes,
            )

        return Diff(path=path or "", is_binary=False, hunks=[])
    except (KeyError, pygit2.GitError) as exc:
        logger.debug("pygit2 get_commit_diff fallback for %s (%s): %s", sha[:8], path, exc)
        git_args = ["diff-tree", "-p", "--no-commit-id", "--root", sha]
        if path:
            git_args.extend(["--", path])
        return _run_git_diff_fallback(
            repo.path,
            git_args,
            path or "",
            max_lines=max_lines,
            max_bytes=max_bytes,
        )


def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]:
    """Get list of changed files with +additions / -deletions for a commit."""
    r = repo.pygit2_repo
    commit = r.get(sha)
    if not commit or not isinstance(commit, pygit2.Commit):
        return []

    diff = None
    try:
        if commit.parents:
            parent_tree = commit.parents[0].tree
        else:
            empty_tree_id = r.TreeBuilder().write()
            parent_tree = r[empty_tree_id]

        diff = r.diff(parent_tree, commit.tree)
        stats: list[FileStat] = []

        for patch in diff:
            delta = patch.delta
            file_path = delta.new_file.path or delta.old_file.path
            change_type = _DELTA_STATUS_MAP.get(delta.status, "modified")
            additions = patch.line_stats[1]
            deletions = patch.line_stats[2]
            stats.append(
                FileStat(
                    path=file_path,
                    change_type=change_type,
                    additions=additions,
                    deletions=deletions,
                )
            )

        return stats
    except (KeyError, pygit2.GitError) as exc:
        logger.debug(
            "pygit2 get_commit_file_stats fallback for %s (partial clone): %s", sha[:8], exc
        )
        if diff is not None:
            return [
                FileStat(
                    path=delta.new_file.path or delta.old_file.path,
                    change_type=_DELTA_STATUS_MAP.get(delta.status, "modified"),
                    additions=0,
                    deletions=0,
                )
                for delta in diff.deltas
            ]
        return _git_commit_file_stats_fallback(repo.path, sha)


def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]:
    """Map commit SHA to list of RefLabel badges (branches, tags, HEAD)."""
    r = repo.pygit2_repo
    labels: dict[str, list[RefLabel]] = {}

    def add_label(commit_sha: str, label: RefLabel) -> None:
        labels.setdefault(commit_sha, []).append(label)

    # 1. Local branches
    for branch_name in r.branches.local:
        branch = r.branches.local[branch_name]
        try:
            target_commit = branch.peel(pygit2.Commit)
            add_label(str(target_commit.id), RefLabel(name=branch_name, kind="branch"))
        except Exception as e:
            logger.debug("Failed resolving branch commit for label: %s", e)

    # 2. Tags
    for ref_name in r.references:
        if ref_name.startswith("refs/tags/"):
            tag_name = ref_name.removeprefix("refs/tags/")
            ref = r.references[ref_name]
            try:
                target_oid = ref.target
                obj = r.get(target_oid) if isinstance(target_oid, pygit2.Oid) else None
                if obj is None and isinstance(target_oid, str):
                    resolved = ref.resolve()
                    obj = r.get(resolved.target)
                depth = 0
                while isinstance(obj, pygit2.Tag) and depth < 16:
                    obj = r.get(obj.target)
                    depth += 1
                if isinstance(obj, pygit2.Commit):
                    add_label(str(obj.id), RefLabel(name=tag_name, kind="tag"))
            except (KeyError, pygit2.GitError, ValueError) as e:
                logger.debug("Failed resolving tag commit for label: %s", e)

    # 3. HEAD
    if not r.head_is_unborn:
        try:
            head_target = r.head.target
            if r.head_is_detached:
                add_label(str(head_target), RefLabel(name="HEAD", kind="head"))
            else:
                add_label(str(head_target), RefLabel(name="HEAD", kind="head"))
        except Exception as e:
            logger.debug("Failed resolving HEAD target for label: %s", e)

    return labels


def iter_commits(repo: RepoHandle, *, all_refs: bool = False) -> Iterator[Commit]:
    """Yield commits in topological/time order.

    When all_refs=True, seeds from local branches and HEAD for fast, deterministic DAG traversal.
    """
    r = repo.pygit2_repo
    if r.head_is_unborn:
        return

    walker = r.walk(r.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME)

    if all_refs:
        # Push HEAD first
        pushed_oids: set[pygit2.Oid] = {r.head.target}
        # Push all local branches
        for branch_name in r.branches.local:
            try:
                b = r.branches.local[branch_name]
                target = b.peel(pygit2.Commit).id
                if target not in pushed_oids:
                    walker.push(target)
                    pushed_oids.add(target)
            except Exception as e:
                logger.debug("Failed peeling branch commit in walker: %s", e)

    for git_commit in walker:
        author_date = datetime.fromtimestamp(
            git_commit.author.time,
            tz=timezone.utc,
        ).isoformat()

        yield Commit(
            sha=str(git_commit.id),
            message=git_commit.message.strip(),
            author_name=git_commit.author.name,
            author_email=git_commit.author.email,
            author_date=author_date,
            parent_shas=[str(p) for p in git_commit.parent_ids],
        )


def _commit_touches_path(r: pygit2.Repository, commit_sha: str, path: str) -> bool:
    """Check if a commit modified the given path against its first parent."""
    try:
        commit = r.get(commit_sha)
        if not commit or not isinstance(commit, pygit2.Commit):
            return False
        if commit.parents:
            parent_tree = commit.parents[0].tree
        else:
            empty_tree_id = r.TreeBuilder().write()
            parent_tree = r[empty_tree_id]

        diff = r.diff(parent_tree, commit.tree)
        for delta in diff.deltas:
            if delta.new_file.path == path or delta.old_file.path == path:
                return True
            # Also check directory prefix match
            if delta.new_file.path.startswith(
                path.rstrip("/") + "/"
            ) or delta.old_file.path.startswith(path.rstrip("/") + "/"):
                return True
    except Exception as e:
        logger.debug("Failed checking commit path touch: %s", e)
    return False


_WALKER_CACHE_MAXSIZE = 8
_WALKER_CACHE_LOCK = threading.Lock()
# Keyed by (repo_path, repo_obj_id, repo_generation, head_sha, all_refs, filter_key)
# Value is (walker, buffered_next_commit, expected_cursor_sha, refs_digest)
_ACTIVE_WALKER_CACHE: OrderedDict[tuple[object, ...], tuple[object, Commit | None, str, str]] = (
    OrderedDict()
)


def _commit_from_pygit2(git_commit: pygit2.Commit) -> Commit:
    author_date = datetime.fromtimestamp(
        git_commit.author.time,
        tz=timezone.utc,
    ).isoformat()
    return Commit(
        sha=str(git_commit.id),
        message=git_commit.message.strip(),
        author_name=git_commit.author.name,
        author_email=git_commit.author.email,
        author_date=author_date,
        parent_shas=[str(p) for p in git_commit.parent_ids],
    )


def _matches_log_filter(
    r: pygit2.Repository,
    commit: Commit,
    log_filter: LogFilter | None,
) -> bool:
    if not log_filter:
        return True
    if log_filter.author:
        author_lower = log_filter.author.lower()
        if (
            author_lower not in commit.author_name.lower()
            and author_lower not in commit.author_email.lower()
        ):
            return False
    if log_filter.message_substring:
        if log_filter.message_substring.lower() not in commit.message.lower():
            return False
    if log_filter.date_from and commit.author_date < log_filter.date_from:
        return False
    if log_filter.date_to and commit.author_date > log_filter.date_to:
        return False
    if log_filter.path and not _commit_touches_path(r, commit.sha, log_filter.path):
        return False
    return True


def _repo_refs_digest(r: pygit2.Repository, all_refs: bool) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(str(r.head.target).encode("utf-8"))
    if all_refs:
        for branch_name in sorted(r.branches.local):
            try:
                tip = r.branches.local[branch_name].peel(pygit2.Commit).id
                h.update(f"{branch_name}:{tip};".encode("utf-8"))
            except (KeyError, pygit2.GitError) as exc:
                logger.debug("Skipping branch '%s' in refs digest: %s", branch_name, exc)
    return h.hexdigest()


def _create_walker(r: pygit2.Repository, *, all_refs: bool):
    walker = r.walk(r.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME)
    if all_refs:
        pushed_oids: set[pygit2.Oid] = {r.head.target}
        for branch_name in r.branches.local:
            try:
                b = r.branches.local[branch_name]
                target = b.peel(pygit2.Commit).id
                if target not in pushed_oids:
                    walker.push(target)
                    pushed_oids.add(target)
            except (KeyError, pygit2.GitError) as exc:
                logger.debug("Failed peeling branch commit in walker: %s", exc)
    return walker


def get_log_page(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 500,
    cursor_sha: str | None = None,
    all_refs: bool = False,
) -> LogPage:
    """Fetch a bounded page of commits without loading full repository history."""
    if limit <= 0:
        return LogPage(commits=(), next_cursor_sha=None, has_more=False, scanned_count=0)

    r = repo.pygit2_repo
    if r.head_is_unborn:
        return LogPage(commits=(), next_cursor_sha=None, has_more=False, scanned_count=0)

    head_sha = str(r.head.target)
    refs_digest = _repo_refs_digest(r, all_refs)
    filter_key = (
        filter.author if filter else None,
        filter.message_substring if filter else None,
        filter.date_from if filter else None,
        filter.date_to if filter else None,
        filter.path if filter else None,
    )
    cache_key = (
        str(repo.path),
        id(r),
        getattr(repo, "_generation", 0),
        head_sha,
        bool(all_refs),
        filter_key,
    )

    walker = None
    buffered_commit: Commit | None = None
    scanned_count = 0

    if cursor_sha is not None:
        with _WALKER_CACHE_LOCK:
            cached = _ACTIVE_WALKER_CACHE.get(cache_key)
            if cached is not None:
                c_walker, c_buf, c_cursor, c_digest = cached
                if c_cursor == cursor_sha and c_digest == refs_digest:
                    _ACTIVE_WALKER_CACHE.pop(cache_key, None)
                    walker = c_walker
                    buffered_commit = c_buf
                else:
                    _ACTIVE_WALKER_CACHE.pop(cache_key, None)

        if walker is None:
            walker = _create_walker(r, all_refs=all_refs)
            seen_cursor = False
            for raw_commit in walker:
                scanned_count += 1
                if str(raw_commit.id) == cursor_sha:
                    seen_cursor = True
                    break
            if not seen_cursor:
                return LogPage(
                    commits=(),
                    next_cursor_sha=None,
                    has_more=False,
                    scanned_count=scanned_count,
                )
    else:
        walker = _create_walker(r, all_refs=all_refs)

    collected: list[Commit] = []
    peek_commit: Commit | None = None

    if buffered_commit is not None:
        if _matches_log_filter(r, buffered_commit, filter):
            collected.append(buffered_commit)

    if len(collected) <= limit:
        for raw_commit in walker:
            scanned_count += 1
            commit = _commit_from_pygit2(raw_commit)
            if not _matches_log_filter(r, commit, filter):
                continue
            if len(collected) < limit:
                collected.append(commit)
            else:
                peek_commit = commit
                break

    has_more = peek_commit is not None
    next_cursor_sha = collected[-1].sha if has_more and collected else None

    if has_more and next_cursor_sha is not None:
        with _WALKER_CACHE_LOCK:
            _ACTIVE_WALKER_CACHE[cache_key] = (walker, peek_commit, next_cursor_sha, refs_digest)
            _ACTIVE_WALKER_CACHE.move_to_end(cache_key)
            while len(_ACTIVE_WALKER_CACHE) > _WALKER_CACHE_MAXSIZE:
                _ACTIVE_WALKER_CACHE.popitem(last=False)

    return LogPage(
        commits=tuple(collected),
        next_cursor_sha=next_cursor_sha,
        has_more=has_more,
        scanned_count=scanned_count,
    )


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
    all_refs: bool = False,
) -> list[Commit]:
    """Walk the commit log, paginated with optional filtering."""
    r = repo.pygit2_repo
    if r.head_is_unborn:
        return []

    commits: list[Commit] = []
    skipped = 0

    for c in iter_commits(repo, all_refs=all_refs):
        if filter:
            if filter.author:
                author_lower = filter.author.lower()
                if (
                    author_lower not in c.author_name.lower()
                    and author_lower not in c.author_email.lower()
                ):
                    continue
            if (
                filter.message_substring
                and filter.message_substring.lower() not in c.message.lower()
            ):
                continue
            if filter.date_from and c.author_date < filter.date_from:
                continue
            if filter.date_to and c.author_date > filter.date_to:
                continue
            if filter.path and not _commit_touches_path(r, c.sha, filter.path):
                continue

        if skipped < offset:
            skipped += 1
            continue

        commits.append(c)
        if len(commits) >= limit:
            break

    return commits


def blame_file(repo: RepoHandle, path: str) -> list[BlameLine]:
    """Get per-line blame for a file."""
    r = repo.pygit2_repo

    blame_result = r.blame(path)
    lines: list[BlameLine] = []

    try:
        head_commit = r.head.peel(pygit2.Commit)
        tree = head_commit.tree
        blob = tree[path]
        file_content = r[blob.id].data.decode("utf-8", errors="replace")
        file_lines = file_content.splitlines()
    except KeyError, pygit2.GitError:
        file_lines = []

    for hunk in blame_result:
        for line_offset in range(hunk.lines_in_hunk):
            line_no = hunk.final_start_line_number + line_offset
            line_content = ""
            if 0 < line_no <= len(file_lines):
                line_content = file_lines[line_no - 1]

            lines.append(
                BlameLine(
                    line_no=line_no,
                    commit_sha=str(hunk.final_commit_id),
                    author=hunk.final_committer.name,
                    line_content=line_content,
                )
            )

    return lines


def get_repo_refs_signature(
    repo: RepoHandle,
) -> tuple[str, bool, bool, str, str, str] | None:
    """Return a deterministic signature of HEAD + all repository refs via fresh pygit2 read.

    Returns ``(repo_path, head_is_unborn, head_is_detached, head_name, head_target, refs_digest)``
    or ``None`` if the repository state cannot be inspected cleanly.
    """
    r: pygit2.Repository | None = None
    try:
        r = pygit2.Repository(str(repo.path))
    except KeyError, pygit2.GitError, OSError, TypeError:
        candidate = getattr(repo, "pygit2_repo", None)
        if candidate is not None and isinstance(getattr(candidate, "head_is_unborn", None), bool):
            r = candidate
        else:
            return None

    try:
        unborn = bool(r.head_is_unborn)
        detached = bool(r.head_is_detached)
        if unborn:
            head_name = ""
            head_target = ""
        else:
            head_ref = r.head
            head_name = str(getattr(head_ref, "name", "") or "")
            head_target = str(getattr(head_ref, "target", "") or "")

        h = hashlib.blake2b(digest_size=16)
        symbolic_enum = getattr(getattr(pygit2, "enums", None), "ReferenceType", None)
        symbolic_type = getattr(symbolic_enum, "SYMBOLIC", getattr(pygit2, "GIT_REF_SYMBOLIC", 2))
        refs = getattr(r, "references", ())
        for ref_name in sorted(refs):
            try:
                ref = refs[ref_name]
                raw_target = str(getattr(ref, "target", "") or "")
                resolved_target = raw_target
                if getattr(ref, "type", None) == symbolic_type:
                    try:
                        resolved_target = str(ref.resolve().target)
                    except KeyError, pygit2.GitError:
                        resolved_target = ""
                h.update(f"{ref_name}={raw_target}->{resolved_target};".encode())
            except KeyError, pygit2.GitError, OSError:
                h.update(f"{ref_name}=<unreadable>;".encode())
        return (str(repo.path), unborn, detached, head_name, head_target, h.hexdigest())
    except (KeyError, pygit2.GitError, OSError, AttributeError) as exc:
        logger.debug(
            "Unable to compute refs signature for '%s': %s", getattr(repo, "path", "?"), exc
        )
        return None
