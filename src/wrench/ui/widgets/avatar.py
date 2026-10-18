"""Avatar loader, initials renderer, and avatar widget with disk/memory caching (FR-5.14)."""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from wrench.core import paths
from wrench.storage import forge_accounts, settings
from wrench.ui.theme import get_avatar_bg_color, get_avatar_fg_color, is_dark_theme
from wrench.ui.workers import run_in_background

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 7 * 86400  # 7 days

_author_avatar_url_cache: dict[tuple[str, str, tuple[str, ...]], str | None] = {}


def clear_author_avatar_cache() -> None:
    """Clears the memoized author avatar URL resolution cache."""
    _author_avatar_url_cache.clear()


def resolve_author_avatar_url(
    name: str,
    email: str,
    remote_urls: list[str] | None = None,
    db_conn: sqlite3.Connection | None = None,
) -> str | None:
    """Multi-tier author avatar resolution pipeline (FR-5.14).

    Tiers:
    1. Configured forge accounts in Wrench local storage matching username.
    2. GitHub noreply email address pattern (*@users.noreply.github.com).
    3. GitHub username heuristic when remote URLs point to github.com.
    4. Gravatar fallback strictly gated by 'ui.avatars_gravatar' user setting.
    """
    norm_name = (name or "").strip()
    norm_email = (email or "").strip().lower()
    norm_remotes = tuple(sorted(remote_urls or []))

    is_gravatar_on = False
    if db_conn:
        try:
            is_gravatar_on = settings.get_setting(db_conn, "ui.avatars_gravatar") == "true"
        except Exception:
            is_gravatar_on = False

    cache_key = (norm_name, norm_email, norm_remotes, is_gravatar_on)
    if cache_key in _author_avatar_url_cache:
        return _author_avatar_url_cache[cache_key]

    url: str | None = None

    # Tier 1: Matching configured Wrench forge account
    if db_conn:
        try:
            accounts = forge_accounts.list_accounts(db_conn)
            for acc in accounts:
                if acc.username and (
                    acc.username.lower() == norm_name.lower()
                    or (norm_email and acc.username.lower() == norm_email.split("@")[0].lower())
                ):
                    url = settings.get_setting(db_conn, f"account.{acc.id}.avatar_url")
                    if url:
                        break
        except Exception:
            pass

    # Tier 2: GitHub noreply email pattern
    if not url and norm_email and "users.noreply.github.com" in norm_email:
        clean = norm_email.split("@")[0]
        username = clean.split("+")[-1] if "+" in clean else clean
        if username:
            url = f"https://github.com/{username}.png?size=80"

    # Tier 3: GitHub remote author username heuristic
    if not url and remote_urls:
        has_github = any("github.com" in (r or "").lower() for r in remote_urls)
        if has_github:
            candidate = norm_name
            if candidate and re.match(
                r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$", candidate
            ):
                url = f"https://github.com/{candidate}.png?size=80"

    # Tier 4: Gravatar fallback (strictly gated by ui.avatars_gravatar)
    if not url and is_gravatar_on and norm_email:
        url = get_gravatar_url(norm_email, size=80)

    if len(_author_avatar_url_cache) > 5000:
        _author_avatar_url_cache.clear()

    _author_avatar_url_cache[cache_key] = url
    return url


def get_gravatar_url(email: str, size: int = 80) -> str:
    """Computes Gravatar URL from email using MD5 with 404 fallback."""
    clean_email = email.strip().lower().encode("utf-8")
    email_hash = hashlib.md5(clean_email).hexdigest()
    return f"https://www.gravatar.com/avatar/{email_hash}?d=404&s={size}"


def _extract_initials(name_or_email: str) -> str:
    """Extracts 1 or 2 uppercase initials from a name, username, or email."""
    if not name_or_email:
        return "?"
    text = name_or_email.strip()
    if "@" in text:
        text = text.split("@")[0]
    parts = text.replace("_", " ").replace("-", " ").replace(".", " ").split()
    if not parts:
        return text[:1].upper()
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def render_initials_tile(name_or_email: str, size: int = 40, is_dark: bool = False) -> QPixmap:
    """Renders a circular initials tile using deterministic Catppuccin palette tokens."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    bg_hex = get_avatar_bg_color(name_or_email, is_dark)
    fg_hex = get_avatar_fg_color(is_dark)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Circle background
    painter.setBrush(QColor(bg_hex))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, size, size)

    # Initials text
    initials = _extract_initials(name_or_email)
    painter.setPen(QColor(fg_hex))
    font = painter.font()
    font.setBold(True)
    font.setPixelSize(max(9, int(size * 0.42)))
    painter.setFont(font)
    painter.drawText(0, 0, size, size, Qt.AlignCenter, initials)
    painter.end()

    return pixmap


def _make_circular_pixmap(image: QImage, size: int) -> QPixmap:
    """Downscales image to bucket size and masks it to an anti-aliased circle."""
    scaled = image.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )

    # Crop to exact square if needed
    if scaled.width() != size or scaled.height() != size:
        x_off = (scaled.width() - size) // 2
        y_off = (scaled.height() - size) // 2
        scaled = scaled.copy(x_off, y_off, size, size)

    circle_pm = QPixmap(size, size)
    circle_pm.fill(Qt.transparent)

    painter = QPainter(circle_pm)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawImage(0, 0, scaled)
    painter.end()

    return circle_pm


AVATAR_HEADERS = {
    "User-Agent": "Wrench/1.0 (https://github.com/uzair777-dev/Wrench; contact@wrench.dev)",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}

NEGATIVE_CACHE_TTL = 3600.0  # 1 hour


class AvatarLoader(QObject):
    """Module-level singleton managing memory/disk caches and background avatar downloads."""

    avatar_ready = Signal(str, int)  # (url, size)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mem_cache: dict[tuple[str, int], tuple[QPixmap, float]] = {}
        self._in_flight: set[str] = set()
        self._pending_sizes: dict[str, set[int]] = {}
        self._negative_cache: dict[str, float] = {}

    def get_avatar(
        self,
        url: str | None,
        name_or_email: str,
        size: int = 40,
        is_dark: bool = False,
    ) -> QPixmap:
        """Returns avatar pixmap immediately (cached or initials) and triggers background fetch."""
        # 1. Fallback immediately to initials if no URL
        if not url:
            return render_initials_tile(name_or_email, size=size, is_dark=is_dark)

        # Check negative cache (recent 404 or failure)
        now = time.time()
        fail_time = self._negative_cache.get(url)
        if fail_time is not None:
            if now - fail_time < NEGATIVE_CACHE_TTL:
                return render_initials_tile(name_or_email, size=size, is_dark=is_dark)
            else:
                self._negative_cache.pop(url, None)

        cache_key = (url, size)
        disk_file = self._disk_cache_path(url)
        disk_mtime: float | None = None
        if disk_file.exists():
            try:
                disk_mtime = disk_file.stat().st_mtime
            except OSError:
                disk_mtime = None

        # 2. Check in-memory cache
        if cache_key in self._mem_cache:
            pixmap, mem_time = self._mem_cache[cache_key]
            effective_time = disk_mtime if disk_mtime is not None else mem_time
            is_stale = (now - effective_time) > CACHE_TTL_SECONDS
            if not is_stale:
                return pixmap
            # If stale, trigger background refresh and return current pixmap
            self._trigger_fetch(url, size)
            return pixmap

        # 3. Check disk cache
        if disk_file.exists() and disk_mtime is not None:
            is_stale = (now - disk_mtime) > CACHE_TTL_SECONDS
            image = QImage(str(disk_file))
            if not image.isNull():
                pixmap = _make_circular_pixmap(image, size)
                self._mem_cache[cache_key] = (pixmap, disk_mtime)
                if not is_stale:
                    return pixmap
                # If stale, trigger background refresh and return current disk pixmap
                self._trigger_fetch(url, size)
                return pixmap
            else:
                # Corrupt image on disk -> prune file
                logger.debug("Pruning corrupt avatar cache file: %s", disk_file)
                try:
                    disk_file.unlink()
                except OSError:
                    pass

        # 4. Trigger in-flight background fetch if not already running
        self._trigger_fetch(url, size)

        # 5. Return initials while in-flight or if disk image not available
        return render_initials_tile(name_or_email, size=size, is_dark=is_dark)

    def _trigger_fetch(self, url: str, size: int) -> None:
        self._pending_sizes.setdefault(url, set()).add(size)
        if url not in self._in_flight:
            self._in_flight.add(url)
            run_in_background(
                fn=self._fetch_avatar_bytes,
                url=url,
                on_finished=lambda data: self._on_fetch_success(url, data),
                on_failed=lambda exc: self._on_fetch_failed(url, exc),
            )

    def _disk_cache_path(self, url: str) -> Path:
        cache_dir = paths.cache_dir() / "avatars"
        cache_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return cache_dir / f"{h}.png"

    def _fetch_avatar_bytes(self, url: str) -> bytes:
        """Fetch raw image bytes with standard browser headers."""
        resp = httpx.get(url, headers=AVATAR_HEADERS, timeout=10.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.content

    def _on_fetch_success(self, url: str, data: bytes) -> None:
        self._in_flight.discard(url)
        sizes = self._pending_sizes.pop(url, {40})
        image = QImage()
        if not image.loadFromData(data):
            self._negative_cache[url] = time.time()
            logger.debug("Failed decoding avatar data from %s", url)
            return

        now = time.time()
        # Write to disk cache
        try:
            disk_file = self._disk_cache_path(url)
            image.save(str(disk_file), "PNG")
        except Exception as e:
            logger.debug("Failed writing avatar disk cache: %s", e)

        # Create masked circular pixmap and cache for each requested size
        for s in sizes:
            pixmap = _make_circular_pixmap(image, s)
            self._mem_cache[(url, s)] = (pixmap, now)
            self.avatar_ready.emit(url, s)
        self.avatar_ready.emit(url, 0)

    def _on_fetch_failed(self, url: str, exc: Exception) -> None:
        self._in_flight.discard(url)
        self._pending_sizes.pop(url, None)
        self._negative_cache[url] = time.time()
        logger.debug("Avatar fetch failed silently for %s: %s", url, exc)


_loader_instance: AvatarLoader | None = None


def get_avatar_loader() -> AvatarLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = AvatarLoader()
    return _loader_instance


class AvatarWidget(QLabel):
    """Convenience label widget rendering circular avatars with initials fallback."""

    def __init__(
        self,
        size: int = 40,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._url: str | None = None
        self._name_or_email: str = ""
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

        self._loader = get_avatar_loader()
        self._loader.avatar_ready.connect(self._on_avatar_ready)

    def set_avatar(self, url: str | None, name_or_email: str) -> None:
        self._url = url
        self._name_or_email = name_or_email
        self.setAccessibleName(name_or_email or "Avatar")
        self.setToolTip(name_or_email)
        self._refresh()

    def _refresh(self) -> None:
        is_dark = is_dark_theme(self)
        pm = self._loader.get_avatar(
            self._url,
            self._name_or_email,
            size=self._size,
            is_dark=is_dark,
        )
        self.setPixmap(pm)

    def _on_avatar_ready(self, url: str, size: int) -> None:
        if url == self._url and (size == self._size or size == 0):
            self._refresh()
