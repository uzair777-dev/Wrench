"""Unit tests for the Secret Service credential backend (§5 Phase 3 Step 1)."""

import shutil
import sys
from unittest.mock import MagicMock, patch

import pytest
from secretstorage.exceptions import LockedException, SecretServiceNotAvailableException

from wrench.credentials import _detect_packaging_context, get_backend
from wrench.credentials.backend import CredentialBackendUnavailableError
from wrench.credentials.secret_service import (
    _ATTR_APP,
    AppImageSecretServiceBackend,
    FlatpakSecretServiceBackend,
    SecretServiceBackend,
)


class DummySecretServiceBackend(SecretServiceBackend):
    def unavailable_help_text(self) -> str:
        return "Dummy backend help text"


class TestSecretServiceBackend:
    def test_get_secret_happy_path(self):
        backend = DummySecretServiceBackend()
        mock_item = MagicMock()
        mock_item.get_secret.return_value = b"my-super-secret-token"

        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = False
        mock_coll.search_items.return_value = [mock_item]

        with patch.object(backend, "_collection", return_value=mock_coll):
            result = backend.get_secret("wrench:forge:1")
            assert result == "my-super-secret-token"
            mock_coll.search_items.assert_called_once_with(
                {"application": _ATTR_APP, "key": "wrench:forge:1"}
            )

    def test_get_secret_empty_returns_none(self):
        backend = DummySecretServiceBackend()
        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = False
        mock_coll.search_items.return_value = []

        with patch.object(backend, "_collection", return_value=mock_coll):
            result = backend.get_secret("wrench:forge:999")
            assert result is None

    def test_store_secret_calls_create_item(self):
        backend = DummySecretServiceBackend()
        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = False

        with patch.object(backend, "_collection", return_value=mock_coll):
            backend.store_secret(
                "wrench:forge:1", "my-secret-token", label="Wrench: Personal GitHub"
            )
            mock_coll.create_item.assert_called_once_with(
                "Wrench: Personal GitHub",
                {"application": _ATTR_APP, "key": "wrench:forge:1"},
                "my-secret-token",
                replace=True,
            )

    def test_delete_secret_deletes_all_matches(self):
        backend = DummySecretServiceBackend()
        mock_item1 = MagicMock()
        mock_item2 = MagicMock()

        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = False
        mock_coll.search_items.return_value = [mock_item1, mock_item2]

        with patch.object(backend, "_collection", return_value=mock_coll):
            backend.delete_secret("wrench:forge:1")
            mock_item1.delete.assert_called_once()
            mock_item2.delete.assert_called_once()

    def test_collection_unlocks_when_locked(self):
        backend = DummySecretServiceBackend()
        mock_bus = MagicMock()
        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = True

        with (
            patch("secretstorage.dbus_init", return_value=mock_bus),
            patch("secretstorage.get_default_collection", return_value=mock_coll),
        ):
            coll = backend._collection()
            assert coll == mock_coll
            mock_coll.unlock.assert_called_once()

    def test_collection_locked_exception_raises_unavailable(self):
        backend = DummySecretServiceBackend()
        mock_bus = MagicMock()
        mock_coll = MagicMock()
        mock_coll.is_locked.return_value = True
        mock_coll.unlock.side_effect = LockedException("Collection locked")

        with (
            patch("secretstorage.dbus_init", return_value=mock_bus),
            patch("secretstorage.get_default_collection", return_value=mock_coll),
        ):
            with pytest.raises(CredentialBackendUnavailableError) as exc_info:
                backend._collection()
            assert "Dummy backend help text" in str(exc_info.value)

    def test_dbus_not_available_raises_unavailable(self):
        backend_flatpak = FlatpakSecretServiceBackend()
        backend_appimage = AppImageSecretServiceBackend()

        with patch(
            "secretstorage.dbus_init",
            side_effect=SecretServiceNotAvailableException("D-Bus not available"),
        ):
            with pytest.raises(CredentialBackendUnavailableError) as exc_flatpak:
                backend_flatpak._collection()
            with pytest.raises(CredentialBackendUnavailableError) as exc_appimage:
                backend_appimage._collection()

            # Assert remediation texts differ
            assert "Flatseal" in str(exc_flatpak.value)
            assert "gnome-keyring-daemon" in str(exc_appimage.value)
            assert str(exc_flatpak.value) != str(exc_appimage.value)

    def test_get_backend_dispatch(self):
        with patch("wrench.credentials._detect_packaging_context", return_value="flatpak"):
            backend = get_backend()
            assert isinstance(backend, FlatpakSecretServiceBackend)

        with patch("wrench.credentials._detect_packaging_context", return_value="appimage"):
            backend = get_backend()
            assert isinstance(backend, AppImageSecretServiceBackend)

        with patch("wrench.credentials._detect_packaging_context", return_value="bare"):
            backend = get_backend()
            assert isinstance(backend, AppImageSecretServiceBackend)

    def test_detect_packaging_context_logic(self, monkeypatch):
        # 1. Flatpak environment variable
        monkeypatch.setenv("FLATPAK_ID", "io.github.uzair.Wrench")
        monkeypatch.delenv("APPIMAGE", raising=False)
        assert _detect_packaging_context() == "flatpak"

        # 2. Flatpak takes precedence over APPIMAGE
        monkeypatch.setenv("FLATPAK_ID", "io.github.uzair.Wrench")
        monkeypatch.setenv("APPIMAGE", "/path/to/app.AppImage")
        assert _detect_packaging_context() == "flatpak"

        # 3. /.flatpak-info file check
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.delenv("APPIMAGE", raising=False)
        with patch("os.path.exists", side_effect=lambda p: p == "/.flatpak-info"):
            assert _detect_packaging_context() == "flatpak"

        # 4. AppImage environment variable
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.setenv("APPIMAGE", "/path/to/app.AppImage")
        with patch("os.path.exists", return_value=False):
            assert _detect_packaging_context() == "appimage"

        # 5. Bare fallback
        monkeypatch.delenv("FLATPAK_ID", raising=False)
        monkeypatch.delenv("APPIMAGE", raising=False)
        with patch("os.path.exists", return_value=False):
            assert _detect_packaging_context() == "bare"

    def test_get_backend_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        with pytest.raises(NotImplementedError) as exc_info:
            get_backend()
        assert "win32" in str(exc_info.value)

    @pytest.mark.skipif(
        shutil.which("dbus-launch") is None or _detect_packaging_context() != "bare",
        reason="Local developer sanity test only when real dbus is available in bare mode",
    )
    def test_real_backend_smoke(self):
        backend = get_backend()
        assert backend is not None
