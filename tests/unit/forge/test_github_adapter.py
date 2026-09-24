"""Unit tests for GitHubAdapter-specific methods."""

from unittest.mock import MagicMock, patch

import pytest

from wrench.forge.adapters.github import GitHubAdapter
from wrench.forge.models import ForgeAccount


@pytest.fixture
def mock_account():
    """Create a mock ForgeAccount for testing."""
    account = MagicMock(spec=ForgeAccount)
    account.label = "test-github"
    account.provider = "github"
    account.instance_url = "https://github.com"
    account.secret_service_key = "wrench/github/test"
    account.tls_insecure = False
    account.tls_ca_bundle_path = None
    return account


@pytest.fixture
def adapter(mock_account):
    """Create a GitHubAdapter with mocked credentials."""
    with patch("wrench.credentials.get_backend") as mock_backend:
        mock_backend.return_value.get_secret.return_value = "ghp_test_token_123"
        adapter = GitHubAdapter(mock_account)
    yield adapter
    adapter.close()


class TestGetPrimaryEmail:
    def test_returns_primary_verified_email(self, adapter):
        mock_emails = [
            {"email": "noreply@users.noreply.github.com", "primary": False, "verified": True},
            {"email": "user@example.com", "primary": True, "verified": True},
        ]
        with patch.object(adapter, "_request") as mock_request:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_emails
            mock_request.return_value = mock_resp

            result = adapter.get_primary_email()
            assert result == "user@example.com"
            mock_request.assert_called_once_with("GET", "/user/emails")

    def test_returns_first_verified_if_no_primary(self, adapter):
        mock_emails = [
            {"email": "alt@example.com", "primary": False, "verified": True},
            {"email": "unverified@example.com", "primary": False, "verified": False},
        ]
        with patch.object(adapter, "_request") as mock_request:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_emails
            mock_request.return_value = mock_resp

            result = adapter.get_primary_email()
            assert result == "alt@example.com"

    def test_returns_none_on_empty_list(self, adapter):
        with patch.object(adapter, "_request") as mock_request:
            mock_resp = MagicMock()
            mock_resp.json.return_value = []
            mock_request.return_value = mock_resp

            result = adapter.get_primary_email()
            assert result is None

    def test_returns_none_on_api_error(self, adapter):
        from wrench.forge.exceptions import ForgeError

        with patch.object(adapter, "_request", side_effect=ForgeError("API error")):
            result = adapter.get_primary_email()
            assert result is None
