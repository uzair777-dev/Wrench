"""GitHub OAuth Device Flow (RFC 8628) for native desktop authentication."""

import logging
import threading
import time
from dataclasses import dataclass

import httpx

from wrench.forge.exceptions import ForgeAuthenticationError, ForgeError

logger = logging.getLogger(__name__)

GITHUB_CLIENT_ID = "Ov23liB9V3dIK8eViERi"

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_DEVICE_VERIFICATION_URI = "https://github.com/login/device"


@dataclass(frozen=True, slots=True)
class DeviceFlowCodes:
    """Codes returned by the initial device code request."""

    device_code: str
    user_code: str
    verification_uri: str
    interval: int  # seconds between polls (typically 5)
    expires_in: int  # seconds until codes expire (typically 900 = 15min)


def _build_device_code_url(instance_url: str) -> str:
    """Build the device code endpoint URL.

    For github.com: https://github.com/login/device/code
    For GHES:       https://ghes.company.com/login/device/code
    """
    base = instance_url.rstrip("/")
    return f"{base}/login/device/code"


def _build_token_url(instance_url: str) -> str:
    """Build the token exchange endpoint URL.

    For github.com: https://github.com/login/oauth/access_token
    For GHES:       https://ghes.company.com/login/oauth/access_token
    """
    base = instance_url.rstrip("/")
    return f"{base}/login/oauth/access_token"


def request_device_code(
    client_id: str,
    scope: str = "repo",
    instance_url: str = "https://github.com",
) -> DeviceFlowCodes:
    """Step 1: Request device and user codes from GitHub.

    Args:
        client_id: The OAuth App's client ID.
        scope: OAuth scope string (e.g. "repo" or "public_repo").
        instance_url: Base URL. "https://github.com" for personal,
                      or "https://ghes.company.com" for Enterprise.

    Returns:
        DeviceFlowCodes with the user_code to display and device_code for polling.

    Raises:
        ForgeError: If the request fails or returns an unexpected response.
    """
    url = _build_device_code_url(instance_url)
    headers = {"Accept": "application/json"}
    data = {"client_id": client_id, "scope": scope}

    try:
        resp = httpx.post(url, data=data, headers=headers, timeout=15.0)
    except httpx.ConnectError as exc:
        cause = str(exc).lower()
        if "ssl" in cause or "certificate" in cause:
            raise ForgeError(
                f"SSL certificate verification failed for {instance_url}. "
                "If using a self-hosted instance, use Manual Setup "
                "to configure a custom CA bundle."
            ) from exc
        raise ForgeError(
            f"Cannot reach {instance_url}. Check your internet connection and try again."
        ) from exc
    except httpx.TimeoutException as exc:
        raise ForgeError(
            f"Connection to {instance_url} timed out. "
            "The server may be busy — try again in a moment."
        ) from exc
    except httpx.HTTPError as exc:
        raise ForgeError(f"Failed to contact GitHub: {exc}") from exc

    if resp.status_code >= 500:
        raise ForgeError(
            f"GitHub is experiencing issues (HTTP {resp.status_code}). "
            "Check status.github.com and try again later."
        )
    if resp.status_code != 200:
        raise ForgeError(
            f"GitHub device code request failed ({resp.status_code}): " f"{resp.text[:300]}"
        )

    body = resp.json()

    if "error" in body:
        raise ForgeError(
            f"GitHub device code error: {body.get('error_description', body['error'])}"
        )

    return DeviceFlowCodes(
        device_code=body["device_code"],
        user_code=body["user_code"],
        verification_uri=body.get("verification_uri", GITHUB_DEVICE_VERIFICATION_URI),
        interval=int(body.get("interval", 5)),
        expires_in=int(body.get("expires_in", 900)),
    )


def poll_for_token(
    client_id: str,
    device_code: str,
    interval: int,
    expires_in: int,
    cancel_event: threading.Event,
    instance_url: str = "https://github.com",
) -> str:
    """Step 2: Poll GitHub until user authorizes or timeout.

    This is a BLOCKING function — run it in a background thread.

    Args:
        client_id: The OAuth App's client ID.
        device_code: The device_code from request_device_code().
        interval: Seconds between polls (from DeviceFlowCodes.interval).
        expires_in: Seconds until expiry (from DeviceFlowCodes.expires_in).
        cancel_event: threading.Event — set it to cancel the poll loop.
        instance_url: Base URL for the token endpoint.

    Returns:
        The access_token string.

    Raises:
        ForgeAuthenticationError: If user denied access.
        ForgeError: If codes expired or an unexpected error occurred.
    """
    url = _build_token_url(instance_url)
    headers = {"Accept": "application/json"}
    data = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }

    current_interval = interval
    deadline = time.monotonic() + expires_in

    while time.monotonic() < deadline:
        if cancel_event.is_set():
            raise ForgeError("Authorization cancelled by user.")

        # Wait the required interval, checking cancel every second
        for _ in range(current_interval):
            if cancel_event.is_set():
                raise ForgeError("Authorization cancelled by user.")
            time.sleep(1.0)

        try:
            resp = httpx.post(url, data=data, headers=headers, timeout=15.0)
        except httpx.HTTPError as exc:
            logger.warning("Device flow poll network error: %s", exc)
            continue  # Retry on transient network errors

        if resp.status_code != 200:
            logger.warning("Device flow poll HTTP %d", resp.status_code)
            continue

        body = resp.json()

        if "access_token" in body:
            return body["access_token"]

        error = body.get("error", "")

        if error == "authorization_pending":
            # Normal — user hasn't authorized yet, keep polling
            continue
        elif error == "slow_down":
            # GitHub wants us to back off — add 5 seconds per spec
            current_interval += 5
            logger.debug("Device flow: slow_down, interval now %ds", current_interval)
            continue
        elif error == "expired_token":
            raise ForgeError("The authorization code has expired. Please try again.")
        elif error == "access_denied":
            raise ForgeAuthenticationError("You denied the authorization request on GitHub.")
        elif error == "unsupported_grant_type":
            raise ForgeError(
                "Device Flow is not enabled for this OAuth App. "
                "Enable it in the app settings on GitHub."
            )
        else:
            raise ForgeError(
                f"Unexpected device flow error: {body.get('error_description', error)}"
            )

    raise ForgeError("The authorization code has expired. Please try again.")
