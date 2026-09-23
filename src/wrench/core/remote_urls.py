"""Shared Git remote URL parser for credential helper and UI account linking."""

import re


def parse_remote_url(url: str) -> tuple[str, str, str]:
    """Extract (host, owner_slug, repo_slug) from any standard Git remote URL.

    Supported patterns:
      - HTTPS: https://github.com/owner/repo.git -> ('github.com', 'owner', 'repo')
      - SSH SCP-like: git@gitlab.com:grp/sub/proj.git -> ('gitlab.com', 'grp/sub', 'proj')
      - SSH URL: ssh://git@forge.io:2222/org/repo.git -> ('forge.io', 'org', 'repo')
    """
    clean_url = url.strip()
    if clean_url.endswith(".git"):
        clean_url = clean_url[:-4]

    # SSH SCP-like: [user@]host:owner/repo (never contains ://)
    if "://" not in clean_url:
        scp_match = re.match(r"^(?:[\w.-]+@)?([^:/]+):([^/].+)$", clean_url)
        if scp_match:
            host = scp_match.group(1).lower()
            path = scp_match.group(2).strip("/")
            parts = path.rsplit("/", 1)
            if len(parts) == 2:
                return host, parts[0], parts[1]

    # Standard URL: scheme://[user@]host[:port]/path
    url_match = re.match(
        r"^(https?|ssh|git)://(?:[^@]+@)?([^:/]+)(?::\d+)?/(.+)$", clean_url, re.IGNORECASE
    )
    if url_match:
        host = url_match.group(2).lower()
        path = url_match.group(3).strip("/")
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and host:
            return host, parts[0], parts[1]

    raise ValueError(f"Cannot parse Git remote URL: {url!r}")
