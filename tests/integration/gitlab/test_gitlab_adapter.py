"""10-item integration test matrix for GitLabAdapter."""

from unittest.mock import patch

import httpx
import pytest

from wrench.forge.adapters.gitlab import GitLabAdapter
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import ForgeAccount


@pytest.fixture
def gitlab_account():
    return ForgeAccount(
        id=2,
        provider="gitlab",
        instance_url="https://gitlab.com",
        label="GitLab Test",
        username="testuser",
        secret_service_key="wrench:forge:2",
    )


@pytest.fixture
def gitlab_adapter(gitlab_account):
    adapter = GitLabAdapter(gitlab_account)
    adapter._cached_token = "glpat_testtoken123"
    yield adapter
    adapter.close()


def test_authenticate_success(gitlab_adapter):
    mock_resp = httpx.Response(
        200,
        json={"username": "testuser"},
        request=httpx.Request("GET", "https://gitlab.com/api/v4/user"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        gitlab_adapter.authenticate()


def test_authenticate_auth_error(gitlab_adapter):
    mock_resp = httpx.Response(
        401,
        json={"message": "401 Unauthorized"},
        request=httpx.Request("GET", "https://gitlab.com/api/v4/user"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeAuthenticationError, match="rejected"):
            gitlab_adapter.authenticate()


def test_authenticate_insufficient_scope(gitlab_adapter):
    mock_resp = httpx.Response(
        403,
        json={"message": "403 Forbidden"},
        request=httpx.Request("GET", "https://gitlab.com/api/v4/user"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeInsufficientScopeError) as exc_info:
            gitlab_adapter.authenticate()
        assert "read_api" in exc_info.value.scope_hint


def test_authenticate_unreachable(gitlab_adapter):
    with patch.object(
        gitlab_adapter._client, "request", side_effect=httpx.ConnectError("Network down")
    ):
        with pytest.raises(ForgeUnreachableError, match="Can't reach https://gitlab.com"):
            gitlab_adapter.authenticate()


def test_rate_limiting(gitlab_adapter):
    mock_resp = httpx.Response(
        429,
        headers={"Retry-After": "90"},
        request=httpx.Request("GET", "https://gitlab.com/api/v4/user"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError) as exc:
            gitlab_adapter.authenticate()
        assert exc.value.retry_after_seconds == 90


def test_list_pull_requests_state_mapping(gitlab_adapter):
    items = [
        {
            "iid": 10,
            "title": "Opened MR",
            "description": "Details 1",
            "state": "opened",
            "web_url": "https://gitlab.com/group/proj/-/merge_requests/10",
            "author": {"username": "alice"},
            "source_branch": "feat-1",
            "target_branch": "main",
            "created_at": "2026-09-23T10:00:00Z",
        },
        {
            "iid": 11,
            "title": "Merged MR",
            "description": "Details 2",
            "state": "merged",
            "web_url": "https://gitlab.com/group/proj/-/merge_requests/11",
            "author": {"username": "bob"},
            "source_branch": "feat-2",
            "target_branch": "main",
            "created_at": "2026-09-23T11:00:00Z",
        },
        {
            "iid": 12,
            "title": "Closed MR",
            "description": "Details 3",
            "state": "closed",
            "web_url": "https://gitlab.com/group/proj/-/merge_requests/12",
            "author": {"username": "carol"},
            "source_branch": "feat-3",
            "target_branch": "main",
            "created_at": "2026-09-23T12:00:00Z",
        },
    ]

    mock_resp = httpx.Response(
        200,
        json=items,
        request=httpx.Request(
            "GET", "https://gitlab.com/api/v4/projects/group%2Fproj/merge_requests"
        ),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        mrs = gitlab_adapter.list_pull_requests("group", "proj", state="all")

    assert len(mrs) == 3
    assert mrs[0].state == "open"
    assert mrs[1].state == "merged"
    assert mrs[2].state == "closed"


def test_list_pull_requests_pagination_and_cap(gitlab_adapter):
    page1 = httpx.Response(
        200,
        json=[{"iid": 1, "title": "M1", "source_branch": "a", "target_branch": "b", "author": {}}],
        headers={
            "link": '<https://gitlab.com/api/v4/projects/g%2Fp/merge_requests?page=2>; rel="next"'
        },
        request=httpx.Request("GET", "https://gitlab.com/api/v4/projects/g%2Fp/merge_requests"),
    )
    page2 = httpx.Response(
        200,
        json=[{"iid": 2, "title": "M2", "source_branch": "c", "target_branch": "d", "author": {}}],
        request=httpx.Request(
            "GET", "https://gitlab.com/api/v4/projects/g%2Fp/merge_requests?page=2"
        ),
    )

    with patch.object(gitlab_adapter._client, "request", side_effect=[page1, page2]):
        mrs = gitlab_adapter.list_pull_requests("g", "p")
        assert len(mrs) == 2
        assert mrs[0].id == "1"
        assert mrs[1].id == "2"


def test_create_pull_request_payload(gitlab_adapter):
    mock_resp = httpx.Response(
        201,
        json={
            "iid": 77,
            "title": "MR Title",
            "description": "MR Desc",
            "source_branch": "feature",
            "target_branch": "main",
            "web_url": "https://gitlab.com/g/p/-/merge_requests/77",
            "author": {"username": "alice"},
            "created_at": "2026-09-23T12:00:00Z",
        },
        request=httpx.Request("POST", "https://gitlab.com/api/v4/projects/g%2Fp/merge_requests"),
    )

    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp) as mock_req:
        mr = gitlab_adapter.create_pull_request(
            "g",
            "p",
            title="MR Title",
            source_branch="feature",
            target_branch="main",
            description="MR Desc",
        )

    assert mr.id == "77"
    assert mr.title == "MR Title"
    _, kwargs = mock_req.call_args
    assert kwargs["json"] == {
        "title": "MR Title",
        "source_branch": "feature",
        "target_branch": "main",
        "description": "MR Desc",
    }


def test_get_ci_status_mapping(gitlab_adapter):
    # Pipeline success
    resp_success = httpx.Response(
        200,
        json=[{"id": 100, "status": "success", "web_url": "https://gitlab.com/pipelines/100"}],
        request=httpx.Request("GET", "https://gitlab.com/pipelines"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=resp_success):
        ci = gitlab_adapter.get_ci_status("g", "p", "sha123")
        assert ci.state == "success"
        assert ci.url == "https://gitlab.com/pipelines/100"

    # Empty pipelines -> unknown
    resp_empty = httpx.Response(
        200, json=[], request=httpx.Request("GET", "https://gitlab.com/pipelines")
    )
    with patch.object(gitlab_adapter._client, "request", return_value=resp_empty):
        ci_empty = gitlab_adapter.get_ci_status("g", "p", "sha456")
        assert ci_empty.state == "unknown"


def test_submit_review_actions_and_self_approval_trap(gitlab_adapter):
    # Test supported review actions
    assert gitlab_adapter.supported_review_actions == frozenset({"approve", "comment"})

    with pytest.raises(ForgeError, match="GitLab does not support requesting changes"):
        gitlab_adapter.submit_review("g", "p", 1, action="request_changes")

    # Test self-approval trap translation
    resp_self_approve = httpx.Response(
        401,
        text='{"message": "401 Unauthorized - You cannot approve your own merge request"}',
        request=httpx.Request("POST", "https://gitlab.com/approve"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=resp_self_approve):
        with pytest.raises(ForgeError, match="You cannot approve your own merge request."):
            gitlab_adapter.submit_review("g", "p", 1, action="approve")

    # Test comment note creation
    resp_note = httpx.Response(
        201, json={}, request=httpx.Request("POST", "https://gitlab.com/notes")
    )
    with patch.object(gitlab_adapter._client, "request", return_value=resp_note) as mock_req:
        gitlab_adapter.submit_review("g", "p", 1, action="comment", body="Looking good")
        _, kwargs = mock_req.call_args
        assert kwargs["json"] == {"body": "Looking good"}


def test_get_pull_request(gitlab_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "iid": 42,
            "title": "MR 42",
            "description": "MR description",
            "state": "merged",
            "source_branch": "feature",
            "target_branch": "main",
            "web_url": "https://gitlab.com/g/p/-/merge_requests/42",
            "author": {"username": "alice"},
            "created_at": "2026-09-24T10:00:00Z",
        },
        request=httpx.Request("GET", "https://gitlab.com/api/v4/projects/g%2Fp/merge_requests/42"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        mr = gitlab_adapter.get_pull_request("g", "p", "42")
        assert mr.id == "42"
        assert mr.title == "MR 42"
        assert mr.state == "merged"
        assert mr.source_branch == "feature"
        assert mr.target_branch == "main"
        assert mr.author == "alice"


def test_get_issue(gitlab_adapter):
    mock_resp = httpx.Response(
        200,
        json={
            "iid": 114,
            "title": "Issue 114",
            "description": "Issue description",
            "state": "opened",
            "web_url": "https://gitlab.com/g/p/-/issues/114",
            "author": {"username": "bob"},
            "created_at": "2026-09-24T10:30:00Z",
        },
        request=httpx.Request("GET", "https://gitlab.com/api/v4/projects/g%2Fp/issues/114"),
    )
    with patch.object(gitlab_adapter._client, "request", return_value=mock_resp):
        issue = gitlab_adapter.get_issue("g", "p", "114")
        assert issue.id == "114"
        assert issue.title == "Issue 114"
        assert issue.state == "open"
        assert issue.author == "bob"
        assert issue.description == "Issue description"
