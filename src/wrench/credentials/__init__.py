"""FR-11.1: Platform credential factory."""

import os
import sys

from .backend import CredentialBackend


def _detect_packaging_context() -> str:
    """Returns 'flatpak', 'appimage', or 'bare'."""
    if os.environ.get("FLATPAK_ID") or os.path.exists("/.flatpak-info"):
        return "flatpak"
    if os.environ.get("APPIMAGE"):
        return "appimage"
    return "bare"


def get_backend() -> CredentialBackend:
    if sys.platform.startswith("linux") or sys.platform.startswith("freebsd"):
        context = _detect_packaging_context()
        if context == "flatpak":
            from .secret_service import FlatpakSecretServiceBackend

            return FlatpakSecretServiceBackend()
        from .secret_service import AppImageSecretServiceBackend

        return AppImageSecretServiceBackend()
    raise NotImplementedError(
        f"No CredentialBackend for platform {sys.platform!r} yet — see SRS §7.3"
    )
