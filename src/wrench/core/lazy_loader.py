"""Lazy import utilities supporting explicit deferred module loading.

Complies with Python 3.15 explicit lazy import patterns (PEP 810).
Provides a backward-compatible LazyProxyModule for environments running on
earlier Python runtimes (e.g., Python 3.14).
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any


class LazyProxyModule(types.ModuleType):
    """A proxy module that defers actual import until an attribute is accessed."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self._target_name = name
        self._loaded_module: types.ModuleType | None = None

    def _resolve(self) -> types.ModuleType:
        if self._loaded_module is None:
            # If already present in sys.modules and not self, use it
            existing = sys.modules.get(self._target_name)
            if existing is not None and not isinstance(existing, LazyProxyModule):
                self._loaded_module = existing
            else:
                # Remove self from sys.modules temporarily so importlib actually loads it
                sys.modules.pop(self._target_name, None)
                self._loaded_module = importlib.import_module(self._target_name)
                sys.modules[self._target_name] = self._loaded_module
        return self._loaded_module

    def __getattr__(self, item: str) -> Any:
        module = self._resolve()
        return getattr(module, item)

    def __repr__(self) -> str:
        if self._loaded_module is not None:
            return repr(self._loaded_module)
        return f"<LazyProxyModule '{self._target_name}' (deferred)>"


def lazy_import(name: str) -> types.ModuleType:
    """Explicitly declare a lazy import for a module.

    Usage:
        math = lazy_import("math")
        # math is not imported into memory until math.<attr> is accessed.
    """
    if name in sys.modules and not isinstance(sys.modules[name], LazyProxyModule):
        return sys.modules[name]

    proxy = LazyProxyModule(name)
    return proxy
