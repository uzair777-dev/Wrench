"""FR-13.2 Contrast Gate Test: Assert WCAG contrast ratios on all registered token pairs."""

from wrench.ui.theme import (
    BANNER_STYLES,
    FORGE_BADGE_COLORS,
    GRAPH_LANES,
    create_pastel_dark_palette,
    create_pastel_light_palette,
)


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    """Converts #RGB or #RRGGBB to integer (r, g, b) tuple."""
    hex_clean = hex_str.lstrip("#")
    if len(hex_clean) == 3:
        hex_clean = "".join(c * 2 for c in hex_clean)
    return int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16)


def srgb_channel_to_linear(c_int: int) -> float:
    """WCAG 2.1 sRGB component to linear component conversion."""
    c = c_int / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_str: str) -> float:
    """Computes WCAG relative luminance L = 0.2126*R + 0.7152*G + 0.0722*B."""
    r, g, b = hex_to_rgb(hex_str)
    rl = srgb_channel_to_linear(r)
    gl = srgb_channel_to_linear(g)
    bl = srgb_channel_to_linear(b)
    return 0.2126 * rl + 0.7152 * gl + 0.0722 * bl


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Computes WCAG contrast ratio (L1 + 0.05) / (L2 + 0.05)."""
    l1 = relative_luminance(hex1)
    l2 = relative_luminance(hex2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_base_palettes_text_contrast():
    """Verify window text against window and base backgrounds (>= 4.5:1)."""
    light_pal = create_pastel_light_palette()
    dark_pal = create_pastel_dark_palette()

    # Light mode
    light_win_bg = light_pal.window().color().name()
    light_base_bg = light_pal.base().color().name()
    light_text = light_pal.text().color().name()

    assert contrast_ratio(light_text, light_win_bg) >= 4.5
    assert contrast_ratio(light_text, light_base_bg) >= 4.5

    # Dark mode
    dark_win_bg = dark_pal.window().color().name()
    dark_base_bg = dark_pal.base().color().name()
    dark_text = dark_pal.text().color().name()

    assert contrast_ratio(dark_text, dark_win_bg) >= 4.5
    assert contrast_ratio(dark_text, dark_base_bg) >= 4.5


def test_banner_tokens_contrast():
    """Verify text vs background in all banner styles (>= 4.5:1)."""
    for mode in ("light", "dark"):
        for level, colors in BANNER_STYLES[mode].items():
            ratio = contrast_ratio(colors["fg"], colors["bg"])
            assert ratio >= 4.5, f"Banner {mode} {level} failed contrast: {ratio:.2f} < 4.5"


def test_forge_badge_tokens_contrast():
    """Verify text vs pill background in all forge badges (>= 4.5:1)."""
    for mode in ("light", "dark"):
        for state, (fg, bg) in FORGE_BADGE_COLORS[mode].items():
            ratio = contrast_ratio(fg, bg)
            assert ratio >= 4.5, f"Forge badge {mode} {state} failed contrast: {ratio:.2f} < 4.5"


def test_graph_lane_tokens_contrast():
    """Verify graph lanes against window background (>= 3.0:1 for decorative/graph lines)."""
    light_pal = create_pastel_light_palette()
    dark_pal = create_pastel_dark_palette()
    light_bg = light_pal.window().color().name()
    dark_bg = dark_pal.window().color().name()

    for i, hex_col in enumerate(GRAPH_LANES["light"]):
        ratio = contrast_ratio(hex_col, light_bg)
        assert ratio >= 3.0, f"Light graph lane {i} ({hex_col}) contrast {ratio:.2f} < 3.0"

    for i, hex_col in enumerate(GRAPH_LANES["dark"]):
        ratio = contrast_ratio(hex_col, dark_bg)
        assert ratio >= 3.0, f"Dark graph lane {i} ({hex_col}) contrast {ratio:.2f} < 3.0"
