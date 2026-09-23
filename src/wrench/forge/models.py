"""Normalized data models for forge providers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PullRequest:
    """Normalized pull request / merge request representation."""

    id: str  # String representation across all providers (GitHub int, GitLab iid, etc.)
    title: str
    description: str
    source_branch: str
    target_branch: str
    state: str  # Strictly normalized: 'open' | 'merged' | 'closed'
    url: str  # Web URL for browser deep linking
    author: str  # Username / display name
    created_at: str  # ISO 8601 UTC timestamp


@dataclass(frozen=True, slots=True)
class Issue:
    """Normalized issue representation."""

    id: str
    title: str
    description: str
    state: str  # Strictly normalized: 'open' | 'closed'
    url: str
    author: str
    created_at: str


@dataclass(frozen=True, slots=True)
class CIStatus:
    """Normalized commit / pull request CI pipeline status."""

    state: str  # Strictly normalized: 'success' | 'failure' | 'pending' | 'unknown'
    url: str | None = None  # Link to CI dashboard / check run
    description: str | None = None  # Human-readable summary (e.g. "3/3 checks passed")


@dataclass(frozen=True, slots=True)
class RepoMetadata:
    """Normalized repository metadata including mirror detection."""

    owner: str
    repo: str
    default_branch: str
    is_mirror: bool = False
    mirror_source_url: str | None = None
    is_readonly: bool = False
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ForgeAccount:
    """Full account representation including secret key reference.

    SECURITY INVARIANT:
    Constructed solely within background workers to pass to ForgeAdapter constructors.
    Must NEVER be displayed in the UI, logged, or saved to session state.
    """

    id: int
    provider: str  # 'github' | 'gitlab' | 'forgejo' | 'bitbucket'
    instance_url: str  # Base host or self-hosted URL
    label: str  # User-defined label (e.g. "Work GitLab")
    username: str | None
    secret_service_key: str  # 'wrench:forge:{id}'
    tls_ca_bundle_path: str | None = None  # Custom PEM bundle path for self-signed instances
    tls_insecure: bool = False  # True = skip TLS verification
