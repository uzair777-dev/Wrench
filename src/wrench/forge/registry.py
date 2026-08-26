"""Entry-points discovery for forge adapters."""

from importlib.metadata import entry_points

from .capability import ForgeAdapter
from .models import ForgeAccount

_ENTRY_POINT_GROUP = "wrench.forge_adapters"


class ForgeAdapterNotFoundError(Exception):
    """Raised when an adapter for a provider cannot be found."""


def discover_adapters() -> dict[str, type[ForgeAdapter]]:
    adapters = {}
    for ep in entry_points(group=_ENTRY_POINT_GROUP):
        cls = ep.load()
        adapters[cls.provider_id] = cls
    return adapters


def get_adapter_for_account(account: ForgeAccount) -> ForgeAdapter:
    adapters = discover_adapters()
    cls = adapters.get(account.provider)
    if cls is None:
        raise ForgeAdapterNotFoundError(account.provider)
    return cls()
