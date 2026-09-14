"""Load the active Omarchy theme colors for the overlay.

The overlay follows the *active* Omarchy theme, not a hardcoded one. It reads
the current theme name from ~/.local/state/omarchy/current/theme.name, then
that theme's colors.toml, and falls back to GTK named colors when unavailable.

Also exposes the theme's Hyprland active-border gradient (the "colorful border"
seen on Omarchy notifications/panels), converted to GTK CSS linear-gradient.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

HOME = Path.home()
STATE_THEME_NAME = HOME / ".local" / "state" / "omarchy" / "current" / "theme.name"
THEMES_DIR = HOME / ".config" / "omarchy" / "themes"


def _active_theme_name() -> str | None:
    try:
        return STATE_THEME_NAME.read_text().strip() or None
    except OSError:
        return None


def _read_colors(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out = {}
    for key in ("bg", "lighter_bg", "selection", "muted", "fg", "light_fg",
                "bright_fg", "accent", "green", "blue", "red", "cyan",
                "hyprland_active_border"):
        val = data.get(key)
        if isinstance(val, str):
            out[key] = val
    return out


def load_theme() -> dict:
    """Return raw theme tokens (colors + border gradient string)."""
    name = _active_theme_name()
    if not name:
        return {}
    path = THEMES_DIR / name / "colors.toml"
    return _read_colors(path)


def _css_color(hexval: str) -> str:
    """Normalise a color token to a GTK CSS color.

    Accepts "#rrggbb", "#rgb", "rgb(hex)" (Hyprland style), "rgba(...)".
    Returns the CSS color or None if unparseable.
    """
    v = hexval.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", v)
    if m:
        return "#" + m.group(1).lower()
    m = re.fullmatch(r"#([0-9a-fA-F]{3})", v)
    if m:
        return "#" + "".join(c * 2 for c in m.group(1).lower())
    m = re.fullmatch(r"rgb\(\s*([0-9a-fA-F]{6})\s*\)", v)
    if m:
        return "#" + m.group(1).lower()
    return None


def border_gradient_css(theme: dict) -> str | None:
    """Convert the theme's `hyprland_active_border` into CSS linear-gradient.

    The Omarchy format is a Hyprland gradient, e.g.:
        "rgb(59E1E3) rgb(59E1E3) rgb(26BBD9) rgb(26BBD9) rgb(29D398) rgb(29D398) 45deg"
    Returns "linear-gradient(45deg, #59e1e3, ...)" or None.
    """
    raw = theme.get("hyprland_active_border")
    if not raw:
        return None
    tokens = raw.split()
    colors = []
    angle = "45deg"
    for tok in tokens:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)deg", tok)
        if m:
            angle = m.group(0)
            continue
        c = _css_color(tok)
        if c:
            colors.append(c)
    if not colors:
        return None
    return f"linear-gradient({angle}, {', '.join(colors)})"
