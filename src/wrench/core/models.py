"""Data models and dataclasses for Wrench core."""

from dataclasses import dataclass, field
from pathlib import Path


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
    def partially_staged_paths(self) -> set[str]:
        return {f.path for f in self.partially_staged}

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


class RefName(str):
    """String wrapper supporting both prefixed ('local:main', 'tag:v1.0') and unprefixed equality."""

    def __eq__(self, other: object) -> bool:
        if super().__eq__(other):
            return True
        if isinstance(other, str):
            for prefix in ("local:", "remote:", "tag:", "head:"):
                if self.startswith(prefix) and self.removeprefix(prefix) == other:
                    return True
                if other.startswith(prefix) and other.removeprefix(prefix) == self:
                    return True
        return False


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
    refs: list[RefName] = field(default_factory=list)

    @property
    def author(self) -> str:
        return self.author_name

    @property
    def hex(self) -> str:
        return self.sha


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
    """Returned by clone_repo on success."""

    path: Path


@dataclass
class RemoteInfo:
    """Represents a configured git remote."""

    name: str
    url: str
    last_fetch_at: str | None = None
    is_reachable: bool | None = None

    @property
    def fetch_url(self) -> str:
        return self.url


@dataclass
class LfsFileStatus:
    """Git LFS tracked file status."""

    path: str
    is_pointer: bool
    oid: str | None = None
    size: int | None = None
    is_locked: bool = False
    locked_by: str | None = None


@dataclass(frozen=True)
class LFSLock:
    """Git LFS file lock."""

    lock_id: str
    path: str
    owner: str


@dataclass
class BundleInfo:
    """Git bundle metadata."""

    path: Path
    is_valid: bool
    prerequisites: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SparseCheckoutState:
    """Current sparse-checkout configuration for a repository or linked worktree."""

    enabled: bool
    cone_mode: bool
    directories: tuple[str, ...]
    partial_filter: str | None = None


@dataclass(slots=True, frozen=True)
class TreeDirectoryEntry:
    """Single directory node returned for lazy tree expansion at HEAD."""

    name: str
    rel_path: str
    has_children: bool
    is_selected: bool = False


@dataclass(slots=True, frozen=True)
class LogPage:
    """Windowed commit page returned by bounded pygit2 walker queries."""

    commits: tuple[Commit, ...]
    next_cursor_sha: str | None
    has_more: bool
    scanned_count: int = 0


@dataclass(slots=True, frozen=True)
class CommitGraphStats:
    """Outcome metadata returned by background git commit-graph maintenance."""

    written: bool
    duration_ms: int
    skipped_reason: str | None = None  # None | 'disabled' | 'empty_repo' | 'locked' | 'error'
    graph_file_size_bytes: int = 0


@dataclass(slots=True, frozen=True)
class WatcherStatusInfo:
    """Active monitoring strategy reported by RepoWatcher."""

    mode: str  # 'full_inotify' | 'git_dir_inotify' | 'polling' | 'disabled'
    is_fallback: bool
    watched_paths: tuple[str, ...]
    reason: str | None = None


@dataclass(slots=True, frozen=True)
class RebaseTodoEntry:
    """Single instruction row for an interactive rebase plan (VP-2, FR-3.5)."""

    action: str  # 'pick' | 'reword' | 'edit' | 'squash' | 'fixup' | 'drop'
    oid: str
    short_oid: str
    summary: str
    author: str
    new_message: str | None = None


# ---------------------------------------------------------------------------
# VP-2.5: Multi-Branch & Remote DAG Walk, Ref Sidebar & Sync Models (FR-3.16)
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BranchInfo:
    """Metadata for a local or remote branch in the sidebar tree."""

    name: str
    is_head: bool
    upstream_name: str | None = None
    ahead: int = 0
    behind: int = 0
    target_oid: str = ""


@dataclass(slots=True, frozen=True)
class TagInfo:
    """Metadata for an annotated or lightweight tag."""

    name: str
    target_oid: str
    message: str | None = None
    tagger_date: str | None = None


@dataclass(slots=True, frozen=True)
class StashEntry:
    """Metadata for a git stash item."""

    index: int
    message: str
    oid: str
    timestamp: str | None = None


@dataclass(slots=True, frozen=True)
class BranchSyncStatus:
    """Ahead/behind counts and tracking upstream for the active branch."""

    branch_name: str
    upstream_name: str | None
    ahead: int = 0
    behind: int = 0
    is_detached: bool = False


@dataclass(slots=True, frozen=True)
class RefSidebarTree:
    """Structured ref inventory for the History view left sidebar."""

    local_branches: tuple[BranchInfo, ...] = ()
    remote_branches: tuple[BranchInfo, ...] = ()
    tags: tuple[TagInfo, ...] = ()
    stashes: tuple[StashEntry, ...] = ()
