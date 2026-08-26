"""Normalized data models for forge providers."""

from dataclasses import dataclass


@dataclass
class PullRequest:
    id: str
    title: str
    description: str
    source_branch: str
    target_branch: str
    state: str  # 'open' | 'merged' | 'closed'
    url: str
    author: str
    created_at: str  # ISO 8601


@dataclass
class Issue:
    id: str
    title: str
    description: str
    state: str  # 'open' | 'closed'
    url: str
    author: str
    created_at: str


@dataclass
class CIStatus:
    state: str  # 'success' | 'failure' | 'pending' | 'unknown'
    url: str | None
    description: str | None


@dataclass
class ForgeAccount:
    id: int
    provider: str  # 'github' | 'gitlab' | 'forgejo' | 'bitbucket'
    instance_url: str
    label: str
    username: str | None
    secret_service_key: str
