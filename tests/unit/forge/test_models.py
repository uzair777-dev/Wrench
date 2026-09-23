"""Unit tests for forge normalized data models."""

from dataclasses import FrozenInstanceError

import pytest

from wrench.forge.models import CIStatus, ForgeAccount, Issue, PullRequest, RepoMetadata


def test_pull_request_model():
    pr = PullRequest(
        id="123",
        title="Add feature",
        description="A great feature",
        source_branch="feat/awesome",
        target_branch="main",
        state="open",
        url="https://github.com/org/repo/pull/123",
        author="alice",
        created_at="2026-09-23T12:00:00Z",
    )
    assert pr.id == "123"
    assert pr.state == "open"
    assert hasattr(pr, "__slots__")
    assert not hasattr(pr, "__dict__")

    with pytest.raises(FrozenInstanceError):
        pr.title = "New Title"  # type: ignore[misc]


def test_issue_model():
    issue = Issue(
        id="456",
        title="Fix bug",
        description="Bug details",
        state="closed",
        url="https://gitlab.com/org/repo/issues/456",
        author="bob",
        created_at="2026-09-23T12:00:00Z",
    )
    assert issue.id == "456"
    assert issue.state == "closed"
    assert hasattr(issue, "__slots__")
    assert not hasattr(issue, "__dict__")

    with pytest.raises(FrozenInstanceError):
        issue.state = "open"  # type: ignore[misc]


def test_ci_status_model():
    ci = CIStatus(state="success", url="https://ci.example.com/1", description="Checks passed")
    assert ci.state == "success"
    assert ci.url == "https://ci.example.com/1"
    assert ci.description == "Checks passed"

    # Default unknown status
    ci_default = CIStatus(state="unknown")
    assert ci_default.url is None
    assert ci_default.description is None
    assert hasattr(ci, "__slots__")
    assert not hasattr(ci, "__dict__")

    with pytest.raises(FrozenInstanceError):
        ci.state = "failure"  # type: ignore[misc]


def test_repo_metadata_model():
    repo = RepoMetadata(
        owner="org",
        repo="repo",
        default_branch="main",
        is_mirror=True,
        mirror_source_url="https://github.com/upstream/repo",
        is_readonly=True,
        description="Mirrored repo",
    )
    assert repo.owner == "org"
    assert repo.is_mirror is True
    assert repo.mirror_source_url == "https://github.com/upstream/repo"
    assert repo.is_readonly is True
    assert hasattr(repo, "__slots__")
    assert not hasattr(repo, "__dict__")

    with pytest.raises(FrozenInstanceError):
        repo.is_mirror = False  # type: ignore[misc]


def test_forge_account_model():
    acc = ForgeAccount(
        id=1,
        provider="gitlab",
        instance_url="https://gitlab.com",
        label="Work GitLab",
        username="alice",
        secret_service_key="wrench:forge:1",
        tls_ca_bundle_path="/etc/ssl/custom.pem",
        tls_insecure=False,
    )
    assert acc.id == 1
    assert acc.provider == "gitlab"
    assert acc.tls_ca_bundle_path == "/etc/ssl/custom.pem"
    assert acc.tls_insecure is False
    assert hasattr(acc, "__slots__")
    assert not hasattr(acc, "__dict__")

    with pytest.raises(FrozenInstanceError):
        acc.label = "Other"  # type: ignore[misc]
