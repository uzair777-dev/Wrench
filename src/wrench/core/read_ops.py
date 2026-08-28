"""Git read operations — pygit2-backed.

All read operations (status, diff, log, blame) go through this module.
UI code never calls this module directly — it goes through core.engine.
"""

from datetime import datetime, timezone

import pygit2

from .engine import (
    BlameLine,
    Commit,
    Diff,
    DiffLine,
    FileChange,
    Hunk,
    LogFilter,
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
        has_conflicts = r.index.conflicts is not None and len(r.index.conflicts) > 0
    except pygit2.GitError:
        pass

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
    )


def get_diff(repo: RepoHandle, path: str, *, staged: bool) -> Diff:
    """Get the diff for a single file."""
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


def get_log(
    repo: RepoHandle,
    filter: LogFilter | None = None,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[Commit]:
    """Walk the commit log, paginated."""
    r = repo.pygit2_repo

    if r.head_is_unborn:
        return []

    commits: list[Commit] = []
    skipped = 0

    for git_commit in r.walk(r.head.target, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_TIME):
        author_date = datetime.fromtimestamp(
            git_commit.author.time,
            tz=timezone.utc,
        ).isoformat()

        c = Commit(
            sha=str(git_commit.id),
            message=git_commit.message.strip(),
            author_name=git_commit.author.name,
            author_email=git_commit.author.email,
            author_date=author_date,
            parent_shas=[str(p) for p in git_commit.parent_ids],
        )

        if filter:
            if filter.author and filter.author.lower() not in c.author_name.lower():
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
