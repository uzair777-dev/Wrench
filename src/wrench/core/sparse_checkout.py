"""Monorepo sparse-checkout and lazy HEAD tree inspection (FR-1.16, FR-1.18)."""

from __future__ import annotations

import logging
import re
import stat
from pathlib import Path

import pygit2

from . import write_ops
from .exceptions import GitCommandError, WrenchRepoNotFoundError
from .models import SparseCheckoutState, TreeDirectoryEntry
from .paths import resolve_git_dir
from .security_sanitizer import redact_secrets

logger = logging.getLogger(__name__)

_FORBIDDEN_GLOB_CHARS = frozenset({"*", "?", "[", "]"})
_MAX_SPARSE_FILE_BYTES = 2 * 1024 * 1024
_CONE_INCLUDE_RE = re.compile(r'^/([^\x00*?#"\\]+)/$')
_CONE_EXCLUDE_RE = re.compile(r'^!/([^\x00*?#"\\]+)/\*/$')


def _validate_sparse_dir(rel_dir: str) -> str:
    """Validate and normalize a repository-relative sparse-checkout directory path (SEC-1/SEC-2)."""
    if not isinstance(rel_dir, str):
        raise ValueError("Sparse-checkout directory path must be a string.")
    if "\0" in rel_dir or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel_dir):
        raise ValueError("Sparse-checkout path contains forbidden control characters.")
    if any(ch in rel_dir for ch in _FORBIDDEN_GLOB_CHARS):
        raise ValueError("Sparse-checkout directory path must not contain glob wildcards.")

    normalized = rel_dir.strip().replace("\\", "/")
    if not normalized:
        raise ValueError("Sparse-checkout directory path must not be empty.")
    if normalized.startswith("/"):
        raise ValueError("Sparse-checkout directory path must be repository-relative.")

    clean = normalized.rstrip("/")
    if not clean:
        raise ValueError("Sparse-checkout directory path must not refer to root '/'.")

    parts = clean.split("/")
    for seg in parts:
        if not seg:
            raise ValueError("Sparse-checkout path contains empty '//' segment.")
        if seg in (".", ".."):
            raise ValueError("Sparse-checkout path must not contain '.' or '..' traversal.")
        if seg.startswith("-"):
            raise ValueError("Sparse-checkout path segment must not begin with '-'.")

    return clean


def _open_pygit2_repo(repo_path: Path | str) -> pygit2.Repository:
    try:
        return pygit2.Repository(str(Path(repo_path)))
    except pygit2.GitError as exc:
        raise WrenchRepoNotFoundError(str(exc)) from exc


def _read_bool_config(repo: pygit2.Repository, key: str, default: bool = False) -> bool:
    try:
        return bool(repo.config.get_bool(key))
    except (KeyError, pygit2.GitError, ValueError) as exc:
        logger.debug("Git config bool lookup missed '%s': %s", key, exc)
        return default


def _read_str_config(repo: pygit2.Repository, key: str) -> str | None:
    try:
        return str(repo.config[key])
    except (KeyError, pygit2.GitError, ValueError) as exc:
        logger.debug("Git config string lookup missed '%s': %s", key, exc)
        return None


def _parse_cone_sparse_file(sparse_file: Path, *, cone_mode: bool) -> list[str] | None:
    """Strictly parse simple cone-mode sparse-checkout files; fall back to git CLI otherwise."""
    if not cone_mode:
        return None

    try:
        st = sparse_file.lstat()
    except OSError as exc:
        logger.debug("Unable to stat sparse-checkout file '%s': %s", sparse_file, exc)
        return None

    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        return None
    if st.st_size > _MAX_SPARSE_FILE_BYTES:
        return None

    try:
        raw = sparse_file.read_bytes()
    except OSError as exc:
        logger.debug("Unable to read sparse-checkout file '%s': %s", sparse_file, exc)
        return None

    if b"\0" in raw:
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None

    lines = [ln.rstrip("\r") for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2 or lines[0] != "/*" or lines[1] != "!/*/":
        return None

    includes: list[str] = []
    include_set: set[str] = set()
    excluded_parents: set[str] = set()

    for line in lines[2:]:
        ex_match = _CONE_EXCLUDE_RE.match(line)
        if ex_match is not None:
            parent = ex_match.group(1)
            try:
                clean_parent = _validate_sparse_dir(parent)
            except ValueError:
                return None
            if clean_parent != parent or parent not in include_set or parent in excluded_parents:
                return None
            excluded_parents.add(parent)
            continue

        inc_match = _CONE_INCLUDE_RE.match(line)
        if inc_match is None:
            return None
        inc = inc_match.group(1)
        try:
            clean_inc = _validate_sparse_dir(inc)
        except ValueError:
            return None
        if clean_inc != inc:
            return None
        if inc not in include_set:
            include_set.add(inc)
            includes.append(inc)

    # Every excluded parent container must have at least one selected descendant directory
    for parent in excluded_parents:
        prefix = parent + "/"
        if not any(d.startswith(prefix) and d not in excluded_parents for d in includes):
            return None

    return [d for d in includes if d not in excluded_parents]


def _extract_git_warnings(stderr_text: str) -> str | None:
    """Extract and redact non-fatal git warning lines from stderr (SEC-3)."""
    if not stderr_text:
        return None
    warnings: list[str] = []
    for raw_line in stderr_text.splitlines():
        stripped = raw_line.strip()
        if stripped.lower().startswith("warning:"):
            warnings.append(redact_secrets(stripped))
    if not warnings:
        return None
    joined = " | ".join(warnings)
    if len(joined) > 280:
        return joined[:277] + "..."
    return joined


def is_sparse_checkout_enabled(repo_path: Path | str) -> bool:
    """Return True if sparse-checkout is enabled for the repository or linked worktree."""
    git_dir = resolve_git_dir(repo_path)
    sparse_file = git_dir / "info" / "sparse-checkout"
    if not sparse_file.is_file():
        return False
    r = _open_pygit2_repo(repo_path)
    return _read_bool_config(r, "core.sparsecheckout", default=False)


def get_sparse_checkout_state(repo_path: Path | str) -> SparseCheckoutState:
    """Inspect current sparse-checkout enablement, cone mode, selected dirs, and filter."""
    git_dir = resolve_git_dir(repo_path)
    r = _open_pygit2_repo(repo_path)
    sparse_file = git_dir / "info" / "sparse-checkout"
    enabled = sparse_file.is_file() and _read_bool_config(r, "core.sparsecheckout", default=False)
    cone_mode = _read_bool_config(r, "core.sparsecheckoutcone", default=True) if enabled else True

    partial_filter: str | None = None
    remote_names = [remote.name for remote in r.remotes]
    if "origin" in remote_names:
        remote_names = ["origin"] + [n for n in remote_names if n != "origin"]
    for name in remote_names:
        val = _read_str_config(r, f"remote.{name}.partialclonefilter")
        if val is not None:
            partial_filter = val
            break

    directories = (
        tuple(
            list_sparse_directories(
                repo_path, _repo=r, _sparse_file=sparse_file, _cone_mode=cone_mode
            )
        )
        if enabled
        else ()
    )
    return SparseCheckoutState(
        enabled=enabled,
        cone_mode=cone_mode,
        directories=directories,
        partial_filter=partial_filter,
    )


def init_sparse_checkout(repo_path: Path | str, *, cone: bool = True) -> None:
    """Initialize git sparse-checkout in cone or non-cone mode."""
    p = Path(repo_path)
    resolve_git_dir(p)
    flag = "--cone" if cone else "--no-cone"
    write_ops.run_git(p, ["sparse-checkout", "init", flag], check=True)


def list_sparse_directories(
    repo_path: Path | str,
    *,
    _repo: pygit2.Repository | None = None,
    _sparse_file: Path | None = None,
    _cone_mode: bool | None = None,
) -> list[str]:
    """List currently active sparse-checkout directory patterns cleanly."""
    p = Path(repo_path)
    sparse_file = _sparse_file or (resolve_git_dir(p) / "info" / "sparse-checkout")
    if not sparse_file.is_file():
        return []

    r = _repo or _open_pygit2_repo(p)
    if not _read_bool_config(r, "core.sparsecheckout", default=False):
        return []

    cone_mode = (
        _cone_mode
        if _cone_mode is not None
        else _read_bool_config(r, "core.sparsecheckoutcone", default=True)
    )
    parsed = _parse_cone_sparse_file(sparse_file, cone_mode=cone_mode)
    if parsed is not None:
        return parsed

    res = write_ops.run_git(p, ["--no-optional-locks", "sparse-checkout", "list"], check=False)
    if res.returncode != 0:
        stderr_lower = res.stderr.lower()
        if ".lock" in stderr_lower or "fatal:" in stderr_lower:
            raise GitCommandError(
                ["sparse-checkout", "list"],
                res.returncode,
                res.stderr.strip(),
                stdout=res.stdout.strip(),
            )
        return []

    dirs: list[str] = []
    seen: set[str] = set()
    for raw_line in res.stdout.splitlines():
        item = raw_line.strip().strip("/")
        if item and item not in seen:
            seen.add(item)
            dirs.append(item)
    return dirs


def set_sparse_directories(
    repo_path: Path | str,
    dirs: list[str],
    *,
    cone: bool = True,
    warnings_out: list[str] | None = None,
) -> None:
    """Set sparse-checkout directories safely via validated --stdin input."""
    p = Path(repo_path)
    clean_dirs: list[str] = []
    seen: set[str] = set()
    for d in dirs:
        clean = _validate_sparse_dir(d)
        if clean not in seen:
            seen.add(clean)
            clean_dirs.append(clean)

    if not is_sparse_checkout_enabled(p):
        init_sparse_checkout(p, cone=cone)

    mode_flag = "--cone" if cone else "--no-cone"
    stdin_payload = ("\n".join(clean_dirs) + "\n") if clean_dirs else ""
    res = write_ops.run_git(
        p,
        ["sparse-checkout", "set", mode_flag, "--stdin"],
        input_text=stdin_payload,
        check=True,
    )
    if warnings_out is not None:
        warn = _extract_git_warnings(res.stderr or "")
        if warn:
            warnings_out.append(warn)


def disable_sparse_checkout(
    repo_path: Path | str,
    *,
    warnings_out: list[str] | None = None,
) -> None:
    """Disable sparse-checkout and materialize full working tree."""
    p = Path(repo_path)
    if not is_sparse_checkout_enabled(p):
        return
    res = write_ops.run_git(p, ["sparse-checkout", "disable"], check=True)
    if warnings_out is not None:
        warn = _extract_git_warnings(res.stderr or "")
        if warn:
            warnings_out.append(warn)


def list_tree_subdirectories(
    repo_path: Path | str,
    parent_rel_path: str = "",
) -> list[TreeDirectoryEntry]:
    """List immediate child directories of HEAD (or relative subtree) cleanly."""
    p = Path(repo_path)
    r = _open_pygit2_repo(p)
    if r.head_is_unborn:
        return []

    parent_clean = ""
    if parent_rel_path and parent_rel_path.strip():
        parent_clean = _validate_sparse_dir(parent_rel_path)

    sparse_file = resolve_git_dir(p) / "info" / "sparse-checkout"
    active = (
        set(list_sparse_directories(p, _repo=r, _sparse_file=sparse_file))
        if sparse_file.is_file() and _read_bool_config(r, "core.sparsecheckout", default=False)
        else set()
    )

    try:
        root_tree = r.head.peel(pygit2.Commit).tree
        target_tree: pygit2.Tree = root_tree
        if parent_clean:
            for seg in parent_clean.split("/"):
                if seg not in target_tree:
                    return []
                entry = target_tree[seg]
                if entry.type != pygit2.GIT_OBJECT_TREE:
                    return []
                obj = r[entry.id]
                if not isinstance(obj, pygit2.Tree):
                    return []
                target_tree = obj

        results: list[TreeDirectoryEntry] = []
        for entry in target_tree:
            # Skip blobs, symlinks, and submodule gitlinks (GIT_OBJECT_COMMIT)
            if entry.type != pygit2.GIT_OBJECT_TREE:
                continue
            name = entry.name
            rel_path = f"{parent_clean}/{name}" if parent_clean else name
            has_children = True
            if r.odb.exists(entry.id):
                try:
                    sub_obj = r[entry.id]
                    if isinstance(sub_obj, pygit2.Tree):
                        has_children = any(c.type == pygit2.GIT_OBJECT_TREE for c in sub_obj)
                    else:
                        has_children = False
                except (KeyError, pygit2.GitError) as exc:
                    logger.debug("Lazy child peek fallback for '%s': %s", rel_path, exc)
                    has_children = True

            results.append(
                TreeDirectoryEntry(
                    name=name,
                    rel_path=rel_path,
                    has_children=has_children,
                    is_selected=rel_path in active,
                )
            )

        results.sort(key=lambda item: item.name.lower())
        return results

    except (KeyError, pygit2.GitError) as exc:
        logger.debug(
            "pygit2 tree resolution fallback for '%s' in '%s': %s",
            parent_clean or "HEAD",
            p,
            exc,
        )
        tree_spec = f"HEAD:{parent_clean}" if parent_clean else "HEAD"
        res = write_ops.run_git(p, ["ls-tree", "-d", "--name-only", tree_spec], check=False)
        if res.returncode != 0:
            return []

        fallback_results: list[TreeDirectoryEntry] = []
        for raw_name in res.stdout.splitlines():
            name = raw_name.strip().rstrip("/")
            if not name:
                continue
            rel_path = f"{parent_clean}/{name}" if parent_clean else name
            fallback_results.append(
                TreeDirectoryEntry(
                    name=name,
                    rel_path=rel_path,
                    has_children=True,
                    is_selected=rel_path in active,
                )
            )
        fallback_results.sort(key=lambda item: item.name.lower())
        return fallback_results


def list_head_top_directories(
    repo_path: Path | str,
    max_depth: int = 2,
) -> list[str]:
    """Return top-level directory paths in HEAD up to max_depth levels."""
    if max_depth < 1:
        return []

    p = Path(repo_path)
    r = _open_pygit2_repo(p)
    if r.head_is_unborn:
        return []

    try:
        root_tree = r.head.peel(pygit2.Commit).tree
    except (KeyError, pygit2.GitError) as exc:
        logger.debug("Failed resolving HEAD tree for directory scan in '%s': %s", p, exc)
        return []

    collected: list[str] = []
    queue: list[tuple[pygit2.Tree, str, int]] = [(root_tree, "", 1)]

    while queue:
        tree_obj, prefix, depth = queue.pop(0)
        for entry in tree_obj:
            if entry.type != pygit2.GIT_OBJECT_TREE:
                continue
            rel = f"{prefix}/{entry.name}" if prefix else entry.name
            collected.append(rel)
            if depth < max_depth:
                try:
                    sub = r[entry.id]
                    if isinstance(sub, pygit2.Tree):
                        queue.append((sub, rel, depth + 1))
                except (KeyError, pygit2.GitError) as exc:
                    logger.debug("Skipping un-fetched subtree '%s': %s", rel, exc)

    return sorted(collected, key=str.lower)
