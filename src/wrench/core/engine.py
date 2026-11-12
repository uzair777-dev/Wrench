import logging
import os
import re
import sqlite3
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pygit2

from .exceptions import (
    BinaryFileStagingError,
    GitCommandError,
    PatchApplyError,
    RemoteExistsError,
    RemoteNotFoundError,
    StaleLockDetectedError,  # noqa: F401
    WrenchGitError,
    WrenchRepoNotFoundError,
)
from .models import (
    BundleInfo,
    CommitGraphStats,
    LfsFileStatus,
    LFSLock,
    LogPage,
    RebaseTodoEntry,
    SparseCheckoutState,
    TreeDirectoryEntry,
    WatcherStatusInfo,  # noqa: F401
)

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    path: str
    change_type: str  # 'added' | 'modified' | 'deleted' | 'renamed'
    old_path: str | None = None
    is_partially_staged: bool = False

    @property
    def status_code(self) -> str:
        codes = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R"}
        return codes.get(self.change_type, "M")


@dataclass(frozen=True)
class FileStatusInfo:
    """Rich status descriptor for a repository path."""

    path: str
    staged_code: str  # e.g., "M", "A", "D", "R", " "
    unstaged_code: str  # e.g., "M", "D", "?", " "
    is_partially_staged: bool  # True if both staged_code.strip() and unstaged_code.strip()
    is_untracked: bool = False
    staged_hunks_count: int = 0
    unstaged_hunks_count: int = 0

    @property
    def composite_badge(self) -> str:
        """Returns visual status symbol (e.g., 'MM', 'AM', 'M', 'M', '??')."""
        s = self.staged_code.strip() or " "
        u = self.unstaged_code.strip() or " "
        return f"{s}{u}".strip() if self.is_partially_staged else (s if s != " " else u)


@dataclass
class RepoStatus:
    staged: list[FileChange]
    unstaged: list[FileChange]
    untracked: list[str]
    current_branch: str | None
    is_detached: bool
    ahead: int
    behind: int
    has_conflicts: bool
    detached_head_sha: str | None = None
    head_sha: str | None = None
    merge_in_progress: bool = False
    rebase_in_progress: bool = False
    partially_staged: list[FileChange] = field(default_factory=list)

    @property
    def branch_name(self) -> str | None:
        return self.current_branch

    @property
    def is_detached_head(self) -> bool:
        return self.is_detached

    @property
    def partially_staged_paths(self) -> set[str]:
        return {f.path for f in self.partially_staged}


@dataclass
class FileStat:
    """Per-file change stats for a commit (+N/-M)."""

    path: str
    change_type: str  # 'added' | 'modified' | 'deleted' | 'renamed'
    additions: int
    deletions: int


@dataclass
class RefLabel:
    """A badge rendered on the commit graph (branch, tag, or head)."""

    name: str  # 'main', 'feature/x', 'v1.0.0', 'HEAD'
    kind: str  # 'branch' | 'tag' | 'head'


@dataclass
class Commit:
    sha: str
    message: str
    author_name: str
    author_email: str
    author_date: str  # ISO 8601
    parent_shas: list[str]

    @property
    def author(self) -> str:
        return self.author_name


@dataclass
class BlameLine:
    line_no: int
    commit_sha: str
    author: str
    line_content: str


@dataclass
class DiffLine:
    content: str
    origin: str  # '+' | '-' | ' '
    old_lineno: int | None
    new_lineno: int | None


@dataclass
class Hunk:
    id: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine]


@dataclass
class Diff:
    path: str
    is_binary: bool
    hunks: list[Hunk]
    is_truncated: bool = False
    total_lines: int = 0
    truncated_reason: str | None = None


@dataclass
class MergeResult:
    status: str  # 'up_to_date' | 'merged' | 'conflict'
    commit_sha: str | None = None
    conflicted_files: list[str] = field(default_factory=list)


@dataclass
class RebaseResult:
    status: str  # 'complete' | 'conflict' | 'aborted'
    conflicted_files: list[str] = field(default_factory=list)


@dataclass
class Remote:
    name: str
    url: str


@dataclass
class ReflogEntry:
    sha: str
    message: str
    timestamp: str  # ISO 8601


@dataclass
class Submodule:
    path: str
    url: str
    initialized: bool


@dataclass
class SubmoduleStatus:
    path: str
    current_commit: str
    is_dirty: bool


@dataclass
class LogFilter:
    author: str | None = None
    message_substring: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    path: str | None = None


@dataclass
class CloneResult:
    """Phase 3 addition. Returned by clone_repo on success."""

    path: Path


@dataclass
class RemoteInfo:
    """Phase 3 addition. Represents a configured git remote."""

    name: str
    url: str
    last_fetch_at: str | None = None
    is_reachable: bool | None = None

    @property
    def fetch_url(self) -> str:
        return self.url


class RepoHandle:
    """Wraps a pygit2.Repository for reads and Path for subprocess."""

    def __init__(
        self,
        pygit2_repo: pygit2.Repository | str | Path,
        path: Path | str | None = None,
    ):
        if isinstance(pygit2_repo, (str, Path)):
            p = Path(pygit2_repo)
            self.pygit2_repo = pygit2.Repository(str(p))
            self.path = p
        else:
            self.pygit2_repo = pygit2_repo
            self.path = Path(path) if path is not None else Path(pygit2_repo.path).parent
        self._generation: int = 0

    def reload(self) -> None:
        """Reopen pygit2.Repository so external config/ref/sparse changes take effect."""
        try:
            new_repo = pygit2.Repository(str(self.path))
        except pygit2.GitError as exc:
            raise WrenchRepoNotFoundError(str(exc)) from exc
        self._generation += 1
        self.pygit2_repo = new_repo


# Import read_ops, write_ops, identity, reflog after all dataclasses are defined
from . import identity, read_ops, rebase_sequencer, reflog, sparse_checkout, write_ops  # noqa: E402
from .bundles import (  # noqa: E402
    create_bundle,
    get_bundle_info,
    unbundle,
    verify_bundle,
)
from .discovery import discover_repos  # noqa: E402, F401
from .lfs_ops import (  # noqa: E402
    is_lfs_installed,
    is_lfs_pointer,
    lfs_available,
    lfs_files,
    lfs_lock,
    lfs_locks,
    lfs_pull,
    lfs_push,
    lfs_status,
    lfs_track,
    lfs_unlock,
    lfs_untrack,
    parse_lfs_pointer,
)
from .paths import resolve_git_dir  # noqa: E402, F401
from .read_ops import iter_commits as _read_iter_commits  # noqa: E402
from .reflog_ops import (  # noqa: E402
    create_branch_from_reflog,
    list_reflog,
    reset_to_reflog_entry,
)
from .security_sanitizer import (  # noqa: E402, F401
    redact_secrets,
    validate_clone_url,
    validate_git_ref,
)
from .submodules import (  # noqa: E402
    add_submodule,
    init_submodule,
    list_submodules,
    submodule_status,
    sync_submodules,
    update_submodules,
)


def init_repo(path: Path | str) -> RepoHandle:
    p = Path(path)
    write_ops.init_repo(p)
    return open_repo(p)


def clone_repo(
    url: str,
    dest: Path | str,
    *,
    progress_cb=None,
    cancel_event=None,
    branch: str | None = None,
    recursive: bool = False,
    filter_spec: str | None = None,
    sparse: bool = False,
) -> CloneResult:
    return write_ops.clone_repo(
        url,
        dest,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        branch=branch,
        recursive=recursive,
        filter_spec=filter_spec,
        sparse=sparse,
    )


clone = clone_repo
clone_repository = clone_repo


def open_repo(path: Path | str, *, configure_credentials: bool = True) -> RepoHandle:
    read_ops.configure_libgit2_cache_limits()
    p = Path(path)
    if not p.exists():
        raise WrenchRepoNotFoundError(f"Path does not exist: {p}")
    git_dir = p / ".git"
    if not git_dir.exists() and not (p / "HEAD").exists():
        raise WrenchRepoNotFoundError(f"Not a git repository: {p}")
    try:
        pygit2_repo = pygit2.Repository(str(p))
    except pygit2.GitError as e:
        raise WrenchRepoNotFoundError(str(e)) from e

    if configure_credentials:
        # Ensure Wrench credential helper is configured locally for seamless auth
        try:
            write_ops.ensure_wrench_credential_config(p, pygit2_repo=pygit2_repo)
        except Exception as e:
            logger.debug("Failed configuring credential helper: %s", e)

        # Ensure Git LFS filter is installed locally if repo uses LFS
        try:
            gitattributes = p / ".gitattributes"
            if gitattributes.exists() and lfs_available():
                content = gitattributes.read_text(encoding="utf-8", errors="replace")
                if "filter=lfs" in content:
                    write_ops.run_git(p, ["lfs", "install", "--local"], check=False)
        except Exception as e:
            logger.debug("Failed configuring local LFS filter: %s", e)

    return RepoHandle(pygit2_repo, p)


def get_status(repo: RepoHandle) -> RepoStatus:
    return read_ops.get_status(repo)


def get_diff(
    repo: RepoHandle,
    path: str,
    *,
    staged: bool,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    return read_ops.get_diff(
        repo,
        path,
        staged=staged,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
    all_refs: bool = False,
) -> list[Commit]:
    return read_ops.get_log(repo, filter, limit=limit, offset=offset, all_refs=all_refs)


def get_log_page(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 500,
    cursor_sha: str | None = None,
    all_refs: bool = False,
) -> LogPage:
    return read_ops.get_log_page(
        repo,
        filter,
        limit=limit,
        cursor_sha=cursor_sha,
        all_refs=all_refs,
    )


def iter_commits(repo: RepoHandle, *, all_refs: bool = False):
    return _read_iter_commits(repo, all_refs=all_refs)


def get_commit_diff(
    repo: RepoHandle,
    sha: str,
    path: str | None = None,
    *,
    max_lines: int | None = None,
    max_bytes: int | None = None,
) -> Diff:
    return read_ops.get_commit_diff(
        repo,
        sha,
        path=path,
        max_lines=max_lines,
        max_bytes=max_bytes,
    )


def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]:
    return read_ops.get_commit_file_stats(repo, sha)


def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]:
    return read_ops.get_ref_labels(repo)


def get_repo_refs_signature(
    repo: RepoHandle,
) -> tuple[str, bool, bool, str, str, str] | None:
    return read_ops.get_repo_refs_signature(repo)


def blame(repo: RepoHandle, path: str) -> list[BlameLine]:
    return read_ops.blame_file(repo, path)


def stage_file(repo: RepoHandle, path: str) -> None:
    """Stage an entire file (add to index, or remove from index for deleted files)."""
    repo.pygit2_repo.index.read()
    full_path = repo.path / path
    if full_path.exists():
        repo.pygit2_repo.index.add(path)
    else:
        try:
            repo.pygit2_repo.index.remove(path)
        except KeyError, OSError:
            pass
    repo.pygit2_repo.index.write()


def unstage_file(repo: RepoHandle, path: str) -> None:
    """Unstage a file (restore index entry to match HEAD)."""
    if repo.pygit2_repo.head_is_unborn:
        repo.pygit2_repo.index.read()
        try:
            repo.pygit2_repo.index.remove(path)
            repo.pygit2_repo.index.write()
        except KeyError, OSError:
            pass
    else:
        write_ops.run_git(repo.path, ["reset", "HEAD", "--", path])
        repo.pygit2_repo.index.read()


def stage_hunk(repo: RepoHandle, path: str, hunk_id: str) -> None:
    """Stage a single hunk via constructed patch + git apply --cached."""
    diff = read_ops.get_diff(repo, path, staged=False)
    if diff.is_binary:
        raise BinaryFileStagingError(f"Cannot stage hunks of binary file: {path}")

    target_hunk = None
    for h in diff.hunks:
        if h.id == hunk_id:
            target_hunk = h
            break

    if target_hunk is None:
        raise PatchApplyError(f"Hunk '{hunk_id}' not found in diff for {path}")

    patch_text = _build_hunk_patch(path, target_hunk)
    _apply_patch(repo, patch_text)


def stage_lines(repo: RepoHandle, path: str, line_numbers: list[int]) -> None:
    """Stage specific lines within a diff via a synthetic partial patch."""
    diff = read_ops.get_diff(repo, path, staged=False)
    if diff.is_binary:
        raise BinaryFileStagingError(f"Cannot stage lines of binary file: {path}")

    for hunk in diff.hunks:
        patch_text = _build_line_patch(path, hunk, line_numbers)
        if patch_text:
            _apply_patch(repo, patch_text)
            return

    raise PatchApplyError(f"No matching hunk found for lines {line_numbers} in {path}")


def _build_hunk_patch(path: str, hunk: Hunk) -> str:
    """Build a standalone patch from a single hunk."""
    lines = [
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@",
    ]
    for dl in hunk.lines:
        lines.append(f"{dl.origin}{dl.content}")

    return "\n".join(lines) + "\n"


def _build_line_patch(path: str, hunk: Hunk, line_numbers: list[int]) -> str | None:
    """Build a synthetic patch from specific lines within a hunk."""
    hunk_new_lines = {
        dl.new_lineno for dl in hunk.lines if dl.origin == "+" and dl.new_lineno is not None
    }
    hunk_old_lines = {
        dl.old_lineno for dl in hunk.lines if dl.origin == "-" and dl.old_lineno is not None
    }
    requested = set(line_numbers)

    if not (requested & hunk_new_lines) and not (requested & hunk_old_lines):
        return None

    new_lines = []
    old_count = 0
    new_count = 0

    for dl in hunk.lines:
        if dl.origin == " ":
            new_lines.append(f" {dl.content}")
            old_count += 1
            new_count += 1
        elif dl.origin == "+":
            if dl.new_lineno in requested:
                new_lines.append(f"+{dl.content}")
                new_count += 1
        elif dl.origin == "-":
            if dl.old_lineno in requested:
                new_lines.append(f"-{dl.content}")
                old_count += 1
            else:
                new_lines.append(f" {dl.content}")
                old_count += 1
                new_count += 1

    header = f"@@ -{hunk.old_start},{old_count} +{hunk.new_start},{new_count} @@"
    result = [f"--- a/{path}", f"+++ b/{path}", header] + new_lines
    return "\n".join(result) + "\n"


def _apply_patch(repo: RepoHandle, patch_text: str) -> None:
    """Write a patch to a temp file and apply it to the index."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
        f.write(patch_text)
        tmp_path = f.name

    try:
        write_ops.run_git(repo.path, ["apply", "--cached", tmp_path])
        repo.pygit2_repo.index.read()
    except write_ops.GitCommandError as e:
        raise PatchApplyError(f"git apply --cached failed: {e.stderr}", stderr=e.stderr) from e
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def commit(repo: RepoHandle, message: str, *, amend: bool = False) -> str:
    sha = write_ops.commit(repo.path, message, amend=amend)
    repo.pygit2_repo.index.read()
    return sha


def list_branches(repo: RepoHandle) -> list[str]:
    return list(repo.pygit2_repo.branches.local)


def create_branch(repo: RepoHandle, name: str, *, from_ref: str = "HEAD") -> None:
    write_ops.create_branch(repo.path, name, from_ref)


def switch_branch(repo: RepoHandle, name: str) -> None:
    write_ops.switch_branch(repo.path, name)
    repo.pygit2_repo.index.read()


def delete_branch(repo: RepoHandle, name: str, *, force: bool = False) -> None:
    from . import snapshots

    snapshots.take_snapshot(repo, "pre_risky_op")
    write_ops.delete_branch(repo.path, name, force=force)


def rename_branch(repo: RepoHandle, old: str, new: str) -> None:
    write_ops.rename_branch(repo.path, old, new)


def discard_file(repo: RepoHandle, path: str) -> None:
    """Discard all changes in a tracked or untracked file."""
    write_ops.discard_file(repo.path, path)
    repo.pygit2_repo.index.read()


def stash_create(repo: RepoHandle, message: str | None = None) -> str:
    res = write_ops.stash_push(repo.path, message)
    repo.pygit2_repo.index.read()
    return res


def stash_pop(repo: RepoHandle, stash_id: str | int = 0) -> None:
    write_ops.stash_pop(repo.path, stash_id)
    repo.pygit2_repo.index.read()


def stash_apply(repo: RepoHandle, stash_id: str) -> None:
    write_ops.stash_apply(repo.path, stash_id)
    repo.pygit2_repo.index.read()


def stash_drop(repo: RepoHandle, stash_id: str) -> None:
    write_ops.stash_drop(repo.path, stash_id)


def check_identity(repo_or_path: RepoHandle | Path | str) -> tuple[str, str]:
    path = repo_or_path.path if isinstance(repo_or_path, RepoHandle) else Path(repo_or_path)
    return identity.check_identity(path)


def set_identity(repo_or_path: RepoHandle | Path | str, name: str, email: str) -> None:
    path = repo_or_path.path if isinstance(repo_or_path, RepoHandle) else Path(repo_or_path)
    identity.set_identity(path, name, email)


def get_reflog(repo: RepoHandle) -> list[ReflogEntry]:
    return reflog.get_reflog(repo)


def restore_to_ref(repo: RepoHandle, sha: str) -> None:
    reflog.restore_to_ref(repo, sha)


def push(
    repo: RepoHandle,
    remote: str,
    branch: str,
    *,
    force: bool = False,
    extra_config: dict[str, str] | None = None,
    timeout: float = 1800.0,
    progress_cb=None,
    cancel_event=None,
) -> None:
    write_ops.push(
        repo.path,
        remote,
        branch,
        force=force,
        extra_config=extra_config,
        timeout=timeout,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )


def push_incremental_batches(
    repo: RepoHandle,
    remote: str,
    branch: str,
    *,
    chunk_size: int = 20,
    force: bool = False,
    extra_config: dict[str, str] | None = None,
    progress_cb=None,
    cancel_event=None,
) -> None:
    write_ops.push_incremental_batches(
        repo.path,
        remote,
        branch,
        chunk_size=chunk_size,
        force=force,
        extra_config=extra_config,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )


def pull(
    repo: RepoHandle,
    remote: str,
    branch: str,
    *,
    progress_cb=None,
    cancel_event=None,
) -> None:
    write_ops.pull(
        repo.path,
        remote,
        branch,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )


def fetch(
    repo: RepoHandle,
    remote: str,
    *,
    db_conn=None,
    progress_cb=None,
    cancel_event=None,
) -> None:
    write_ops.fetch(
        repo.path,
        remote,
        db_conn=db_conn,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )


_REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_remote_name(name: str) -> None:
    if not name or not _REMOTE_NAME_RE.match(name):
        raise GitCommandError(
            ["remote"],
            1,
            f"Invalid remote name: '{name}'. Must match ^[A-Za-z0-9][A-Za-z0-9._-]*$",
        )


def _validate_remote_url(url: str) -> None:
    u = url.strip()
    if not u:
        raise GitCommandError(["remote"], 1, "Invalid remote url: empty URL.")
    if u.startswith(("https://", "http://", "ssh://")):
        return
    if "@" in u and ":" in u and not u.startswith("/"):
        return
    raise GitCommandError(
        ["remote"],
        1,
        f"Invalid remote url: '{url}'. Supported schemes: https://, http://, ssh://, "
        "user@host:path",
    )


def list_remotes(
    repo: RepoHandle,
    *,
    db_conn: sqlite3.Connection | None = None,
) -> list[RemoteInfo]:
    """List configured remotes without network latency."""
    remotes_list: list[RemoteInfo] = []

    conn = db_conn
    should_close = False
    if conn is None:
        try:
            from wrench.storage import db

            conn = db.get_connection()
            should_close = True
        except Exception:
            conn = None

    try:
        repo_id = None
        if conn:
            from wrench.storage import repo_registry, settings

            try:
                rec = repo_registry.get_repo_by_path(conn, str(repo.path))
                if rec:
                    repo_id = rec.id
            except Exception as e:
                logger.debug("Failed resolving repo from path: %s", e)

        for remote in repo.pygit2_repo.remotes:
            last_fetch = None
            reachable = None
            if conn:
                r_val = None
                if repo_id is not None:
                    last_fetch = settings.get_setting(
                        conn, f"repo.{repo_id}.remote_last_fetch.{remote.name}"
                    )
                    r_val = settings.get_setting(
                        conn, f"repo.{repo_id}.remote_reachable.{remote.name}"
                    )
                if not last_fetch:
                    last_fetch = settings.get_setting(conn, f"remote_last_fetch.{remote.name}")
                if not r_val:
                    r_val = settings.get_setting(conn, f"remote_reachable.{remote.name}")
                if r_val is not None:
                    reachable = r_val == "1" or r_val.lower() == "true"

            remotes_list.append(
                RemoteInfo(
                    name=remote.name,
                    url=remote.url,
                    last_fetch_at=last_fetch,
                    is_reachable=reachable,
                )
            )
    finally:
        if should_close and conn:
            conn.close()

    remotes_list.sort(key=lambda r: r.name)
    return remotes_list


def _probe_reachability(
    repo_path: Path, remote_name: str, db_conn: sqlite3.Connection | None = None
) -> None:
    res = write_ops.run_git(repo_path, ["ls-remote", remote_name, "HEAD"], timeout=15, check=False)
    reachable = res.returncode == 0
    conn = db_conn
    should_close = False
    if conn is None:
        try:
            from wrench.storage import db

            conn = db.get_connection()
            should_close = True
        except Exception:
            return

    try:
        from wrench.storage import repo_registry, settings

        rec = None
        try:
            rec = repo_registry.get_repo_by_path(conn, str(repo_path))
        except Exception as e:
            logger.debug("Failed looking up repo in reachability probe: %s", e)

        val = "1" if reachable else "0"
        if rec:
            settings.set_setting(conn, f"repo.{rec.id}.remote_reachable.{remote_name}", val)
        settings.set_setting(conn, f"remote_reachable.{remote_name}", val)
    except Exception as e:
        logger.debug("Failed saving reachability setting: %s", e)
    finally:
        if should_close and conn:
            conn.close()


def probe_remotes_async(
    repo: RepoHandle,
    *,
    db_conn: sqlite3.Connection | None = None,
    on_complete: Callable[[], None] | None = None,
) -> threading.Thread:
    """Probe reachability for all remotes of the repo in a background daemon thread."""

    def _worker():
        try:
            remotes = [r.name for r in repo.pygit2_repo.remotes]
            for name in remotes:
                _probe_reachability(repo.path, name, db_conn=db_conn)
        finally:
            if on_complete:
                try:
                    on_complete()
                except Exception as e:
                    logger.debug("on_complete callback raised: %s", e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t


def add_remote(
    repo: RepoHandle,
    name: str,
    url: str,
    *,
    db_conn: sqlite3.Connection | None = None,
) -> None:
    """Add a new remote, configure credential helper, and probe reachability in background."""
    _validate_remote_name(name)
    _validate_remote_url(url)

    existing = [r.name for r in repo.pygit2_repo.remotes]
    if name in existing:
        raise RemoteExistsError(name)

    write_ops.ensure_wrench_credential_config(repo.path, pygit2_repo=repo.pygit2_repo)

    write_ops.run_git(repo.path, ["remote", "add", name, url])

    probe_thread = threading.Thread(
        target=_probe_reachability,
        args=(repo.path, name, db_conn),
        daemon=True,
    )
    probe_thread.start()


def remove_remote(repo: RepoHandle, name: str) -> None:
    """Remove a configured remote."""
    existing = [r.name for r in repo.pygit2_repo.remotes]
    if name not in existing:
        raise RemoteNotFoundError(name)

    write_ops.run_git(repo.path, ["remote", "remove", name])


def set_remote_url(repo: RepoHandle, name: str, url: str) -> None:
    """Set the URL of an existing remote."""
    _validate_remote_name(name)
    _validate_remote_url(url)

    existing = [r.name for r in repo.pygit2_repo.remotes]
    if name not in existing:
        raise RemoteNotFoundError(name)

    write_ops.run_git(repo.path, ["remote", "set-url", name, url])


def get_remote_url(repo: RepoHandle, name: str) -> str:
    """Get the URL of an existing remote."""
    res = write_ops.run_git(repo.path, ["remote", "get-url", name], check=False)
    if res.returncode == 0:
        return res.stdout.strip()
    return ""


def count_unpushed_commits(repo: RepoHandle, remote: str, branch: str) -> int:
    """Count number of unpushed commits between local branch and remote tracking ref."""
    clean_b = (branch or "HEAD").replace("refs/heads/", "")
    res = write_ops.run_git(
        repo.path,
        ["rev-list", f"refs/remotes/{remote}/{clean_b}..refs/heads/{clean_b}"],
        check=False,
    )
    if res.returncode == 0:
        return len(res.stdout.splitlines())
    return 0


def merge(repo: RepoHandle, source_branch: str) -> MergeResult:
    return write_ops.merge(repo.path, source_branch)


def merge_abort(repo: RepoHandle) -> None:
    write_ops.merge_abort(repo.path)
    repo.pygit2_repo.index.read()


def rebase(repo: RepoHandle, onto: str) -> RebaseResult:
    return write_ops.rebase(repo.path, onto)


def rebase_continue(repo: RepoHandle) -> RebaseResult:
    return write_ops.rebase_continue(repo.path)


def rebase_abort(repo: RepoHandle) -> None:
    write_ops.rebase_abort(repo.path)
    repo.pygit2_repo.index.read()


def create_tag(repo: RepoHandle, name: str, target: str = "HEAD") -> None:
    write_ops.create_tag(repo.path, name, target=target)


# Recovery & Contention Facade
def check_repo_guard(repo: RepoHandle, timeout: float = 3.0):
    from .recovery import acquire_repo_guard

    return acquire_repo_guard(repo.path, timeout=timeout)


def sweep_repo_debris(repo: RepoHandle) -> list[str]:
    from .recovery import sweep_debris

    return sweep_debris(repo.path)


# Git Network & Config Helpers
def get_git_config(
    repo: RepoHandle | Path | str | None,
    key: str,
    scope: str = "local",
) -> str | None:
    """Retrieve git config value for key, returning None if unset."""
    flag = "--local" if scope == "local" else "--global"
    cwd = None
    if isinstance(repo, RepoHandle):
        cwd = repo.path
    elif repo is not None:
        cwd = Path(repo)
    else:
        cwd = Path.cwd()

    try:
        proc = write_ops.run_git(cwd, ["config", flag, "--get", key], check=False)
        if proc.returncode == 0:
            val = proc.stdout.strip()
            return val if val else None
        return None
    except Exception:
        return None


def set_git_config(
    repo: RepoHandle | Path | str | None,
    key: str,
    value: str,
    scope: str = "local",
) -> None:
    """Set git config key=value for local or global scope."""
    flag = "--local" if scope == "local" else "--global"
    cwd = None
    if isinstance(repo, RepoHandle):
        cwd = repo.path
    elif repo is not None:
        cwd = Path(repo)
    else:
        cwd = Path.cwd()

    write_ops.run_git(cwd, ["config", flag, key, str(value)])


def get_http_post_buffer(
    repo: RepoHandle | Path | str | None = None,
    scope: str = "local",
) -> int | None:
    """Retrieve git http.postBuffer in bytes, or None if unset."""
    val = get_git_config(repo, "http.postBuffer", scope=scope)
    if val:
        try:
            return int(val)
        except ValueError:
            return None
    return None


def set_http_post_buffer(
    repo: RepoHandle | Path | str | None,
    buffer_bytes: int,
    scope: str = "local",
) -> None:
    """Set git http.postBuffer in bytes for local repo or globally."""
    set_git_config(repo, "http.postBuffer", str(buffer_bytes), scope=scope)


def get_http_version(
    repo: RepoHandle | Path | str | None = None,
    scope: str = "local",
) -> str | None:
    """Retrieve git http.version (e.g. 'HTTP/1.1'), or None if unset."""
    return get_git_config(repo, "http.version", scope=scope)


def set_http_version(
    repo: RepoHandle | Path | str | None,
    version: str,
    scope: str = "local",
) -> None:
    """Set git http.version for local repo or globally."""
    set_git_config(repo, "http.version", version, scope=scope)


EXTREME_COMPRESSION_CONFIG: dict[str, str] = {
    "core.compression": "9",
    "pack.compression": "9",
    "pack.window": "10",
    "pack.depth": "50",
    "pack.windowMemory": "512m",
    "pack.threads": "0",
    "http.postBuffer": "524288000",
    "http.lowSpeedLimit": "0",
    "http.lowSpeedTime": "999999",
}


def scan_unpushed_large_blobs(
    repo: RepoHandle,
    remote: str = "origin",
    branch: str | None = None,
    threshold_mb: float = 50.0,
) -> list[tuple[str, float]]:
    """Scan unpushed commits for blobs exceeding threshold_mb.

    Returns list of (file_path, size_in_mb) sorted by size descending.
    """
    clean_branch = (branch or getattr(repo.pygit2_repo.head, "shorthand", "") or "HEAD").replace(
        "refs/heads/", ""
    )
    tracking_ref_name = f"refs/remotes/{remote}/{clean_branch}"

    pygit_repo = repo.pygit2_repo
    head_commit = None
    for target in [f"refs/heads/{clean_branch}", clean_branch, "HEAD"]:
        try:
            head_commit = pygit_repo.revparse_single(target)
            if head_commit:
                break
        except Exception:
            continue

    if not head_commit:
        return []

    remote_commit = None
    try:
        remote_commit = pygit_repo.revparse_single(tracking_ref_name)
    except Exception as e:
        logger.debug("Failed resolving tracking ref commit: %s", e)

    threshold_bytes = int(threshold_mb * 1024 * 1024)
    found_blobs: dict[str, float] = {}

    def _check_blob_entry(oid, file_path: str) -> None:
        try:
            if not oid or str(oid) == "0" * 40:
                return
            obj = pygit_repo[oid]
            if getattr(obj, "type_str", "") == "blob" and obj.size >= threshold_bytes:
                size_mb = obj.size / (1024.0 * 1024.0)
                if file_path not in found_blobs or size_mb > found_blobs[file_path]:
                    found_blobs[file_path] = size_mb
        except Exception as e:
            logger.debug("Failed checking blob entry: %s", e)

    try:
        walker = pygit_repo.walk(head_commit.id, pygit2.enums.SortMode.TOPOLOGICAL)
        if remote_commit:
            walker.hide(remote_commit.id)

        count = 0
        for commit in walker:
            count += 1
            if count > 200:
                break
            diff = None
            if commit.parents:
                diff = pygit_repo.diff(commit.parents[0].tree, commit.tree)
            else:
                try:
                    diff = commit.tree.diff_to_tree()
                except Exception:
                    diff = None
            if diff:
                for delta in diff.deltas:
                    _check_blob_entry(delta.new_file.id, delta.new_file.path)
    except Exception as e:
        logger.debug("Failed walking commits for blob scan: %s", e)

    return sorted(found_blobs.items(), key=lambda x: x[1], reverse=True)


class GitEngine:
    """Facade class providing unified access to core Git, LFS, Submodule, and Bundle operations."""

    def __init__(self, repo: RepoHandle | None = None, settings: Any = None) -> None:
        self.repo = repo
        self._settings = settings
        read_ops.configure_libgit2_cache_limits(force=True)

    def get_settings(self) -> Any:
        if self._settings is not None:
            return self._settings
        from wrench.storage.settings_registry import get_settings_registry

        self._settings = get_settings_registry()
        return self._settings

    def is_feature_enabled(self, key: str, repo_path: str | None = None) -> bool:
        rp = repo_path or (str(self.repo.path) if self.repo else None)
        return self.get_settings().is_enabled(key, rp)

    @staticmethod
    def open_repo(path: Path | str) -> RepoHandle:
        return open_repo(path)

    @staticmethod
    def init_repo(path: Path | str, bare: bool = False) -> RepoHandle:
        return init_repo(path, bare=bare)

    @staticmethod
    def clone_repo(
        url: str,
        dest: Path | str,
        branch: str | None = None,
        progress_cb: Callable[[int, int, int], None] | None = None,
        cancel_event: threading.Event | None = None,
        recursive: bool = False,
        filter_spec: str | None = None,
        sparse: bool = False,
    ) -> CloneResult:
        return clone_repo(
            url,
            dest,
            branch=branch,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            recursive=recursive,
            filter_spec=filter_spec,
            sparse=sparse,
        )

    def get_status(self, repo: RepoHandle | None = None) -> RepoStatus:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return get_status(target)

    def stage_file(self, path: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        stage_file(target, path)

    def unstage_file(self, path: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        unstage_file(target, path)

    def stage_all(self, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        from .write_ops import run_git

        run_git(target.path, ["add", "-A"])

    def unstage_all(self, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        from .write_ops import run_git

        run_git(target.path, ["reset", "HEAD", "--"])

    def commit(
        self,
        message: str,
        amend: bool = False,
        author: tuple[str, str] | None = None,
        repo: RepoHandle | None = None,
    ) -> str:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return commit(target, message, amend=amend)

    def get_diff(
        self,
        path: str,
        staged: bool = False,
        repo: RepoHandle | None = None,
        *,
        max_lines: int | None = None,
        max_bytes: int | None = None,
    ) -> Diff:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return get_diff(
            target,
            path,
            staged=staged,
            max_lines=max_lines,
            max_bytes=max_bytes,
        )

    def get_commit_history(
        self,
        max_count: int = 100,
        skip: int = 0,
        branch: str | None = None,
        filter_opts: LogFilter | None = None,
        repo: RepoHandle | None = None,
    ) -> list[Commit]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return get_log(
            target,
            limit=max_count,
            offset=skip,
            all_refs=(branch is None),
            filter=filter_opts,
        )

    def get_log_page(
        self,
        filter: LogFilter | None = None,
        *,
        limit: int = 500,
        cursor_sha: str | None = None,
        all_refs: bool = False,
        repo: RepoHandle | None = None,
    ) -> LogPage:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return get_log_page(
            target,
            filter=filter,
            limit=limit,
            cursor_sha=cursor_sha,
            all_refs=all_refs,
        )

    def create_branch(
        self,
        name: str,
        start_point: str | None = None,
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        create_branch(target, name, from_ref=start_point or "HEAD")

    def checkout_branch(self, name: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        switch_branch(target, name)

    def fetch_remote(self, remote: str = "origin", repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        fetch(target, remote=remote)

    def pull_remote(
        self,
        remote: str = "origin",
        branch: str | None = None,
        repo: RepoHandle | None = None,
    ) -> MergeResult:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return pull(target, remote=remote, branch=branch or "")

    def push_remote(
        self,
        remote: str = "origin",
        branch: str | None = None,
        set_upstream: bool = False,
        force: bool = False,
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        push(
            target,
            remote=remote,
            branch=branch or "",
            force=force,
        )

    def get_remotes(self, repo: RepoHandle | None = None) -> list[Remote]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return list_remotes(target)

    # Git LFS
    @staticmethod
    def is_lfs_installed() -> bool:
        return is_lfs_installed()

    @staticmethod
    def lfs_available() -> bool:
        return lfs_available()

    @staticmethod
    def is_lfs_pointer(content: str) -> bool:
        return is_lfs_pointer(content)

    @staticmethod
    def parse_lfs_pointer(content: str) -> tuple[str, str] | None:
        return parse_lfs_pointer(content)

    def lfs_files(self, paths: list[str], repo: RepoHandle | None = None) -> set[str]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return lfs_files(target, paths)

    def lfs_track(self, pattern: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_track(target, pattern)

    def lfs_untrack(self, pattern: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_untrack(target, pattern)

    def lfs_pull(self, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_pull(target)

    def lfs_push(
        self,
        remote: str = "origin",
        branch: str | None = None,
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_push(target, remote=remote, branch=branch)

    def lfs_status(self, repo: RepoHandle | None = None) -> list[LfsFileStatus]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        if not self.is_feature_enabled("lfs.enabled", str(target.path)):
            return []
        return lfs_status(target)

    def lfs_locks(self, repo: RepoHandle | None = None) -> list[LFSLock]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        if not self.is_feature_enabled("lfs.enabled", str(target.path)):
            return []
        return lfs_locks(target)

    def lfs_lock(self, path: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_lock(target, path)

    def lfs_unlock(self, path: str, force: bool = False, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        lfs_unlock(target, path, force=force)

    # Submodules
    def list_submodules(self, repo: RepoHandle | None = None) -> list[Submodule]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        if not self.is_feature_enabled("submodules.enabled", str(target.path)):
            return []
        return list_submodules(target)

    def submodule_status(self, path: str, repo: RepoHandle | None = None) -> SubmoduleStatus:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return submodule_status(target, path)

    def init_submodule(self, path: str | None = None, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        init_submodule(target, path=path)

    def update_submodules(
        self,
        path: str | None = None,
        recursive: bool = True,
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        update_submodules(target, path=path, recursive=recursive)

    def sync_submodules(self, path: str | None = None, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        sync_submodules(target, path=path)

    def add_submodule(self, url: str, path: str, repo: RepoHandle | None = None) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        add_submodule(target, url, path)

    # Git Bundles
    def create_bundle(
        self,
        output_path: Path | str,
        revs: list[str] | None = None,
        repo: RepoHandle | None = None,
    ) -> Path:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return create_bundle(target, output_path, revs=revs)

    @staticmethod
    def verify_bundle(bundle_path: Path | str, repo: RepoHandle | None = None) -> bool:
        return verify_bundle(bundle_path, repo=repo)

    def unbundle(self, bundle_path: Path | str, repo: RepoHandle | None = None) -> list[str]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return unbundle(target, bundle_path)

    @staticmethod
    def get_bundle_info(bundle_path: Path | str, repo: RepoHandle | None = None) -> BundleInfo:
        return get_bundle_info(bundle_path, repo=repo)

    # Reflog
    def list_reflog(
        self,
        ref: str = "HEAD",
        limit: int = 100,
        repo: RepoHandle | None = None,
    ) -> list[ReflogEntry]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        return list_reflog(target, ref=ref, limit=limit)

    def reset_to_reflog_entry(
        self,
        sha: str,
        mode: str = "hard",
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        reset_to_reflog_entry(target, sha, mode=mode)

    def create_branch_from_reflog(
        self,
        branch_name: str,
        sha: str,
        repo: RepoHandle | None = None,
    ) -> None:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        create_branch_from_reflog(target, branch_name, sha)

    # Monorepo Sparse-Checkout & Commit-Graph Maintenance (VP-16)
    @staticmethod
    def is_unborn_repo(repo_path: Path | str) -> bool:
        return is_unborn_repo(repo_path)

    @staticmethod
    def refresh_repo_handle(repo: RepoHandle | None) -> None:
        refresh_repo_handle(repo)

    @staticmethod
    def get_repo_refs_signature(
        repo: RepoHandle,
    ) -> tuple[str, bool, bool, str, str, str] | None:
        return get_repo_refs_signature(repo)

    @staticmethod
    def is_sparse_checkout_enabled(repo_path: Path | str) -> bool:
        return is_sparse_checkout_enabled(repo_path)

    @staticmethod
    def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState:
        return get_sparse_checkout_state(repo_path)

    @staticmethod
    def init_sparse_checkout(repo_path: Path | str, cone: bool = True) -> None:
        init_sparse_checkout(repo_path, cone=cone)

    @staticmethod
    def list_sparse_directories(repo_path: Path | str) -> list[str]:
        return list_sparse_directories(repo_path)

    @staticmethod
    def set_sparse_directories(
        repo_path: Path | str,
        dirs: list[str],
        *,
        cone: bool = True,
        warnings_out: list[str] | None = None,
    ) -> None:
        set_sparse_directories(repo_path, dirs, cone=cone, warnings_out=warnings_out)

    @staticmethod
    def disable_sparse_checkout(
        repo_path: Path | str,
        *,
        warnings_out: list[str] | None = None,
    ) -> None:
        disable_sparse_checkout(repo_path, warnings_out=warnings_out)

    @staticmethod
    def list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]:
        return list_head_top_directories(repo_path, max_depth=max_depth)

    @staticmethod
    def list_tree_subdirectories(
        repo_path: Path | str,
        parent_rel_path: str = "",
    ) -> list[TreeDirectoryEntry]:
        return list_tree_subdirectories(repo_path, parent_rel_path=parent_rel_path)

    @staticmethod
    def write_commit_graph(
        repo_path: Path | str,
        *,
        reachable: bool = True,
        changed_paths: bool = True,
        timeout: int = 120,
    ) -> CommitGraphStats:
        return write_commit_graph(
            repo_path,
            reachable=reachable,
            changed_paths=changed_paths,
            timeout=timeout,
        )

    def maybe_write_commit_graph(
        self,
        repo_path: Path | str | None = None,
        *,
        settings_registry: Any = None,
    ) -> CommitGraphStats:
        target_path = (
            Path(repo_path) if repo_path is not None else (self.repo.path if self.repo else None)
        )
        if target_path is None:
            raise ValueError("No repository provided")
        return maybe_write_commit_graph(
            target_path,
            settings_registry=settings_registry or self._settings,
        )

    def list_commits_for_interactive_rebase(
        self,
        base_oid: str,
        repo: RepoHandle | None = None,
        *,
        limit: int = 1000,
    ) -> list[RebaseTodoEntry]:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        if not self.is_feature_enabled("rebase.interactive_ui.enabled", str(target.path)):
            return []
        return list_commits_for_interactive_rebase(target, base_oid, limit=limit)

    def interactive_rebase(
        self,
        base_oid: str,
        entries: list[RebaseTodoEntry],
        repo: RepoHandle | None = None,
        *,
        autostash: bool | None = None,
        autosquash: bool | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> RebaseResult:
        target = repo or self.repo
        if not target:
            raise ValueError("No repository provided")
        repo_str = str(target.path)
        if not self.is_feature_enabled("rebase.interactive_ui.enabled", repo_str):
            raise WrenchGitError(
                "Visual Interactive Rebase is disabled in Settings (rebase.interactive_ui.enabled)."
            )
        reg = self.get_settings()
        eff_autostash = (
            reg.get_bool("rebase.autostash", repo_str) if autostash is None else bool(autostash)
        )
        eff_autosquash = (
            reg.get_bool("rebase.autosquash", repo_str) if autosquash is None else bool(autosquash)
        )
        return interactive_rebase(
            target,
            base_oid,
            entries,
            autostash=eff_autostash,
            autosquash=eff_autosquash,
            conn=conn,
        )


def is_unborn_repo(repo_path: Path | str) -> bool:
    """Return True if the repository exists and has an unborn HEAD."""
    try:
        return bool(pygit2.Repository(str(Path(repo_path))).head_is_unborn)
    except pygit2.GitError as exc:
        raise WrenchRepoNotFoundError(str(exc)) from exc


def refresh_repo_handle(repo: RepoHandle | None) -> None:
    """Safely reload a RepoHandle's underlying pygit2.Repository if present and valid."""
    if repo is None or not hasattr(repo, "reload"):
        return
    try:
        repo.reload()
    except WrenchRepoNotFoundError as exc:
        logger.debug("RepoHandle reload skipped for '%s': %s", getattr(repo, "path", "?"), exc)


def is_sparse_checkout_enabled(repo_path: Path | str) -> bool:
    return sparse_checkout.is_sparse_checkout_enabled(repo_path)


def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState:
    return sparse_checkout.get_sparse_checkout_state(repo_path)


def init_sparse_checkout(repo_path: Path | str, cone: bool = True) -> None:
    sparse_checkout.init_sparse_checkout(repo_path, cone=cone)


def list_sparse_directories(repo_path: Path | str) -> list[str]:
    return sparse_checkout.list_sparse_directories(repo_path)


def set_sparse_directories(
    repo_path: Path | str,
    dirs: list[str],
    *,
    cone: bool = True,
    warnings_out: list[str] | None = None,
) -> None:
    sparse_checkout.set_sparse_directories(
        repo_path,
        dirs,
        cone=cone,
        warnings_out=warnings_out,
    )


def disable_sparse_checkout(
    repo_path: Path | str,
    *,
    warnings_out: list[str] | None = None,
) -> None:
    sparse_checkout.disable_sparse_checkout(repo_path, warnings_out=warnings_out)


def list_head_top_directories(repo_path: Path | str, max_depth: int = 2) -> list[str]:
    return sparse_checkout.list_head_top_directories(repo_path, max_depth=max_depth)


def list_tree_subdirectories(
    repo_path: Path | str,
    parent_rel_path: str = "",
) -> list[TreeDirectoryEntry]:
    return sparse_checkout.list_tree_subdirectories(repo_path, parent_rel_path=parent_rel_path)


def write_commit_graph(
    repo_path: Path | str,
    *,
    reachable: bool = True,
    changed_paths: bool = True,
    timeout: int = 120,
) -> CommitGraphStats:
    return write_ops.write_commit_graph(
        repo_path,
        reachable=reachable,
        changed_paths=changed_paths,
        timeout=timeout,
    )


def maybe_write_commit_graph(
    repo_path: Path | str,
    settings_registry: Any = None,
) -> CommitGraphStats:
    """Gate commit-graph maintenance cleanly against maintenance.auto_commit_graph.enabled."""
    from wrench.storage.settings_registry import peek_settings_registry

    reg = settings_registry or peek_settings_registry()
    if reg is not None and not reg.is_enabled(
        "maintenance.auto_commit_graph.enabled", str(repo_path)
    ):
        return CommitGraphStats(written=False, duration_ms=0, skipped_reason="disabled")
    return write_commit_graph(repo_path)


def build_interactive_rebase_cli_args(
    base_oid: str,
    *,
    autostash: bool = True,
    autosquash: bool = True,
) -> list[str]:
    return rebase_sequencer.build_interactive_rebase_cli_args(
        base_oid,
        autostash=autostash,
        autosquash=autosquash,
    )


def get_interactive_rebase_target_label(
    repo: RepoHandle | Path | str,
    base_oid: str,
) -> tuple[str, str, bool]:
    repo_path = repo.path if isinstance(repo, RepoHandle) else Path(repo)
    return rebase_sequencer.get_interactive_rebase_target_label(repo_path, base_oid)


def list_commits_for_interactive_rebase_checked(
    repo: RepoHandle | Path | str,
    base_oid: str,
    *,
    limit: int = 1000,
) -> tuple[list[RebaseTodoEntry], bool]:
    repo_path = repo.path if isinstance(repo, RepoHandle) else Path(repo)
    return rebase_sequencer.list_commits_for_interactive_rebase_checked(
        repo_path,
        base_oid,
        limit=limit,
    )


def list_commits_for_interactive_rebase(
    repo: RepoHandle | Path | str,
    base_oid: str,
    *,
    limit: int = 1000,
) -> list[RebaseTodoEntry]:
    repo_path = repo.path if isinstance(repo, RepoHandle) else Path(repo)
    return rebase_sequencer.list_commits_for_interactive_rebase(
        repo_path,
        base_oid,
        limit=limit,
    )


def interactive_rebase(
    repo: RepoHandle,
    base_oid: str,
    entries: list[RebaseTodoEntry],
    *,
    autostash: bool = True,
    autosquash: bool = True,
    conn: sqlite3.Connection | None = None,
) -> RebaseResult:
    from . import snapshots

    snapshots.maybe_create_safety_snapshot(repo, "interactive_rebase", conn=conn)
    result = rebase_sequencer.run_interactive_rebase(
        repo.path,
        base_oid,
        entries,
        autostash=autostash,
        autosquash=autosquash,
    )
    refresh_repo_handle(repo)
    return result
