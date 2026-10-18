"""FR-1.12: Multi-repository directory discovery.

Walks a picked folder to identify local Git repositories (both standard directories
and .git-file worktrees).

Safety & non-goals:
- Bare repositories are a documented non-goal (no .git marker).
- Symlinks are NEVER followed to guarantee termination on circular links.
- Pruning occurs immediately at repository boundaries, preventing submodule walks.
"""

import os
import threading
from collections.abc import Callable
from pathlib import Path

__lazy_modules__ = ["os", "threading"]


def discover_repos(
    root: Path | str,
    *,
    max_depth: int = 3,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> list[Path]:
    """Scans root up to max_depth levels deep for Git repositories.

    Args:
        root: The starting directory path.
        max_depth: Maximum directory nesting level to traverse (default: 3).
        cancel_event: Optional thread cancellation flag.
        on_progress: Optional callback invoked with the current count of found repos.

    Returns:
        Sorted list of resolved Path objects for every discovered repository.
    """
    root_path = Path(root).resolve()
    if not root_path.exists() or not root_path.is_dir():
        return []

    found: set[Path] = set()
    skipped_errors: list[Exception] = []

    for dirpath, dirnames, _files in os.walk(
        root_path,
        followlinks=False,
        onerror=skipped_errors.append,
    ):
        if cancel_event is not None and cancel_event.is_set():
            break

        current = Path(dirpath)

        # Check for repository marker (.git directory or .git file for worktrees)
        if (current / ".git").exists():
            found.add(current.resolve())
            dirnames[:] = []  # Prune: never descend inside a repository root
            if on_progress:
                on_progress(len(found))
            continue

        # Depth check relative to the scanned root
        depth = len(current.relative_to(root_path).parts)

        # Prune dot-directories, symlinks, and directories beyond max_depth
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and not (current / d).is_symlink() and depth < max_depth
        ]

    return sorted(found)
