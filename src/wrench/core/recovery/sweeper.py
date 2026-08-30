"""Debris cleaner for abandoned patches, rejects, and temporary workspace artifacts."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

DEBRIS_PATTERNS = ["*.rej", "*.orig", "*.patch"]


def sweep_debris(repo_path: Path | str) -> list[str]:
    """Search and clean up leftover debris files in repository and temp directories.

    Returns:
        List of paths of removed files/directories.
    """
    removed: list[str] = []
    p = Path(repo_path)

    # 1. Search for .rej, .orig, .patch in repository root and immediate subdirs
    if p.exists() and p.is_dir():
        for pattern in DEBRIS_PATTERNS:
            try:
                for match in p.glob(pattern):
                    # Do not delete user files in .git/patches if configured
                    if ".git" not in match.parts:
                        match.unlink(missing_ok=True)
                        removed.append(str(match))
            except Exception as e:
                logger.debug("Error sweeping pattern %s in %s: %s", pattern, p, e)

        # Clean .git/wrench_temp_*
        git_dir = p / ".git" if (p / ".git").is_dir() else p
        if git_dir.exists():
            for temp_dir in git_dir.glob("wrench_temp_*"):
                try:
                    if temp_dir.is_dir():
                        shutil.rmtree(temp_dir, ignore_errors=True)
                    else:
                        temp_dir.unlink(missing_ok=True)
                    removed.append(str(temp_dir))
                except Exception as e:
                    logger.debug("Error cleaning %s: %s", temp_dir, e)

    # 2. Search for orphaned wrench_clone_* directories in system tempdir
    system_temp = Path(tempfile.gettempdir())
    try:
        for temp_match in system_temp.glob("wrench_clone_*"):
            try:
                if temp_match.is_dir():
                    shutil.rmtree(temp_match, ignore_errors=True)
                else:
                    temp_match.unlink(missing_ok=True)
                removed.append(str(temp_match))
            except Exception:
                pass
    except Exception as e:
        logger.debug("Error sweeping system temp directory: %s", e)

    if removed:
        logger.info("Swept %d debris items from repository and temp dir.", len(removed))
    return removed
