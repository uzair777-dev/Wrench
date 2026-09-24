"""Tests for GitHub OAuth Device Flow protocol logic."""

import threading
import unittest
from unittest.mock import MagicMock, patch

import httpx

from wrench.forge.exceptions import ForgeAuthenticationError, ForgeError
from wrench.forge.oauth.github_device_flow import (
    DeviceFlowCodes,
    _build_device_code_url,
    _build_token_url,
    poll_for_token,
    request_device_code,
)


class TestBuildUrls(unittest.TestCase):
    """Test URL construction for personal and enterprise instances."""

    def test_personal_device_code_url(self):
        url = _build_device_code_url("https://github.com")
        assert url == "https://github.com/login/device/code"

    def test_enterprise_device_code_url(self):
        url = _build_device_code_url("https://ghes.company.com")
        assert url == "https://ghes.company.com/login/device/code"

    def test_trailing_slash_stripped(self):
        url = _build_device_code_url("https://github.com/")
        assert url == "https://github.com/login/device/code"

    def test_personal_token_url(self):
        url = _build_token_url("https://github.com")
        assert url == "https://github.com/login/oauth/access_token"

    def test_enterprise_token_url(self):
        url = _build_token_url("https://ghes.corp.net")
        assert url == "https://ghes.corp.net/login/oauth/access_token"


class TestRequestDeviceCode(unittest.TestCase):
    """Test the initial device code request."""

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "device_code": "dc_abc123",
            "user_code": "ABCD-1234",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        }
        mock_post.return_value = mock_resp

        codes = request_device_code("test_client_id", scope="repo")

        assert isinstance(codes, DeviceFlowCodes)
        assert codes.device_code == "dc_abc123"
        assert codes.user_code == "ABCD-1234"
        assert codes.verification_uri == "https://github.com/login/device"
        assert codes.interval == 5
        assert codes.expires_in == 900

        # Verify the POST was called with correct params
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["data"]["client_id"] == "test_client_id"
        assert call_kwargs.kwargs["data"]["scope"] == "repo"

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_enterprise_url(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "device_code": "dc_ent",
            "user_code": "EFGH-5678",
            "verification_uri": "https://ghes.co/login/device",
            "interval": 5,
            "expires_in": 900,
        }
        mock_post.return_value = mock_resp

        codes = request_device_code(
            "ent_client",
            scope="repo",
            instance_url="https://ghes.co",
        )
        assert codes.device_code == "dc_ent"

        # Verify it hit the enterprise URL
        call_url = mock_post.call_args.args[0]
        assert call_url == "https://ghes.co/login/device/code"

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_http_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_post.return_value = mock_resp

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("test_id")
        assert "404" in str(ctx.exception)

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_network_error_raises(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("DNS failed")

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("test_id")
        assert "Cannot reach" in str(ctx.exception)

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_error_response_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "error": "unauthorized_client",
            "error_description": "The client is not authorized",
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("bad_id")
        assert "not authorized" in str(ctx.exception)

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_ssl_error_gives_actionable_message(self, mock_post):
        mock_post.side_effect = httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED")

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("test_id")
        msg = str(ctx.exception)
        assert "SSL" in msg
        assert "Manual Setup" in msg

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_timeout_gives_actionable_message(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("test_id")
        assert "timed out" in str(ctx.exception).lower()

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_server_500_gives_status_page_hint(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_post.return_value = mock_resp

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("test_id")
        assert "status.github.com" in str(ctx.exception)

    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_unauthorized_client_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "error": "unauthorized_client",
            "error_description": "Client is not authorized for device flow",
        }
        mock_post.return_value = mock_resp

        with self.assertRaises(ForgeError) as ctx:
            request_device_code("unauth_id")
        assert "not authorized for device flow" in str(ctx.exception)


class TestPollForToken(unittest.TestCase):
    """Test the polling loop."""

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_immediate_success(self, mock_post, mock_sleep):
        """Token returned on first poll."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "gho_abc123"}
        mock_post.return_value = mock_resp

        cancel = threading.Event()
        token = poll_for_token(
            "cid",
            "dc_123",
            interval=1,
            expires_in=60,
            cancel_event=cancel,
        )
        assert token == "gho_abc123"

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_pending_then_success(self, mock_post, mock_sleep):
        """authorization_pending twice, then success."""
        pending_resp = MagicMock()
        pending_resp.status_code = 200
        pending_resp.json.return_value = {"error": "authorization_pending"}

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"access_token": "gho_final"}

        mock_post.side_effect = [pending_resp, pending_resp, success_resp]

        cancel = threading.Event()
        token = poll_for_token(
            "cid",
            "dc_123",
            interval=1,
            expires_in=60,
            cancel_event=cancel,
        )
        assert token == "gho_final"

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_slow_down_increases_interval(self, mock_post, mock_sleep):
        """slow_down response should increase interval by 5."""
        slow_resp = MagicMock()
        slow_resp.status_code = 200
        slow_resp.json.return_value = {"error": "slow_down"}

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"access_token": "gho_slow"}

        mock_post.side_effect = [slow_resp, success_resp]

        cancel = threading.Event()
        token = poll_for_token(
            "cid",
            "dc_123",
            interval=1,
            expires_in=60,
            cancel_event=cancel,
        )
        assert token == "gho_slow"
        assert mock_sleep.call_count > 2

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_access_denied_raises_auth_error(self, mock_post, mock_sleep):
        denied_resp = MagicMock()
        denied_resp.status_code = 200
        denied_resp.json.return_value = {"error": "access_denied"}
        mock_post.return_value = denied_resp

        cancel = threading.Event()
        with self.assertRaises(ForgeAuthenticationError):
            poll_for_token(
                "cid",
                "dc_123",
                interval=1,
                expires_in=60,
                cancel_event=cancel,
            )

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_expired_token_raises(self, mock_post, mock_sleep):
        expired_resp = MagicMock()
        expired_resp.status_code = 200
        expired_resp.json.return_value = {"error": "expired_token"}
        mock_post.return_value = expired_resp

        cancel = threading.Event()
        with self.assertRaises(ForgeError) as ctx:
            poll_for_token(
                "cid",
                "dc_123",
                interval=1,
                expires_in=60,
                cancel_event=cancel,
            )
        assert "expired" in str(ctx.exception).lower()

    @patch("wrench.forge.oauth.github_device_flow.time.sleep")
    @patch("wrench.forge.oauth.github_device_flow.httpx.post")
    def test_cancel_event_stops_polling(self, mock_post, mock_sleep):
        """Setting cancel_event should raise ForgeError."""
        cancel = threading.Event()
        cancel.set()  # Pre-set — loop should exit immediately

        with self.assertRaises(ForgeError) as ctx:
            poll_for_token(
                "cid",
                "dc_123",
                interval=1,
                expires_in=60,
                cancel_event=cancel,
            )
        assert "cancelled" in str(ctx.exception).lower()
