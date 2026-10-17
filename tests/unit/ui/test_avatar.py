"""Unit tests for AvatarLoader and AvatarWidget (Phase 4.4)."""

import hashlib
import os
import time
from unittest.mock import patch

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from wrench.core import paths
from wrench.ui.widgets.avatar import (
    AvatarLoader,
    AvatarWidget,
    get_gravatar_url,
    render_initials_tile,
)


@pytest.fixture(autouse=True)
def app():
    instance = QApplication.instance()
    if not instance:
        instance = QApplication([])
    return instance


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path)
    return tmp_path


def test_initials_tile_rendering():
    pm = render_initials_tile("Alice Smith", size=40, is_dark=False)
    assert isinstance(pm, QPixmap)
    assert pm.width() == 40
    assert pm.height() == 40

    pm24 = render_initials_tile("Bob", size=24, is_dark=True)
    assert pm24.width() == 24
    assert pm24.height() == 24


def test_gravatar_url_generation():
    url = get_gravatar_url("Test.User@Example.COM ", size=40)
    expected_hash = hashlib.md5(b"test.user@example.com").hexdigest()
    assert expected_hash in url
    assert "d=404" in url
    assert "s=40" in url


def test_avatar_loader_url_none_returns_initials_immediately():
    loader = AvatarLoader()
    pm = loader.get_avatar(None, "Alice", size=40)
    assert isinstance(pm, QPixmap)
    assert pm.width() == 40


def test_avatar_loader_disk_cache_and_ttl(tmp_cache):
    loader = AvatarLoader()
    test_url = "https://example.com/avatar1.png"

    # Simulate cached PNG
    avatar_dir = tmp_cache / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(test_url.encode("utf-8")).hexdigest()
    cached_file = avatar_dir / f"{key}.png"

    # Write dummy 40x40 valid pixmap
    pm_src = render_initials_tile("Cached", size=40, is_dark=False)
    pm_src.save(str(cached_file), "PNG")

    # Load should hit disk cache without network
    with patch("wrench.ui.widgets.avatar.run_in_background") as mock_bg:
        loaded_pm = loader.get_avatar(test_url, "User", size=40)
        assert loaded_pm.width() == 40
        assert mock_bg.call_count == 0

    # Age file by 8 days (> 7 days TTL)
    old_time = time.time() - (8 * 86400)
    os.utime(cached_file, (old_time, old_time))

    with patch("wrench.ui.widgets.avatar.run_in_background") as mock_bg:
        _ = loader.get_avatar(test_url, "User", size=40)
        # Stale cache triggers background refetch
        assert mock_bg.call_count == 1


def test_avatar_loader_in_flight_deduplication(tmp_cache):
    loader = AvatarLoader()
    test_url = "https://example.com/shared.png"

    with patch("wrench.ui.widgets.avatar.run_in_background") as mock_bg:
        _ = loader.get_avatar(test_url, "User1", size=40)
        _ = loader.get_avatar(test_url, "User2", size=40)
        # Concurrently requested identical url calls run_in_background only ONCE
        assert mock_bg.call_count == 1


def test_avatar_loader_corrupt_disk_file_deleted(tmp_cache):
    loader = AvatarLoader()
    test_url = "https://example.com/corrupt.png"
    avatar_dir = tmp_cache / "avatars"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(test_url.encode("utf-8")).hexdigest()
    corrupt_file = avatar_dir / f"{key}.png"
    corrupt_file.write_bytes(b"NOT_A_VALID_IMAGE_DATA")

    with patch("wrench.ui.widgets.avatar.run_in_background"):
        pm = loader.get_avatar(test_url, "Fallback", size=40)
        assert isinstance(pm, QPixmap)
        assert not corrupt_file.exists()  # Corrupt file pruned


def test_avatar_widget_set_avatar():
    widget = AvatarWidget(size=40)
    widget.set_avatar(None, "Jane Doe")
    assert widget.toolTip() == "Jane Doe"
    assert widget.accessibleName() == "Jane Doe"
    assert widget.pixmap() is not None
    assert widget.pixmap().width() == 40
