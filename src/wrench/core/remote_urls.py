"""Shared Git remote URL parser for credential helper and UI account linking."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class RemoteUrlParts:
    """Parsed components of a Git remote URL."""

    protocol: str  # 'https', 'http', 'ssh', 'git', 'file'
    host: str  # lowercased, port stripped
    owner: str  # e.g. 'torvalds' or 'group/subgroup'
    repo: str  # e.g. 'linux', trailing .git stripped


def parse_remote_url(url: str) -> RemoteUrlParts | None:
    """Extract protocol, host, owner, and repo from any standard Git remote URL.

    Returns None only when even the host can't be determined — never raises.
    An unparseable URL is a normal outcome (git's own error handles it downstream).

    Supported patterns:
      - HTTPS/HTTP: https://github.com/owner/repo.git
      - SSH SCP-like: git@gitlab.com:grp/sub/proj.git
      - SSH URL: ssh://git@forge.io:2222/org/repo.git
      - file:// and bare local paths (protocol='file', host/owner/repo from path tail)
    """
    clean_url = url.strip()
    if not clean_url:
        return None

    # Strip trailing .git and /
    def _strip_suffix(s: str) -> str:
        if s.endswith(".git"):
            s = s[:-4]
        return s.rstrip("/")

    # --- file:// scheme ---
    if clean_url.startswith("file://"):
        path = clean_url[7:].lstrip("/")
        path = _strip_suffix(path)
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and parts[0] and parts[1]:
            # Try to extract owner/repo from path
            owner_parts = parts[0].rsplit("/", 1)
            repo = parts[1]
            owner = owner_parts[-1] if owner_parts else ""
            return RemoteUrlParts(protocol="file", host="", owner=owner, repo=repo)
        elif parts and parts[-1]:
            return RemoteUrlParts(protocol="file", host="", owner="", repo=parts[-1])
        return None

    # --- SSH SCP-like: [user@]host:owner/repo (never contains ://) ---
    if "://" not in clean_url:
        scp_match = re.match(r"^(?:[\w.-]+@)?([^:/]+):([^/].+)$", clean_url)
        if scp_match:
            host = scp_match.group(1).lower()
            path = _strip_suffix(scp_match.group(2).strip("/"))
            parts = path.rsplit("/", 1)
            if len(parts) == 2 and host:
                return RemoteUrlParts(protocol="ssh", host=host, owner=parts[0], repo=parts[1])
            elif host:
                return RemoteUrlParts(protocol="ssh", host=host, owner="", repo=path)

        # Bare local path
        path = _strip_suffix(clean_url)
        parts = path.rsplit("/", 1)
        if parts and parts[-1]:
            return RemoteUrlParts(protocol="file", host="", owner="", repo=parts[-1])
        return None

    # --- Standard URL: scheme://[user@]host[:port]/path ---
    url_match = re.match(
        r"^(https?|ssh|git)://(?:[^@]+@)?([^:/]+)(?::\d+)?/(.+)$",
        clean_url,
        re.IGNORECASE,
    )
    if url_match:
        protocol = url_match.group(1).lower()
        host = url_match.group(2).lower()
        path = _strip_suffix(url_match.group(3).strip("/"))
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and host:
            return RemoteUrlParts(protocol=protocol, host=host, owner=parts[0], repo=parts[1])
        elif host:
            return RemoteUrlParts(protocol=protocol, host=host, owner="", repo=path)

    return None


def host_of_instance_url(instance_url: str) -> str:
    """Extract normalized host from an instance URL (lowercase, port stripped).

    Moved from git_credential_helper._host_of — identical semantics.
    """
    try:
        parsed = urlsplit(instance_url)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    # Fallback for plain host:port or scp-style user@host:path
    raw = (
        instance_url.replace("https://", "")
        .replace("http://", "")
        .replace("ssh://", "")
        .split("/")[0]
    )
    host_part = raw.split(":")[0].lower()
    if "@" in host_part:
        host_part = host_part.split("@")[-1]
    return host_part
