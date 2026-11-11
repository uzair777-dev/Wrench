"""Security sanitization utilities for clone URLs, refs, and CLI secret redaction (SEC-2, SEC-3)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_ALLOWED_URL_SCHEMES = frozenset({"https", "http", "ssh", "git", "file"})
_FORBIDDEN_TRANSPORT_PREFIXES = (
    "ext::",
    "fd::",
    "javascript:",
    "data:",
    "vbscript:",
)
_REMOTE_HELPER_PREFIX_RE = re.compile(r"^[A-Za-z0-9+.-]+::")
_SCP_STYLE_RE = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:[^\s].*$")

_TOKEN_PATTERNS = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{6,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{6,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{6,}\b"),
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-+/=]{4,}")
_URL_USER_PASS_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*://)([^:/\s@]+):([^@\s]+)@")
_URL_TOKEN_USER_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9+.-]*://)(?:x-access-token|oauth2|[A-Za-z0-9_-]{20,})@"
)


def validate_clone_url(url: str) -> str:
    """Validate repository clone URLs/paths against flag and transport injection (SEC-2)."""
    if not isinstance(url, str):
        raise ValueError("Clone URL must be a string.")

    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Clone URL must not be empty.")

    if "\0" in cleaned or "\r" in cleaned or "\n" in cleaned:
        raise ValueError("Clone URL contains forbidden control characters.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("Clone URL contains invalid ASCII control characters.")
    if cleaned.startswith("-"):
        raise ValueError("Clone URL must not begin with '-' (CLI option injection rejected).")

    lower = cleaned.lower()
    for prefix in _FORBIDDEN_TRANSPORT_PREFIXES:
        if lower.startswith(prefix):
            raise ValueError(f"Unsafe clone transport scheme rejected: {prefix}")

    if _REMOTE_HELPER_PREFIX_RE.match(cleaned):
        raise ValueError("Arbitrary git remote-helper '::' transport syntax is rejected.")

    if "://" in cleaned:
        parsed = urlsplit(cleaned)
        scheme = parsed.scheme.lower()
        if scheme not in _ALLOWED_URL_SCHEMES:
            raise ValueError(f"Unsupported clone URL scheme '{scheme}'.")
        if scheme != "file" and not parsed.netloc:
            raise ValueError(f"Clone URL with scheme '{scheme}' must include a host.")
        if scheme == "file" and not (parsed.path or parsed.netloc):
            raise ValueError("file:// clone URL must include a repository path.")
        return cleaned

    if "@" in cleaned and ":" in cleaned and not cleaned.startswith(("/", "./", "../", "~")):
        if not _SCP_STYLE_RE.match(cleaned):
            raise ValueError("Malformed SSH SCP-style repository location.")
        host_part = cleaned.split(":", 1)[0].split("@", 1)[1]
        if host_part.startswith("-"):
            raise ValueError("SSH hostname must not begin with '-'.")
        return cleaned

    return cleaned


def validate_git_ref(ref: str) -> str:
    """Validate branch/tag ref name before passing to CLI flags like --branch."""
    if not isinstance(ref, str):
        raise ValueError("Git ref must be a string.")
    cleaned = ref.strip()
    if not cleaned:
        raise ValueError("Git ref must not be empty.")
    if "\0" in cleaned or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        raise ValueError("Git ref contains invalid control characters.")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("Git ref must not contain whitespace.")
    if cleaned.startswith("-") or cleaned.startswith("/") or cleaned.endswith("/"):
        raise ValueError("Invalid git ref syntax.")
    if ".." in cleaned or "//" in cleaned or "@{" in cleaned:
        raise ValueError("Git ref contains forbidden sequence.")
    if any(ch in cleaned for ch in ("~", "^", ":", "\\", "*", "?", "[")):
        raise ValueError("Git ref contains forbidden special characters.")
    if cleaned.endswith(".") or cleaned.endswith(".lock"):
        raise ValueError("Invalid git ref suffix.")
    return cleaned


def redact_secrets(text: str) -> str:
    """Scrub tokens, Bearer headers, and embedded URL credentials from UI/log text (SEC-3)."""
    if not text:
        return text
    redacted = _URL_USER_PASS_RE.sub(r"\1***:***@", text)
    redacted = _URL_TOKEN_USER_RE.sub(r"\1***@", redacted)
    redacted = _BEARER_RE.sub("Bearer ***", redacted)
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub("***", redacted)
    return redacted
