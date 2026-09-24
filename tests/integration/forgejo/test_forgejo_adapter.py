"""10-item integration test matrix for ForgejoAdapter."""

from unittest.mock import patch

import httpx
import pytest

from wrench.forge.adapters.forgejo import ForgejoAdapter
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import ForgeAccount


@pytest.fixture
def forgejo_account():
    return ForgeAccount(
        id=3,
        provider="forgejo",
        instance_url="https://forgejo.example.com",
        label="Forgejo Test",
        username="testuser",
        secret_service_key="wrench:forge:3",
    )


@pytest.fixture
def forgejo_adapter(forgejo_account):
    adapter = ForgejoAdapter(forgejo_account)
    adapter._cached_token = "token_forgejo_123"
    yield adapter
    adapter.close()


def test_authenticate_success(forgejo_adapter):
    mock_resp = httpx.Response(
        200,
        json={"username": "testuser"},
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/user"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        forgejo_adapter.authenticate()


def test_authenticate_auth_error(forgejo_adapter):
    mock_resp = httpx.Response(
        401,
        json={"message": "Unauthorized"},
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/user"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeAuthenticationError, match="rejected"):
            forgejo_adapter.authenticate()


def test_authenticate_insufficient_scope(forgejo_adapter):
    mock_resp = httpx.Response(
        403,
        json={"message": "Forbidden"},
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/user"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeInsufficientScopeError) as exc_info:
            forgejo_adapter.authenticate()
        assert "repo" in exc_info.value.scope_hint


def test_authenticate_unreachable(forgejo_adapter):
    with patch.object(
        forgejo_adapter._client, "request", side_effect=httpx.ConnectError("Unreachable")
    ):
        with pytest.raises(ForgeUnreachableError, match="Can't reach https://forgejo.example.com"):
            forgejo_adapter.authenticate()


def test_rate_limiting(forgejo_adapter):
    mock_resp = httpx.Response(
        429,
        headers={"Retry-After": "30"},
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/user"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError) as exc:
            forgejo_adapter.authenticate()
        assert exc.value.retry_after_seconds == 30


def test_list_pull_requests_state_mapping(forgejo_adapter):
    items = [
        {
            "number": 1,
            "title": "Open PR",
            "body": "Desc 1",
            "state": "open",
            "merged": False,
            "html_url": "https://forgejo.example.com/o/r/pulls/1",
            "user": {"login": "alice"},
            "head": {"ref": "f1"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T10:00:00Z",
        },
        {
            "number": 2,
            "title": "Merged PR",
            "body": "Desc 2",
            "state": "closed",
            "merged": True,
            "html_url": "https://forgejo.example.com/o/r/pulls/2",
            "user": {"login": "bob"},
            "head": {"ref": "f2"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T11:00:00Z",
        },
        {
            "number": 3,
            "title": "Closed PR",
            "body": "Desc 3",
            "state": "closed",
            "merged": False,
            "html_url": "https://forgejo.example.com/o/r/pulls/3",
            "user": {"login": "carol"},
            "head": {"ref": "f3"},
            "base": {"ref": "main"},
            "created_at": "2026-09-23T12:00:00Z",
        },
    ]

    mock_resp = httpx.Response(
        200,
        json=items,
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/repos/o/r/pulls"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        prs = forgejo_adapter.list_pull_requests("o", "r", state="all")

    assert len(prs) == 3
    assert prs[0].state == "open"
    assert prs[1].state == "merged"
    assert prs[2].state == "closed"


def test_list_pull_requests_pagination_and_cap(forgejo_adapter):
    page1 = httpx.Response(
        200,
        json=[
            {"number": i, "title": f"PR {i}", "head": {}, "base": {}, "user": {}} for i in range(50)
        ],
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/repos/o/r/pulls"),
    )
    page2 = httpx.Response(
        200,
        json=[{"number": 51, "title": "PR 51", "head": {}, "base": {}, "user": {}}],
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/repos/o/r/pulls?page=2"),
    )

    with patch.object(forgejo_adapter._client, "request", side_effect=[page1, page2]):
        prs = forgejo_adapter.list_pull_requests("o", "r")
        assert len(prs) == 51


def test_create_pull_request_payload(forgejo_adapter):
    mock_resp = httpx.Response(
        201,
        json={
            "number": 88,
            "title": "Forgejo PR",
            "body": "Body text",
            "head": {"ref": "patch-1"},
            "base": {"ref": "main"},
            "html_url": "https://forgejo.example.com/o/r/pulls/88",
            "user": {"login": "alice"},
            "created_at": "2026-09-23T12:00:00Z",
        },
        request=httpx.Request("POST", "https://forgejo.example.com/api/v1/repos/o/r/pulls"),
    )

    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp) as mock_req:
        pr = forgejo_adapter.create_pull_request(
            "o",
            "r",
            title="Forgejo PR",
            source_branch="patch-1",
            target_branch="main",
            description="Body text",
        )

    assert pr.id == "88"
    assert pr.title == "Forgejo PR"
    _, kwargs = mock_req.call_args
    assert kwargs["json"] == {
        "title": "Forgejo PR",
        "head": "patch-1",
        "base": "main",
        "body": "Body text",
    }


def test_get_ci_status_mapping(forgejo_adapter):
    resp_success = httpx.Response(
        200,
        json={
            "state": "success",
            "statuses": [
                {"target_url": "https://drone.example.com/1", "description": "Drone CI passed"}
            ],
        },
        request=httpx.Request("GET", "https://forgejo.example.com/status"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=resp_success):
        ci = forgejo_adapter.get_ci_status("o", "r", "sha999")
        assert ci.state == "success"
        assert ci.url == "https://drone.example.com/1"
        assert ci.description == "Drone CI passed"


def test_submit_review_action_approved_trap(forgejo_adapter):
    resp_rev = httpx.Response(
        200, json={}, request=httpx.Request("POST", "https://forgejo.example.com/reviews")
    )
    with patch.object(forgejo_adapter._client, "request", return_value=resp_rev) as mock_req:
        # CRITICAL TRAP: Must map 'approve' to past-tense 'APPROVED'!
        forgejo_adapter.submit_review("o", "r", 5, action="approve", body="Good to go")
        _, kwargs = mock_req.call_args
        assert kwargs["json"] == {"event": "APPROVED", "body": "Good to go"}


def test_get_pull_request(forgejo_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "number": 42,
            "title": "Forgejo PR 42",
            "body": "PR description",
            "state": "closed",
            "merged_at": "2026-09-24T10:00:00Z",
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
            "html_url": "https://forgejo.example.com/o/r/pulls/42",
            "user": {"login": "alice"},
            "created_at": "2026-09-24T10:00:00Z",
        },
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/repos/o/r/pulls/42"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        pr = forgejo_adapter.get_pull_request("o", "r", "42")
        assert pr.id == "42"
        assert pr.title == "Forgejo PR 42"
        assert pr.state == "merged"
        assert pr.source_branch == "feature"
        assert pr.target_branch == "main"
        assert pr.author == "alice"


def test_get_issue(forgejo_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "number": 114,
            "title": "Forgejo Issue 114",
            "body": "Issue description",
            "state": "open",
            "html_url": "https://forgejo.example.com/o/r/issues/114",
            "user": {"login": "bob"},
            "created_at": "2026-09-24T10:30:00Z",
        },
        request=httpx.Request("GET", "https://forgejo.example.com/api/v1/repos/o/r/issues/114"),
    )
    with patch.object(forgejo_adapter._client, "request", return_value=mock_resp):
        issue = forgejo_adapter.get_issue("o", "r", "114")
        assert issue.id == "114"
        assert issue.title == "Forgejo Issue 114"
        assert issue.state == "open"
        assert issue.author == "bob"
        assert issue.description == "Issue description"
