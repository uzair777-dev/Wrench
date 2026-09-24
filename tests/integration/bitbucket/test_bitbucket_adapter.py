"""10-item integration test matrix for BitbucketAdapter."""

from unittest.mock import patch

import httpx
import pytest

from wrench.forge.adapters.bitbucket import BitbucketAdapter
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import ForgeAccount


@pytest.fixture
def bitbucket_account():
    return ForgeAccount(
        id=4,
        provider="bitbucket",
        instance_url="https://api.bitbucket.org/2.0",
        label="Bitbucket Test",
        username="user@example.com",
        secret_service_key="wrench:forge:4",
    )


@pytest.fixture
def bitbucket_adapter(bitbucket_account):
    adapter = BitbucketAdapter(bitbucket_account)
    adapter._cached_token = "atlassian_api_token"
    yield adapter
    adapter.close()


def test_authenticate_success(bitbucket_adapter):
    mock_resp = httpx.Response(
        200,
        json={"username": "testuser"},
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/user"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        bitbucket_adapter.authenticate()


def test_authenticate_missing_username_trap():
    account_no_user = ForgeAccount(
        id=5,
        provider="bitbucket",
        instance_url="https://api.bitbucket.org/2.0",
        label="No User BB",
        username=None,
        secret_service_key="wrench:forge:5",
    )
    adapter = BitbucketAdapter(account_no_user)
    adapter._cached_token = "token"

    with pytest.raises(
        ForgeAuthenticationError, match="requires an Atlassian account email as username"
    ):
        adapter.authenticate()
    adapter.close()


def test_authenticate_auth_error(bitbucket_adapter):
    mock_resp = httpx.Response(
        401,
        json={"type": "error"},
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/user"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeAuthenticationError, match="rejected"):
            bitbucket_adapter.authenticate()


def test_authenticate_insufficient_scope(bitbucket_adapter):
    mock_resp = httpx.Response(
        403,
        json={"type": "error"},
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/user"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeInsufficientScopeError) as exc_info:
            bitbucket_adapter.authenticate()
        assert "pullrequest" in exc_info.value.scope_hint


def test_authenticate_unreachable(bitbucket_adapter):
    with patch.object(
        bitbucket_adapter._client, "request", side_effect=httpx.ConnectError("Timeout")
    ):
        with pytest.raises(ForgeUnreachableError, match="Can't reach"):
            bitbucket_adapter.authenticate()


def test_rate_limiting(bitbucket_adapter):
    mock_resp = httpx.Response(
        429,
        headers={"Retry-After": "60"},
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/user"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError) as exc:
            bitbucket_adapter.authenticate()
        assert exc.value.retry_after_seconds == 60


def test_list_pull_requests_state_mapping(bitbucket_adapter):
    items = [
        {
            "id": 1,
            "title": "Open PR",
            "description": "Desc 1",
            "state": "OPEN",
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/1"}},
            "author": {"display_name": "Alice"},
            "source": {"branch": {"name": "f1"}},
            "destination": {"branch": {"name": "main"}},
            "created_on": "2026-09-23T10:00:00Z",
        },
        {
            "id": 2,
            "title": "Merged PR",
            "description": "Desc 2",
            "state": "MERGED",
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/2"}},
            "author": {"display_name": "Bob"},
            "source": {"branch": {"name": "f2"}},
            "destination": {"branch": {"name": "main"}},
            "created_on": "2026-09-23T11:00:00Z",
        },
        {
            "id": 3,
            "title": "Declined PR",
            "description": "Desc 3",
            "state": "DECLINED",
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/3"}},
            "author": {"display_name": "Carol"},
            "source": {"branch": {"name": "f3"}},
            "destination": {"branch": {"name": "main"}},
            "created_on": "2026-09-23T12:00:00Z",
        },
    ]

    mock_resp = httpx.Response(
        200,
        json={"values": items},
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/pullrequests"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        prs = bitbucket_adapter.list_pull_requests("w", "r", state="all")

    assert len(prs) == 3
    assert prs[0].state == "open"
    assert prs[1].state == "merged"
    assert prs[2].state == "closed"


def test_list_pull_requests_next_url_pagination(bitbucket_adapter):
    page1 = httpx.Response(
        200,
        json={
            "values": [
                {"id": 1, "title": "P1", "source": {}, "destination": {}, "author": {}, "links": {}}
            ],
            "next": "https://api.bitbucket.org/2.0/pullrequests?page=2",
        },
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/pullrequests"),
    )
    page2 = httpx.Response(
        200,
        json={
            "values": [
                {"id": 2, "title": "P2", "source": {}, "destination": {}, "author": {}, "links": {}}
            ]
        },
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/pullrequests?page=2"),
    )

    with patch.object(bitbucket_adapter._client, "request", side_effect=[page1, page2]):
        prs = bitbucket_adapter.list_pull_requests("w", "r")
        assert len(prs) == 2
        assert prs[0].id == "1"
        assert prs[1].id == "2"


def test_create_pull_request_payload(bitbucket_adapter):
    mock_resp = httpx.Response(
        201,
        json={
            "id": 99,
            "title": "BB PR",
            "description": "BB Desc",
            "source": {"branch": {"name": "feat"}},
            "destination": {"branch": {"name": "main"}},
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/99"}},
            "author": {"display_name": "Alice"},
            "created_on": "2026-09-23T12:00:00Z",
        },
        request=httpx.Request("POST", "https://api.bitbucket.org/2.0/pullrequests"),
    )

    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp) as mock_req:
        pr = bitbucket_adapter.create_pull_request(
            "w",
            "r",
            title="BB PR",
            source_branch="feat",
            target_branch="main",
            description="BB Desc",
        )

    assert pr.id == "99"
    assert pr.title == "BB PR"
    _, kwargs = mock_req.call_args
    assert kwargs["json"] == {
        "title": "BB PR",
        "source": {"branch": {"name": "feat"}},
        "destination": {"branch": {"name": "main"}},
        "description": "BB Desc",
    }


def test_get_ci_status_mapping_and_review(bitbucket_adapter):
    resp_ci = httpx.Response(
        200,
        json={
            "values": [
                {"state": "SUCCESSFUL", "url": "https://pipelines.bb.com/1", "description": "Pass"}
            ]
        },
        request=httpx.Request("GET", "https://api.bitbucket.org/commit/statuses"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=resp_ci):
        ci = bitbucket_adapter.get_ci_status("w", "r", "sha777")
        assert ci.state == "success"
        assert ci.url == "https://pipelines.bb.com/1"

    # Submit review approve
    resp_approve = httpx.Response(
        200, json={}, request=httpx.Request("POST", "https://api.bitbucket.org/approve")
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=resp_approve) as mock_req:
        bitbucket_adapter.submit_review("w", "r", 99, action="approve")
        mock_req.assert_called_once()


def test_get_pull_request(bitbucket_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "id": 42,
            "title": "BB PR 42",
            "description": "PR description",
            "state": "MERGED",
            "source": {"branch": {"name": "feature"}},
            "destination": {"branch": {"name": "main"}},
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/42"}},
            "author": {"display_name": "Alice"},
            "created_on": "2026-09-24T10:00:00Z",
        },
        request=httpx.Request(
            "GET", "https://api.bitbucket.org/2.0/repositories/w/r/pullrequests/42"
        ),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        pr = bitbucket_adapter.get_pull_request("w", "r", "42")
        assert pr.id == "42"
        assert pr.title == "BB PR 42"
        assert pr.state == "merged"
        assert pr.source_branch == "feature"
        assert pr.target_branch == "main"
        assert pr.author == "Alice"


def test_get_issue(bitbucket_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "id": 114,
            "title": "BB Issue 114",
            "content": {"raw": "Issue description"},
            "state": "new",
            "links": {"html": {"href": "https://bitbucket.org/w/r/issues/114"}},
            "reporter": {"display_name": "Bob"},
            "created_on": "2026-09-24T10:30:00Z",
        },
        request=httpx.Request("GET", "https://api.bitbucket.org/2.0/repositories/w/r/issues/114"),
    )
    with patch.object(bitbucket_adapter._client, "request", return_value=mock_resp):
        issue = bitbucket_adapter.get_issue("w", "r", "114")
        assert issue.id == "114"
        assert issue.title == "BB Issue 114"
        assert issue.state == "open"
        assert issue.author == "Bob"
        assert issue.description == "Issue description"
