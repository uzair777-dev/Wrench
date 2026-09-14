import os
import re
import sqlite3
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pygit2

from .exceptions import (
    BinaryFileStagingError,
    GitCommandError,
    PatchApplyError,
    RemoteExistsError,
    RemoteNotFoundError,
    WrenchRepoNotFoundError,
)


@dataclass
class FileChange:
    path: str
    change_type: str  # 'added' | 'modified' | 'deleted' | 'renamed'
    old_path: str | None = None

    @property
    def status_code(self) -> str:
        codes = {"added": "A", "modified": "M", "deleted": "D", "renamed": "R"}
        return codes.get(self.change_type, "M")


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

    @property
    def branch_name(self) -> str | None:
        return self.current_branch

    @property
    def is_detached_head(self) -> bool:
        return self.is_detached


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


class RepoHandle:
    """Wraps a pygit2.Repository for reads and Path for subprocess."""

    def __init__(self, pygit2_repo: pygit2.Repository, path: Path):
        self.pygit2_repo = pygit2_repo
        self.path = path


# Import read_ops, write_ops, identity, reflog after all dataclasses are defined
from . import identity, read_ops, reflog, write_ops  # noqa: E402


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
) -> CloneResult:
    return write_ops.clone_repo(url, dest, progress_cb=progress_cb, cancel_event=cancel_event)


clone = clone_repo


def open_repo(path: Path | str) -> RepoHandle:
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
    return RepoHandle(pygit2_repo, p)


def get_status(repo: RepoHandle) -> RepoStatus:
    return read_ops.get_status(repo)


def get_diff(repo: RepoHandle, path: str, *, staged: bool) -> Diff:
    return read_ops.get_diff(repo, path, staged=staged)


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
    all_refs: bool = False,
) -> list[Commit]:
    return read_ops.get_log(repo, filter, limit=limit, offset=offset, all_refs=all_refs)


def iter_commits(repo: RepoHandle, *, all_refs: bool = False):
    return read_ops.iter_commits(repo, all_refs=all_refs)


def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None) -> Diff:
    return read_ops.get_commit_diff(repo, sha, path=path)


def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]:
    return read_ops.get_commit_file_stats(repo, sha)


def get_ref_labels(repo: RepoHandle) -> dict[str, list[RefLabel]]:
    return read_ops.get_ref_labels(repo)


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
        except (KeyError, OSError):
            pass
    repo.pygit2_repo.index.write()


def unstage_file(repo: RepoHandle, path: str) -> None:
    """Unstage a file (restore index entry to match HEAD)."""
    if repo.pygit2_repo.head_is_unborn:
        repo.pygit2_repo.index.read()
        try:
            repo.pygit2_repo.index.remove(path)
            repo.pygit2_repo.index.write()
        except (KeyError, OSError):
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
    progress_cb=None,
    cancel_event=None,
) -> None:
    write_ops.push(
        repo.path,
        remote,
        branch,
        force=force,
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
            except Exception:
                pass

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
        except Exception:
            pass

        val = "1" if reachable else "0"
        if rec:
            settings.set_setting(conn, f"repo.{rec.id}.remote_reachable.{remote_name}", val)
        settings.set_setting(conn, f"remote_reachable.{remote_name}", val)
    except Exception:
        pass
    finally:
        if should_close and conn:
            conn.close()


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

    write_ops.run_git(repo.path, ["config", "--local", "credential.helper", "wrench"])
    write_ops.run_git(repo.path, ["config", "--local", "credential.useHttpPath", "true"])

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
