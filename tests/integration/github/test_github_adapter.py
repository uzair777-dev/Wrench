"""10-item integration test matrix for GitHubAdapter."""

from unittest.mock import patch

import httpx
import pytest

from wrench.forge.adapters.github import GitHubAdapter
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import ForgeAccount


@pytest.fixture
def github_account():
    return ForgeAccount(
        id=1,
        provider="github",
        instance_url="https://github.com",
        label="GitHub Test",
        username="testuser",
        secret_service_key="wrench:forge:1",
    )


@pytest.fixture
def github_adapter(github_account):
    adapter = GitHubAdapter(github_account)
    adapter._cached_token = "ghp_validtesttoken123"
    yield adapter
    adapter.close()


def test_authenticate_success(github_adapter):
    mock_resp = httpx.Response(
        200, json={"login": "testuser"}, request=httpx.Request("GET", "https://api.github.com/user")
    )
    with patch.object(github_adapter._client, "request", return_value=mock_resp):
        github_adapter.authenticate()


def test_authenticate_auth_error(github_adapter):
    mock_resp = httpx.Response(
        401,
        json={"message": "Bad credentials"},
        request=httpx.Request("GET", "https://api.github.com/user"),
    )
    with patch.object(github_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeAuthenticationError, match="rejected"):
            github_adapter.authenticate()


def test_authenticate_insufficient_scope(github_adapter):
    mock_resp = httpx.Response(
        403,
        json={"message": "Resource not accessible by personal access token"},
        request=httpx.Request("GET", "https://api.github.com/user"),
    )
    with patch.object(github_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeInsufficientScopeError) as exc_info:
            github_adapter.authenticate()
        assert "repo" in exc_info.value.scope_hint


def test_authenticate_unreachable(github_adapter):
    with patch.object(
        github_adapter._client, "request", side_effect=httpx.ConnectError("DNS failed")
    ):
        with pytest.raises(ForgeUnreachableError, match="Can't reach https://github.com"):
            github_adapter.authenticate()


def test_rate_limiting(github_adapter):
    mock_resp = httpx.Response(
        429,
        headers={"Retry-After": "120"},
        request=httpx.Request("GET", "https://api.github.com/user"),
    )
    with patch.object(github_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError) as exc:
            github_adapter.authenticate()
        assert exc.value.retry_after_seconds == 120


def test_list_pull_requests_state_mapping(github_adapter):
    items = [
        {
            "number": 1,
            "title": "Open PR",
            "body": "Description 1",
            "state": "open",
            "merged_at": None,
            "html_url": "https://github.com/org/repo/pull/1",
            "user": {"login": "alice"},
            "head": {"ref": "feat-1"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T10:00:00Z",
        },
        {
            "number": 2,
            "title": "Merged PR",
            "body": "Description 2",
            "state": "closed",
            "merged_at": "2026-09-23T11:00:00Z",
            "html_url": "https://github.com/org/repo/pull/2",
            "user": {"login": "bob"},
            "head": {"ref": "feat-2"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T09:00:00Z",
        },
        {
            "number": 3,
            "title": "Closed Unmerged PR",
            "body": "Description 3",
            "state": "closed",
            "merged_at": None,
            "html_url": "https://github.com/org/repo/pull/3",
            "user": {"login": "carol"},
            "head": {"ref": "feat-3"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T08:00:00Z",
        },
    ]

    mock_resp = httpx.Response(
        200, json=items, request=httpx.Request("GET", "https://api.github.com/repos/org/repo/pulls")
    )
    with patch.object(github_adapter._client, "request", return_value=mock_resp):
        prs = github_adapter.list_pull_requests("org", "repo", state="all")

    assert len(prs) == 3
    assert prs[0].state == "open"
    assert prs[1].state == "merged"
    assert prs[2].state == "closed"


def test_list_pull_requests_pagination_and_cap(github_adapter):
    page1 = httpx.Response(
        200,
        json=[{"number": 1, "title": "P1", "head": {}, "base": {}, "user": {}}],
        headers={"link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'},
        request=httpx.Request("GET", "https://api.github.com/repos/o/r/pulls"),
    )
    page2 = httpx.Response(
        200,
        json=[{"number": 2, "title": "P2", "head": {}, "base": {}, "user": {}}],
        request=httpx.Request("GET", "https://api.github.com/repos/o/r/pulls?page=2"),
    )

    with patch.object(github_adapter._client, "request", side_effect=[page1, page2]):
        prs = github_adapter.list_pull_requests("o", "r")
        assert len(prs) == 2
        assert prs[0].id == "1"
        assert prs[1].id == "2"


def test_create_pull_request_payload(github_adapter):
    mock_resp = httpx.Response(
        201,
        json={
            "number": 42,
            "title": "New feature",
            "body": "PR description",
            "head": {"ref": "feat"},
            "base": {"ref": "main"},
            "html_url": "https://github.com/org/repo/pull/42",
            "user": {"login": "alice"},
            "created_at": "2026-09-23T12:00:00Z",
        },
        request=httpx.Request("POST", "https://api.github.com/repos/org/repo/pulls"),
    )

    with patch.object(github_adapter._client, "request", return_value=mock_resp) as mock_req:
        pr = github_adapter.create_pull_request(
            "org",
            "repo",
            title="New feature",
            source_branch="feat",
            target_branch="main",
            description="PR description",
        )

    assert pr.id == "42"
    assert pr.title == "New feature"
    mock_req.assert_called_once()
    _, kwargs = mock_req.call_args
    assert kwargs["json"] == {
        "title": "New feature",
        "head": "feat",
        "base": "main",
        "body": "PR description",
    }


def test_get_ci_status_mapping(github_adapter):
    # Combined status success
    resp_success = httpx.Response(
        200,
        json={
            "state": "success",
            "total_count": 1,
            "statuses": [{"target_url": "https://ci.run/1", "description": "Build passed"}],
        },
        request=httpx.Request("GET", "https://api.github.com/status"),
    )
    with patch.object(github_adapter._client, "request", return_value=resp_success):
        ci = github_adapter.get_ci_status("org", "repo", "sha123")
        assert ci.state == "success"
        assert ci.url == "https://ci.run/1"
        assert ci.description == "Build passed"

    # Empty statuses and 404 check-runs -> unknown
    resp_empty = httpx.Response(
        200,
        json={"state": "pending", "total_count": 0, "statuses": []},
        request=httpx.Request("GET", "https://api.github.com/status"),
    )
    resp_404 = httpx.Response(
        404, request=httpx.Request("GET", "https://api.github.com/check-runs")
    )
    with patch.object(github_adapter._client, "request", side_effect=[resp_empty, resp_404]):
        ci_unknown = github_adapter.get_ci_status("org", "repo", "sha456")
        assert ci_unknown.state == "unknown"


def test_submit_review_actions_and_issue_trap(github_adapter):
    # Test review action APPROVE
    resp_rev = httpx.Response(
        200, json={}, request=httpx.Request("POST", "https://api.github.com/reviews")
    )
    with patch.object(github_adapter._client, "request", return_value=resp_rev) as mock_req:
        github_adapter.submit_review("org", "repo", 10, action="approve", body="LGTM")
        _, kwargs = mock_req.call_args
        assert kwargs["json"] == {"event": "APPROVE", "body": "LGTM"}

    # Test /issues endpoint filtering out PRs!
    raw_issues = [
        {"number": 100, "title": "Real issue", "state": "open", "user": {"login": "user1"}},
        {
            "number": 101,
            "title": "PR masquerading as issue",
            "state": "open",
            "pull_request": {"url": "https://..."},
            "user": {"login": "user2"},
        },
    ]
    resp_issues = httpx.Response(
        200, json=raw_issues, request=httpx.Request("GET", "https://api.github.com/issues")
    )
    with patch.object(github_adapter._client, "request", return_value=resp_issues):
        issues = github_adapter.list_issues("org", "repo")
        assert len(issues) == 1
        assert issues[0].id == "100"
        assert issues[0].title == "Real issue"
