"""Entry-points discovery for forge adapters."""

import logging
from importlib.metadata import entry_points

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


def fetch_avatar_bytes(
    url: str, headers: dict[str, str] | None = None, timeout: float = 10.0
) -> bytes:
    """Fetch raw avatar image bytes using httpx (forge network layer)."""

    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.content
