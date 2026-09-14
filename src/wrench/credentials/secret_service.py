import secretstorage
from secretstorage.exceptions import LockedException, SecretServiceNotAvailableException

from .backend import CredentialBackend, CredentialBackendUnavailableError

_ATTR_APP = "wrench"


class SecretServiceBackend(CredentialBackend):
    def _collection(self):
        try:
            bus = secretstorage.dbus_init()
            collection = secretstorage.get_default_collection(bus)
        except SecretServiceNotAvailableException as e:
            raise CredentialBackendUnavailableError(self.unavailable_help_text()) from e

        if collection.is_locked():
            try:
                collection.unlock()
            except LockedException as e:
                raise CredentialBackendUnavailableError(self.unavailable_help_text()) from e
        return collection

    def store_secret(self, key: str, secret: str, *, label: str) -> None:
        self._collection().create_item(
            label, {"application": _ATTR_APP, "key": key}, secret, replace=True
        )

    def get_secret(self, key: str) -> str | None:
        items = self._collection().search_items({"application": _ATTR_APP, "key": key})
        for item in items:
            sec = item.get_secret()
            if isinstance(sec, bytes):
                return sec.decode("utf-8")
            return str(sec) if sec is not None else None
        return None

    def delete_secret(self, key: str) -> None:
        for item in self._collection().search_items({"application": _ATTR_APP, "key": key}):
            item.delete()


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
