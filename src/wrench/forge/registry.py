"""Entry-points discovery for forge adapters."""

import atexit
import logging
import threading
from importlib.metadata import entry_points
from urllib.parse import urlparse

import httpx

from wrench.forge.capability import ForgeAdapter
from wrench.forge.exceptions import ForgeAdapterNotFoundError, ForgeError
from wrench.forge.models import ForgeAccount

logger = logging.getLogger(__name__)
_ENTRY_POINT_GROUP = "wrench.forge_adapters"
_adapter_cache: dict[str, type[ForgeAdapter]] | None = None


def discover_adapters() -> dict[str, type[ForgeAdapter]]:
    """Scan entry points and return {provider_id: AdapterClass}.

    Enforces loud failure if duplicate provider_id plugins are installed.
    """
    global _adapter_cache
    if _adapter_cache is not None:
        return _adapter_cache

    adapters: dict[str, type[ForgeAdapter]] = {}
    sources: dict[str, str] = {}

    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        cls = ep.load()
        pid = getattr(cls, "provider_id", None)
        if not pid:
            continue
        if pid in adapters:
            raise ForgeError(
                f"Duplicate forge adapter registered for provider {pid!r} "
                f"from {sources[pid]!r} and {ep.value!r}"
            )
        adapters[pid] = cls
        sources[pid] = ep.value

    _adapter_cache = adapters
    return adapters


def get_adapter_class(provider: str) -> type[ForgeAdapter]:
    """Retrieve adapter class for a provider string."""
    adapters = discover_adapters()
    cls = adapters.get(provider)
    if cls is None:
        raise ForgeAdapterNotFoundError(provider)
    return cls


def is_forge_enabled(repo_path: str | None = None) -> bool:
    """Return True if forge subsystem is globally or per-repo enabled (< 0.05 ms)."""
    try:
        from wrench.storage.settings_registry import get_settings_registry

        return get_settings_registry().is_enabled("forge.enabled", repo_path)
    except Exception as err:
        logger.debug("Failed checking forge enabled status: %s", err)
        return True


def is_provider_enabled(provider: str, repo_path: str | None = None) -> bool:
    """Return True if specific forge provider (e.g. github, gitlab) is enabled (< 0.05 ms)."""
    if not is_forge_enabled(repo_path):
        return False
    try:
        from wrench.storage.settings_registry import get_settings_registry

        return get_settings_registry().is_enabled(f"forge.{provider}.enabled", repo_path)
    except Exception as err:
        logger.debug("Failed checking provider enabled status for %s: %s", provider, err)
        return True


def get_adapter_for_account(
    account: ForgeAccount,
    repo_path: str | None = None,
    check_enabled: bool = False,
) -> ForgeAdapter | None:
    """Instantiate a new adapter for an account.

    If check_enabled is True, returns None if disabled.
    """
    if check_enabled and not is_provider_enabled(account.provider, repo_path):
        return None
    cls = get_adapter_class(account.provider)
    return cls(account)


create_adapter = get_adapter_for_account


def clear_adapter_cache() -> None:
    """Testing helper to reset cached entry points."""
    global _adapter_cache
    _adapter_cache = None


_avatar_http_client: httpx.Client | None = None
_avatar_http_lock = threading.Lock()
_avatar_http_inflight: int = 0
_avatar_http_retired: list[httpx.Client] = []


def _strip_avatar_request_cookies(request: httpx.Request) -> None:
    """Ensure avatar requests never replay stored or cross-origin cookies."""
    request.headers.pop("cookie", None)


def _strip_avatar_response_cookies(response: httpx.Response) -> None:
    """Drop Set-Cookie headers on avatar responses to prevent jar accumulation."""
    response.headers.pop("set-cookie", None)


def _get_avatar_http_client() -> httpx.Client:
    """Return shared singleton httpx.Client for avatar fetches."""
    with _avatar_http_lock:
        return _get_avatar_http_client_unlocked()


def _close_client_safely(client: httpx.Client) -> None:
    if not getattr(client, "is_closed", False):
        try:
            client.close()
        except Exception as exc:
            logger.debug("Error closing avatar httpx client: %s", exc)


def close_avatar_http_client() -> None:
    """Close shared avatar httpx.Client immediately if idle, or defer until in-flight finishes."""
    global _avatar_http_client
    to_close: list[httpx.Client] = []
    with _avatar_http_lock:
        client = _avatar_http_client
        _avatar_http_client = None
        if client is not None:
            if _avatar_http_inflight == 0:
                to_close.append(client)
            else:
                _avatar_http_retired.append(client)
        if _avatar_http_inflight == 0 and _avatar_http_retired:
            to_close.extend(_avatar_http_retired)
            _avatar_http_retired.clear()
    for c in to_close:
        _close_client_safely(c)


atexit.register(close_avatar_http_client)


def fetch_avatar_bytes(
    url: str, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> bytes:
    """Fetch raw avatar image bytes using the shared stateless singleton httpx.Client."""
    global _avatar_http_inflight
    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Unsupported avatar URL scheme or host: {url!r}")

    with _avatar_http_lock:
        client = _get_avatar_http_client_unlocked()
        _avatar_http_inflight += 1

    try:
        resp = client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    finally:
        cookies = getattr(client, "cookies", None)
        if cookies is not None and callable(getattr(cookies, "clear", None)):
            try:
                cookies.clear()
            except Exception as exc:
                logger.debug("Clearing avatar client cookies skipped: %s", exc)
        to_close: list[httpx.Client] = []
        with _avatar_http_lock:
            _avatar_http_inflight = max(0, _avatar_http_inflight - 1)
            if _avatar_http_inflight == 0 and _avatar_http_retired:
                to_close.extend(_avatar_http_retired)
                _avatar_http_retired.clear()
        for c in to_close:
            _close_client_safely(c)


def _get_avatar_http_client_unlocked() -> httpx.Client:
    """Internal helper returning or constructing the singleton client while lock is held."""
    global _avatar_http_client
    if _avatar_http_client is None or _avatar_http_client.is_closed:
        _avatar_http_client = httpx.Client(
            timeout=10.0,
            limits=httpx.Limits(
                max_keepalive_connections=4,
                max_connections=8,
                keepalive_expiry=30.0,
            ),
            follow_redirects=True,
            max_redirects=5,
            event_hooks={
                "request": [_strip_avatar_request_cookies],
                "response": [_strip_avatar_response_cookies],
            },
        )
    return _avatar_http_client
