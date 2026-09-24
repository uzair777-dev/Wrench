"""Entry-points discovery for forge adapters."""

import logging
from importlib.metadata import entry_points

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


def get_adapter_for_account(account: ForgeAccount) -> ForgeAdapter:
    """Instantiate a new adapter for an account."""
    cls = get_adapter_class(account.provider)
    return cls(account)


create_adapter = get_adapter_for_account


def clear_adapter_cache() -> None:
    """Testing helper to reset cached entry points."""
    global _adapter_cache
    _adapter_cache = None
