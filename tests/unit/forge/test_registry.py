"""Unit tests for forge adapter entry-points registry."""

from unittest.mock import MagicMock, patch

import pytest

from wrench.forge import registry
from wrench.forge.capability import ForgeAdapter, ForgeCapability
from wrench.forge.exceptions import ForgeAdapterNotFoundError, ForgeError
from wrench.forge.models import ForgeAccount


class MockGitHubAdapter(ForgeAdapter):
    provider_id = "github"

    @property
    def capabilities(self) -> ForgeCapability:
        return ForgeCapability.PULL_REQUESTS

    def _get_base_url(self) -> str:
        return "https://api.github.com"

    def _auth_headers_and_auth(self):
        return {}, None

    def _get_scope_hint(self) -> str:
        return "repo"

    def list_pull_requests(self, owner: str, repo: str, state: str = "open"):
        return []

    def create_pull_request(self, owner: str, repo: str, **kwargs):
        raise NotImplementedError

    def submit_review(self, owner: str, repo: str, number: int, **kwargs):
        pass

    def get_ci_status(self, owner: str, repo: str, ref: str):
        raise NotImplementedError


class MockDuplicateAdapter(ForgeAdapter):
    provider_id = "github"

    @property
    def capabilities(self) -> ForgeCapability:
        return ForgeCapability.PULL_REQUESTS

    def _get_base_url(self) -> str:
        return "https://api.github.com"

    def _auth_headers_and_auth(self):
        return {}, None

    def _get_scope_hint(self) -> str:
        return "repo"

    def list_pull_requests(self, owner: str, repo: str, state: str = "open"):
        return []

    def create_pull_request(self, owner: str, repo: str, **kwargs):
        raise NotImplementedError

    def submit_review(self, owner: str, repo: str, number: int, **kwargs):
        pass

    def get_ci_status(self, owner: str, repo: str, ref: str):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def clean_registry_cache():
    registry.clear_adapter_cache()
    yield
    registry.clear_adapter_cache()


def test_discover_adapters_and_caching():
    ep = MagicMock()
    ep.load.return_value = MockGitHubAdapter
    ep.value = "mock_pkg.adapters:MockGitHubAdapter"

    with patch("wrench.forge.registry.entry_points", return_value=[ep]):
        adapters1 = registry.discover_adapters()
        assert "github" in adapters1
        assert adapters1["github"] is MockGitHubAdapter

        # Second call returns cached dict without re-scanning entry points
        adapters2 = registry.discover_adapters()
        assert adapters1 is adapters2


def test_discover_adapters_duplicate_raises_error():
    ep1 = MagicMock()
    ep1.load.return_value = MockGitHubAdapter
    ep1.value = "pkg1:MockGitHubAdapter"

    ep2 = MagicMock()
    ep2.load.return_value = MockDuplicateAdapter
    ep2.value = "pkg2:MockDuplicateAdapter"

    with patch("wrench.forge.registry.entry_points", return_value=[ep1, ep2]):
        with pytest.raises(
            ForgeError, match="Duplicate forge adapter registered for provider 'github'"
        ):
            registry.discover_adapters()


def test_get_adapter_for_account_success():
    ep = MagicMock()
    ep.load.return_value = MockGitHubAdapter
    ep.value = "mock_pkg.adapters:MockGitHubAdapter"

    account = ForgeAccount(
        id=1,
        provider="github",
        instance_url="https://github.com",
        label="GitHub",
        username="alice",
        secret_service_key="wrench:forge:1",
    )

    with patch("wrench.forge.registry.entry_points", return_value=[ep]):
        adapter = registry.get_adapter_for_account(account)
        assert isinstance(adapter, MockGitHubAdapter)
        assert adapter.account == account
        adapter.close()


def test_get_adapter_for_account_not_found():
    account = ForgeAccount(
        id=1,
        provider="unknown_forge",
        instance_url="https://forge.example.com",
        label="Custom",
        username="bob",
        secret_service_key="wrench:forge:1",
    )

    with patch("wrench.forge.registry.entry_points", return_value=[]):
        with pytest.raises(ForgeAdapterNotFoundError) as exc_info:
            registry.get_adapter_for_account(account)
        assert exc_info.value.provider == "unknown_forge"
