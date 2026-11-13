"""Tests for SVG Vector Icon Registry (src/wrench/ui/icons.py)."""

from PySide6.QtGui import QIcon, QPixmap

from wrench.ui.icons import get_icon, get_pixmap, list_available_icons


def test_svg_icon_registry_all_keys():
    available = list_available_icons()
    expected = {
        "repo",
        "branch",
        "merge",
        "laptop",
        "cloud",
        "github",
        "tag",
        "stash",
        "pop",
        "fetch",
        "pull",
        "push",
        "undo",
        "redo",
        "terminal",
        "folder",
        "folder_open",
        "file_code",
        "check",
        "warning",
        "search",
        "sliders",
        "external_link",
        "copy",
        "plus",
        "close",
    }
    assert expected.issubset(available)
    assert len(available) >= 26


def test_get_icon_and_pixmap(qapp):
    icon = get_icon("branch", "#89b4fa", size=24)
    assert isinstance(icon, QIcon)
    assert not icon.isNull()

    pix = get_pixmap("branch", "#89b4fa", size=24)
    assert isinstance(pix, QPixmap)
    assert not pix.isNull()
    assert pix.width() == 24 and pix.height() == 24


def test_get_icon_caching_and_custom_color(qapp):
    icon1 = get_icon("cloud", "#a6e3a1", size=16)
    icon2 = get_icon("cloud", "#a6e3a1", size=16)
    assert icon1 is icon2  # cached instance

    icon3 = get_icon("cloud", "#f38ba8", size=16)
    assert icon1 is not icon3  # different color creates new icon


def test_unknown_icon_fallback(qapp):
    icon = get_icon("nonexistent_glyph_xyz", "#cdd6f4", size=16)
    assert isinstance(icon, QIcon)
    assert not icon.isNull()  # fallback icon provided
