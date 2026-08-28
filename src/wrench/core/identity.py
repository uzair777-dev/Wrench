"""FR-1.1/1.5: Git user identity (user.name/user.email) check and configuration.

Checked once when a repo is opened. If either is missing, raises
IdentityRequiredError — caught by the UI to show a two-field dialog.
"""

from pathlib import Path

from .exceptions import IdentityRequiredError
from .write_ops import GitCommandError, run_git


def check_identity(repo_path: Path | str) -> tuple[str, str]:
    """Check that user.name and user.email are configured.

    Returns (name, email) on success.
    Raises IdentityRequiredError listing which fields are missing.
    """
    p = Path(repo_path)
    missing = []

    try:
        name_result = run_git(p, ["config", "--get", "user.name"], check=False)
        name = name_result.stdout.strip()
    except GitCommandError:
        name = ""

    try:
        email_result = run_git(p, ["config", "--get", "user.email"], check=False)
        email = email_result.stdout.strip()
    except GitCommandError:
        email = ""

    if not name:
        missing.append("user.name")
    if not email:
        missing.append("user.email")

    if missing:
        raise IdentityRequiredError(missing)

    return name, email


def set_identity(repo_path: Path | str, name: str, email: str) -> None:
    """Set user.name and user.email at repo-local level (not --global)."""
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError(f"Invalid email address: {email}")

    p = Path(repo_path)
    run_git(p, ["config", "user.name", name])
    run_git(p, ["config", "user.email", email])
