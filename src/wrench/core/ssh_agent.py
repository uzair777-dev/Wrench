"""FR-11.3: Isolates $SSH_AUTH_SOCK access."""

import os


def get_ssh_auth_socket() -> str | None:
    """Linux/BSD: reads $SSH_AUTH_SOCK directly."""
    return os.environ.get("SSH_AUTH_SOCK")


def configure_ssh_env(env: dict[str, str]) -> None:
    """Propagate SSH agent socket to child process environment if configured."""
    sock = get_ssh_auth_socket()
    if sock:
        env["SSH_AUTH_SOCK"] = sock
    else:
        env.pop("SSH_AUTH_SOCK", None)
