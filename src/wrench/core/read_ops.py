"""Git read operations — pygit2-backed.

All read operations (status, diff, log, blame) go through this module.
UI code never calls this module directly — it goes through core.engine.
"""

from collections.abc import Iterator
from datetime import datetime, timezone

import pygit2

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
    except Exception:
        pass

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
        except (KeyError, pygit2.GitError):
            pass

    # Conflicts
    has_conflicts = False
    try:
        if r.index.conflicts is not None:
            has_conflicts = any(True for _ in r.index.conflicts)
    except Exception:
        pass

    # Merge / Rebase state from pygit2 repository state
    pygit_state = r.state()
    merge_in_progress = pygit_state == _STATE_MERGE
    rebase_in_progress = pygit_state in _REBASE_STATES

    # File status
    staged: list[FileChange] = []
    unstaged: list[FileChange] = []
    untracked: list[str] = []

    status_dict = r.status()
    for filepath, flags in status_dict.items():
        if flags & pygit2.GIT_STATUS_WT_NEW:
            untracked.append(filepath)
            continue

        for flag, change_type in _STAGED_FLAGS.items():
            if flags & flag:
                staged.append(FileChange(path=filepath, change_type=change_type))
                break

        for flag, change_type in _UNSTAGED_FLAGS.items():
            if flags & flag:
                unstaged.append(FileChange(path=filepath, change_type=change_type))
                break

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
    )


def get_diff(repo: RepoHandle, path: str, *, staged: bool) -> Diff:
    """Get the diff for a single file in working tree / index."""
    r = repo.pygit2_repo
    try:
        r.index.read()
    except Exception:
        pass

    if staged:
        if r.head_is_unborn:
            diff = r.index.diff_to_tree()
        else:
            head_tree = r.head.peel(pygit2.Tree)
            diff = r.index.diff_to_tree(head_tree)
    else:
        diff = r.diff(flags=pygit2.GIT_DIFF_INCLUDE_UNTRACKED)

    for patch in diff:
        delta = patch.delta
        if delta.new_file.path == path or delta.old_file.path == path:
            if delta.is_binary:
                return Diff(path=path, is_binary=True, hunks=[])

            hunks: list[Hunk] = []
            for i, hunk in enumerate(patch.hunks):
                lines: list[DiffLine] = []
                for line in hunk.lines:
                    lines.append(
                        DiffLine(
                            content=line.content.rstrip("\n"),
                            origin=line.origin,
                            old_lineno=line.old_lineno if line.old_lineno >= 0 else None,
                            new_lineno=line.new_lineno if line.new_lineno >= 0 else None,
                        )
                    )
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

            return Diff(path=path, is_binary=False, hunks=hunks)

    return Diff(path=path, is_binary=False, hunks=[])


def get_commit_diff(repo: RepoHandle, sha: str, path: str | None = None) -> Diff:
    """Get diff of a historical commit against its first parent (or empty tree for root)."""
    r = repo.pygit2_repo
    commit = r.get(sha)
    if not commit or not isinstance(commit, pygit2.Commit):
        return Diff(path=path or "", is_binary=False, hunks=[])

    if commit.parents:
        parent_tree = commit.parents[0].tree
    else:
        empty_tree_id = r.TreeBuilder().write()
        parent_tree = r[empty_tree_id]

    diff = r.diff(parent_tree, commit.tree)

    for patch in diff:
        delta = patch.delta
        target_path = delta.new_file.path or delta.old_file.path
        if path is not None and target_path != path:
            continue

        if delta.is_binary:
            return Diff(path=target_path, is_binary=True, hunks=[])

        hunks: list[Hunk] = []
        for i, hunk in enumerate(patch.hunks):
            lines: list[DiffLine] = []
            for line in hunk.lines:
                lines.append(
                    DiffLine(
                        content=line.content.rstrip("\n"),
                        origin=line.origin,
                        old_lineno=line.old_lineno if line.old_lineno >= 0 else None,
                        new_lineno=line.new_lineno if line.new_lineno >= 0 else None,
                    )
                )
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

        if path is not None:
            return Diff(path=target_path, is_binary=False, hunks=hunks)

        # If path was None and we found the first patch, return it
        return Diff(path=target_path, is_binary=False, hunks=hunks)

    return Diff(path=path or "", is_binary=False, hunks=[])


def get_commit_file_stats(repo: RepoHandle, sha: str) -> list[FileStat]:
    """Get list of changed files with +additions / -deletions for a commit."""
    r = repo.pygit2_repo
    commit = r.get(sha)
    if not commit or not isinstance(commit, pygit2.Commit):
        return []

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
        except Exception:
            pass

    # 2. Tags
    for ref_name in r.references:
        if ref_name.startswith("refs/tags/"):
            tag_name = ref_name.removeprefix("refs/tags/")
            ref = r.references[ref_name]
            try:
                obj = r.get(ref.target)
                if isinstance(obj, pygit2.Commit):
                    add_label(str(obj.id), RefLabel(name=tag_name, kind="tag"))
                elif isinstance(obj, pygit2.Tag):
                    peeled = obj.peel(pygit2.Commit)
                    add_label(str(peeled.id), RefLabel(name=tag_name, kind="tag"))
                else:
                    target_commit = ref.peel(pygit2.Commit)
                    add_label(str(target_commit.id), RefLabel(name=tag_name, kind="tag"))

            except Exception:
                pass

    # 3. HEAD
    if not r.head_is_unborn:
        try:
            head_target = r.head.target
            if r.head_is_detached:
                add_label(str(head_target), RefLabel(name="HEAD", kind="head"))
            else:
                add_label(str(head_target), RefLabel(name="HEAD", kind="head"))
        except Exception:
            pass

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
            except Exception:
                pass

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
        for patch in diff:
            delta = patch.delta
            if delta.new_file.path == path or delta.old_file.path == path:
                return True
            # Also check directory prefix match
            if delta.new_file.path.startswith(
                path.rstrip("/") + "/"
            ) or delta.old_file.path.startswith(path.rstrip("/") + "/"):
                return True
    except Exception:
        pass
    return False


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
    except (KeyError, pygit2.GitError):
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
