"""FR-8.1-8.5: Git bundle create and restore."""

from pathlib import Path

from .bundles import create_bundle
from .engine import open_repo
from .write_ops import run_git


def create_backup(repo_path: Path, output_path: Path) -> None:
    """Create a git bundle backup of the repository."""
    repo = open_repo(repo_path)
    create_bundle(repo, output_path)


def restore_backup(bundle_path: Path, dest_path: Path) -> None:
    """Restore a repository from a git bundle backup."""
    b_path = Path(bundle_path).resolve()
    d_path = Path(dest_path).resolve()
    d_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(d_path.parent, ["clone", "--", str(b_path), str(d_path)])
