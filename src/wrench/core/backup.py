"""FR-8.1-8.5: Git bundle create and restore."""

from pathlib import Path


def create_backup(repo_path: Path, output_path: Path) -> None:
    """Create a git bundle backup of the repository."""
    raise NotImplementedError


def restore_backup(bundle_path: Path, dest_path: Path) -> None:
    """Restore a repository from a git bundle backup."""
    raise NotImplementedError
