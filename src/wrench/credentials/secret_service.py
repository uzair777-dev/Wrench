"""FR-4.3: Secret Service D-Bus backend."""

from .backend import CredentialBackend

_ATTR_APP = "wrench"


class SecretServiceBackend(CredentialBackend):
    def _collection(self):
        raise NotImplementedError

    def store_secret(self, key: str, secret: str, *, label: str) -> None:
        raise NotImplementedError

    def get_secret(self, key: str) -> str | None:
        raise NotImplementedError

    def delete_secret(self, key: str) -> None:
        raise NotImplementedError

    def unavailable_help_text(self) -> str:
        raise NotImplementedError


class FlatpakSecretServiceBackend(SecretServiceBackend):
    def unavailable_help_text(self) -> str:
        return (
            "Wrench couldn't reach a secret storage service. Under Flatpak this is almost "
            "always a missing permission, not a missing service — check with Flatseal, or run:\n"
            "  flatpak override --talk-name=org.freedesktop.secrets io.github.uzair.Wrench\n"
            "then restart Wrench."
        )


class AppImageSecretServiceBackend(SecretServiceBackend):
    def unavailable_help_text(self) -> str:
        return (
            "Wrench couldn't reach a secret storage service. There's no sandbox permission "
            "to fix here — this means no Secret Service provider (GNOME Keyring, KWallet, or "
            "similar) is currently running. Most full desktop environments start one "
            "automatically; on a minimal window manager (i3, sway, etc.) you may need to "
            "start one yourself, e.g.:\n"
            "  gnome-keyring-daemon --start --components=secrets"
        )
