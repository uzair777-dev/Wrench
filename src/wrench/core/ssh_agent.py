"""FR-11.3: Isolates $SSH_AUTH_SOCK access."""

import os


def get_ssh_auth_socket() -> str | None:
    """Linux/BSD: reads $SSH_AUTH_SOCK directly."""
    return os.environ.get("SSH_AUTH_SOCK")
