"""Unit tests for ForgeCapability and ForgeAdapter ABC."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.exceptions import (
    ForgeAuthenticationError,
    ForgeError,
    ForgeInsufficientScopeError,
    ForgeRateLimitedError,
    ForgeUnreachableError,
)
from wrench.forge.models import CIStatus, ForgeAccount, PullRequest


class DummyAdapter(ForgeAdapter):
    provider_id = "dummy"

    @property
    def capabilities(self) -> ForgeCapability:
        return ForgeCapability.PULL_REQUESTS | ForgeCapability.CI_STATUS

    def _get_base_url(self) -> str:
        return "https://api.dummy.com"

    def _auth_headers_and_auth(self) -> tuple[dict[str, str], httpx.Auth | None]:
        return {"Authorization": f"Bearer {self._get_token()}"}, None

    def _get_scope_hint(self) -> str:
        return "needs 'dummy' scope"

    def list_pull_requests(self, owner: str, repo: str, state: str = "open") -> list[PullRequest]:
        return []

    def create_pull_request(self, owner: str, repo: str, **kwargs) -> PullRequest:
        raise NotImplementedError

    def submit_review(self, owner: str, repo: str, number: int, **kwargs) -> None:
        pass

    def get_ci_status(self, owner: str, repo: str, ref: str) -> CIStatus:
        return CIStatus(state="unknown")


@pytest.fixture
def dummy_account():
    return ForgeAccount(
        id=1,
        provider="dummy",
        instance_url="https://dummy.com",
        label="Dummy",
        username="user",
        secret_service_key="wrench:forge:1",
        tls_ca_bundle_path=None,
        tls_insecure=False,
    )


def test_forge_capability_flags():
    caps = ForgeCapability.PULL_REQUESTS | ForgeCapability.REVIEWS
    assert ForgeCapability.PULL_REQUESTS in caps
    assert ForgeCapability.REVIEWS in caps
    assert ForgeCapability.ISSUES not in caps


def test_adapter_tls_config(dummy_account):
    adapter = DummyAdapter(dummy_account)
    # Default verify is True
    assert adapter._client._transport._pool._ssl_context is not None
    adapter.close()

    insecure_acc = ForgeAccount(
        id=2,
        provider="dummy",
        instance_url="https://dummy.com",
        label="Dummy Insecure",
        username="user",
        secret_service_key="wrench:forge:2",
        tls_insecure=True,
    )
    insecure_adapter = DummyAdapter(insecure_acc)
    # Should not raise
    insecure_adapter.close()


def test_adapter_get_token_caching(dummy_account):
    adapter = DummyAdapter(dummy_account)
    mock_backend = MagicMock()
    mock_backend.get_secret.return_value = "token_xyz"

    with patch("wrench.credentials.get_backend", return_value=mock_backend):
        t1 = adapter._get_token()
        t2 = adapter._get_token()

    assert t1 == "token_xyz"
    assert t2 == "token_xyz"
    assert mock_backend.get_secret.call_count == 1
    adapter.close()


def test_adapter_missing_token_raises_auth_error(dummy_account):
    adapter = DummyAdapter(dummy_account)
    mock_backend = MagicMock()
    mock_backend.get_secret.return_value = None

    with patch("wrench.credentials.get_backend", return_value=mock_backend):
        with pytest.raises(ForgeAuthenticationError, match="No token found"):
            adapter._get_token()
    adapter.close()


def test_adapter_request_401_auth_error(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "bad_token"

    mock_resp = httpx.Response(401, request=httpx.Request("GET", "https://api.dummy.com/test"))
    with patch.object(adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeAuthenticationError, match="rejected"):
            adapter._request("GET", "/test")
    adapter.close()


def test_adapter_request_403_scope_error(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    mock_resp = httpx.Response(403, request=httpx.Request("GET", "https://api.dummy.com/test"))
    with patch.object(adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeInsufficientScopeError) as exc_info:
            adapter._request("GET", "/test")
        assert exc_info.value.scope_hint == "needs 'dummy' scope"
    adapter.close()


def test_adapter_request_403_rate_limit_trap(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "2000000000"}
    mock_resp = httpx.Response(
        403, headers=headers, request=httpx.Request("GET", "https://api.dummy.com/test")
    )
    with patch.object(adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError):
            adapter._request("GET", "/test")
    adapter.close()


def test_adapter_request_429_rate_limit(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    headers = {"Retry-After": "45"}
    mock_resp = httpx.Response(
        429, headers=headers, request=httpx.Request("GET", "https://api.dummy.com/test")
    )
    with patch.object(adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeRateLimitedError) as exc:
            adapter._request("GET", "/test")
        assert exc.value.retry_after_seconds == 45
    adapter.close()


def test_adapter_request_422_validation_error(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    json_payload = {
        "message": "Validation Failed",
        "errors": [{"message": "Branch 'main' already exists"}],
    }
    mock_resp = httpx.Response(
        422, json=json_payload, request=httpx.Request("POST", "https://api.dummy.com/test")
    )
    with patch.object(adapter._client, "request", return_value=mock_resp):
        with pytest.raises(ForgeError, match="Branch 'main' already exists"):
            adapter._request("POST", "/test")
    adapter.close()


def test_adapter_request_connect_timeout_unreachable(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    with patch.object(
        adapter._client, "request", side_effect=httpx.ConnectError("Connection refused")
    ):
        with pytest.raises(ForgeUnreachableError, match="Can't reach https://dummy.com"):
            adapter._request("GET", "/test")
    adapter.close()


def test_adapter_paged_get_and_runaway_cap(dummy_account):
    adapter = DummyAdapter(dummy_account)
    adapter._cached_token = "token"

    page1_resp = httpx.Response(
        200,
        json=[{"id": 1}],
        headers={"link": '<https://api.dummy.com/items?page=2>; rel="next"'},
        request=httpx.Request("GET", "https://api.dummy.com/items"),
    )
    page2_resp = httpx.Response(
        200,
        json=[{"id": 2}],
        headers={"link": '<https://api.dummy.com/items?page=3>; rel="next"'},
        request=httpx.Request("GET", "https://api.dummy.com/items?page=2"),
    )
    page3_resp = httpx.Response(
        200,
        json=[{"id": 3}],
        request=httpx.Request("GET", "https://api.dummy.com/items?page=3"),
    )

    with patch.object(adapter._client, "request", side_effect=[page1_resp, page2_resp, page3_resp]):
        items = adapter._paged_get("/items", max_pages=2)
        # Capped at 2 pages
        assert len(items) == 2
        assert items[0]["id"] == 1
        assert items[1]["id"] == 2
    adapter.close()


def test_adapter_context_manager(dummy_account):
    with DummyAdapter(dummy_account) as adapter:
        assert not adapter._client.is_closed
    assert adapter._client.is_closed
