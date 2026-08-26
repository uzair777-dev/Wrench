"""Core Git Engine — public façade."""

from dataclasses import dataclass, field
from pathlib import Path

import pygit2


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


def init_repo(path: Path) -> None:
    raise NotImplementedError


def clone_repo(url: str, dest: Path, *, progress_cb=None) -> None:
    raise NotImplementedError


def open_repo(path: Path) -> RepoHandle:
    raise NotImplementedError


def get_status(repo: RepoHandle) -> RepoStatus:
    raise NotImplementedError


def get_diff(repo: RepoHandle, path: str, *, staged: bool) -> Diff:
    raise NotImplementedError


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Commit]:
    raise NotImplementedError


def blame(repo: RepoHandle, path: str) -> list[BlameLine]:
    raise NotImplementedError


def stage_file(repo: RepoHandle, path: str) -> None:
    raise NotImplementedError


def stage_hunk(repo: RepoHandle, path: str, hunk_id: str) -> None:
    raise NotImplementedError


def stage_lines(repo: RepoHandle, path: str, line_numbers: list[int]) -> None:
    raise NotImplementedError


def unstage_file(repo: RepoHandle, path: str) -> None:
    raise NotImplementedError


def commit(repo: RepoHandle, message: str, *, amend: bool = False) -> str:
    raise NotImplementedError


def list_branches(repo: RepoHandle) -> list[str]:
    raise NotImplementedError


def create_branch(repo: RepoHandle, name: str, *, from_ref: str = "HEAD") -> None:
    raise NotImplementedError


def switch_branch(repo: RepoHandle, name: str) -> None:
    raise NotImplementedError


def delete_branch(repo: RepoHandle, name: str, *, force: bool = False) -> None:
    raise NotImplementedError


def rename_branch(repo: RepoHandle, old: str, new: str) -> None:
    raise NotImplementedError


def stash_create(repo: RepoHandle, message: str | None = None) -> str:
    raise NotImplementedError


def stash_apply(repo: RepoHandle, stash_id: str) -> None:
    raise NotImplementedError


def stash_drop(repo: RepoHandle, stash_id: str) -> None:
    raise NotImplementedError


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
