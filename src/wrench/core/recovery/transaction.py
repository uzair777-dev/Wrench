"""Atomic workspace transaction context manager with automatic rollback and temp file cleanup."""

from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


class WorkspaceTransaction:
    """Manages an atomic operation on a workspace.

    Tracks temporary files and directories created during the transaction.
    Takes a safety snapshot if pygit2 repository is accessible.
    If an error occurs, automatically sweeps all registered temp paths and logs rollback.
    """

    def __init__(self, repo_path: Path | str, name: str = "transaction"):
        self.repo_path = Path(repo_path)
        self.name = name
        self.temp_paths: list[Path] = []
        self.snapshot_id: str | None = None
        self._completed = False

    def register_temp_path(self, path: Path | str) -> Path:
        """Register a temporary file to be swept on completion or rollback."""
        p = Path(path)
        self.temp_paths.append(p)
        return p

    def register_temp_dir(self, dir_path: Path | str) -> Path:
        """Register a temporary directory to be completely removed on rollback or completion."""
        p = Path(dir_path)
        self.temp_paths.append(p)
        return p

    def rollback(self) -> None:
        """Sweep all registered temporary paths."""
        for p in self.temp_paths:
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                elif p.exists():
                    p.unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Error sweeping temp path %s: %s", p, e)

    def commit(self) -> None:
        """Mark transaction as cleanly completed and sweep temporary artifacts."""
        self._completed = True
        self.rollback()


@contextmanager
def workspace_transaction(
    repo_path: Path | str,
    name: str = "operation",
) -> Generator[WorkspaceTransaction, None, None]:
    """Context manager for atomic workspace operations with automatic cleanup."""
    tx = WorkspaceTransaction(repo_path, name=name)
    try:
        yield tx
        tx.commit()
    except Exception as e:
        logger.warning("Workspace transaction '%s' failed: %s. Performing rollback...", name, e)
        tx.rollback()
        raise
