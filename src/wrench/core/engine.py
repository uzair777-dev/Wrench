"""Core Git Engine — public façade."""

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pygit2

from .exceptions import BinaryFileStagingError, PatchApplyError, WrenchRepoNotFoundError


@dataclass
class FileChange:
    path: str
    change_type: str  # 'added' | 'modified' | 'deleted' | 'renamed'
    old_path: str | None = None


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


@dataclass
class Commit:
    sha: str
    message: str
    author_name: str
    author_email: str
    author_date: str  # ISO 8601
    parent_shas: list[str]


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


class RepoHandle:
    """Wraps a pygit2.Repository for reads and Path for subprocess."""

    def __init__(self, pygit2_repo: pygit2.Repository, path: Path):
        self.pygit2_repo = pygit2_repo
        self.path = path


# Import read_ops and write_ops after all dataclasses are defined to avoid circular imports
from . import read_ops, write_ops  # noqa: E402


def init_repo(path: Path) -> None:
    write_ops.init_repo(path)


def clone_repo(url: str, dest: Path, *, progress_cb=None) -> None:
    write_ops.clone_repo(url, dest, progress_cb=progress_cb)


def open_repo(path: Path) -> RepoHandle:
    if not path.exists():
        raise WrenchRepoNotFoundError(f"Path does not exist: {path}")
    git_dir = path / ".git"
    if not git_dir.exists() and not (path / "HEAD").exists():
        raise WrenchRepoNotFoundError(f"Not a git repository: {path}")
    try:
        pygit2_repo = pygit2.Repository(str(path))
    except pygit2.GitError as e:
        raise WrenchRepoNotFoundError(str(e)) from e
    return RepoHandle(pygit2_repo, path)


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
) -> list[Commit]:
    return read_ops.get_log(repo, filter, limit=limit, offset=offset)


def blame(repo: RepoHandle, path: str) -> list[BlameLine]:
    return read_ops.blame_file(repo, path)


def stage_file(repo: RepoHandle, path: str) -> None:
    """Stage an entire file (add to index)."""
    repo.pygit2_repo.index.read()
    repo.pygit2_repo.index.add(path)
    repo.pygit2_repo.index.write()


def unstage_file(repo: RepoHandle, path: str) -> None:
    """Unstage a file (remove from index, keep in worktree)."""
    if repo.pygit2_repo.head_is_unborn:
        repo.pygit2_repo.index.read()
        repo.pygit2_repo.index.remove(path)
        repo.pygit2_repo.index.write()
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
    write_ops.delete_branch(repo.path, name, force=force)


def rename_branch(repo: RepoHandle, old: str, new: str) -> None:
    write_ops.rename_branch(repo.path, old, new)


def stash_create(repo: RepoHandle, message: str | None = None) -> str:
    res = write_ops.stash_push(repo.path, message)
    repo.pygit2_repo.index.read()
    return res


def stash_apply(repo: RepoHandle, stash_id: str) -> None:
    write_ops.stash_apply(repo.path, stash_id)
    repo.pygit2_repo.index.read()


def stash_drop(repo: RepoHandle, stash_id: str) -> None:
    write_ops.stash_drop(repo.path, stash_id)


def push(repo: RepoHandle, remote: str, branch: str, *, force: bool = False) -> None:
    raise NotImplementedError


def pull(repo: RepoHandle, remote: str, branch: str) -> None:
    raise NotImplementedError


def fetch(repo: RepoHandle, remote: str) -> None:
    raise NotImplementedError


def merge(repo: RepoHandle, source_branch: str) -> MergeResult:
    raise NotImplementedError


def rebase(repo: RepoHandle, onto: str) -> RebaseResult:
    raise NotImplementedError
