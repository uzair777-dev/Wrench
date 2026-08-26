"""FR-1.1/1.5: Git user identity check and configuration."""

from pathlib import Path


def check_identity(repo_path: Path) -> tuple[str, str]:
    raise NotImplementedError


def set_identity(repo_path: Path, name: str, email: str) -> None:
    raise NotImplementedError
