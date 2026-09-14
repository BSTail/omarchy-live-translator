"""Load the active Omarchy theme colors for the overlay.

The overlay follows the *active* Omarchy theme, not a hardcoded one. It reads
the current theme name from ~/.local/state/omarchy/current/theme.name, then
that theme's colors.toml, and falls back to GTK named colors when unavailable.
"""

from __future__ import annotations

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
                "bright_fg", "accent", "green", "blue", "red"):
        val = data.get(key)
        if isinstance(val, str) and val.startswith("#"):
            out[key] = val
    return out


def load_theme() -> dict:
    """Return {bg, fg, accent, green, ...} for the active Omarchy theme.

    Values are #rrggbb. Empty dict means "fall back to GTK theme".
    """
    name = _active_theme_name()
    if not name:
        return {}
    path = THEMES_DIR / name / "colors.toml"
    return _read_colors(path)
