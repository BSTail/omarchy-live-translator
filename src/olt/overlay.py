"""Floating bilingual overlay (GTK4 layer-shell).

The overlay only renders; the controller drives it through a small JSON line
protocol over stdin. Each line is a command:

    {"cmd": "card", "id": "out-1", "direction": "out",
     "source": "…", "target": "…", "state": "draft"}
    {"cmd": "state", "id": "out-1", "state": "ready"}
    {"cmd": "clear", "id": "out-1"}
    {"cmd": "clear_all"}
    {"cmd": "hint", "text": "reconnecting…"}

All cards live inside a single window (one themed panel). The panel is capped
at the screen height; when more translations arrive than fit, the content
scrolls.

Theming follows the active Omarchy theme: the overlay reads the current
theme's colors.toml (bg/fg/accent/green) and builds a CSS provider from those
colors. If no Omarchy theme is found it falls back to GTK named colors.
"""

from __future__ import annotations

import json
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell  # noqa: E402

from .theme import border_gradient_css, load_theme

STATE_CLASS = {
    "draft": "olt-draft",
    "ready": "olt-ready",
    "spoken": "olt-spoken",
    "incoming": "olt-incoming",
}


def build_css(theme: dict) -> str:
    # All colors come from the active Omarchy theme (read dynamically at
    # startup); nothing here is hardcoded. When no theme token is present we
    # fall back to GTK's own named colors so it still follows the GTK theme.
    bg = theme.get("bg", "@theme_bg_color")
    fg = theme.get("fg", "@theme_fg_color")
    light_fg = theme.get("light_fg", theme.get("fg", "@theme_fg_color"))
    accent = theme.get("accent", "@accent_color")
    green = theme.get("green", "@success_color")

    entries = f"""
box.olt-entry {{
    border-bottom: 1px solid alpha({fg}, 0.12);
    padding-bottom: 6px;
}}
box.olt-entry:last-child {{
    border-bottom: none;
    padding-bottom: 0;
}}
label.olt-src {{ color: alpha({light_fg}, 0.65); font-size: 0.9em; }}
label.olt-target {{ color: {fg}; }}
label.olt-draft {{ color: alpha({fg}, 0.55); }}
label.olt-ready {{ color: {fg}; }}
label.olt-spoken {{ color: {green}; }}
label.olt-incoming {{ color: {accent}; }}
"""

    grad = border_gradient_css(theme)
    if grad:
        # Gradient border: the outer box paints the theme's active-border
        # gradient, the inner card paints the solid theme background, and the
        # outer box's padding reveals the gradient as a thin ring.
        return f"""
window.olt-root {{
    background: transparent;
}}
box.card-border {{
    background-image: {grad};
    border-radius: 10px;
    padding: 2px;
}}
box.card {{
    background: alpha({bg}, 0.92);
    border-radius: 8px;
    padding: 8px;
}}
{entries}
"""
    return f"""
window.olt-root {{
    background: transparent;
}}
box.card-border {{ background: none; padding: 0; }}
box.card {{
    background: alpha({bg}, 0.92);
    border: 1px solid alpha({fg}, 0.15);
    border-radius: 8px;
    padding: 8px;
}}
{entries}
"""


class OverlayApp:
    def __init__(self, position: str):
        self.window = Gtk.Window()
        self.window.set_default_size(420, -1)
        self.window.set_title("olt-overlay")

        Gtk4LayerShell.init_for_window(self.window)
        Gtk4LayerShell.set_layer(self.window, Gtk4LayerShell.Layer.OVERLAY)
        Gtk4LayerShell.set_namespace(self.window, "olt-overlay")
        Gtk4LayerShell.set_keyboard_mode(
            self.window, Gtk4LayerShell.KeyboardMode.NONE
        )

        top = "top" in position
        bottom = "bottom" in position
        left = "left" in position
        right = "right" in position
        if top:
            Gtk4LayerShell.set_anchor(self.window, Gtk4LayerShell.Edge.TOP, True)
        if bottom:
            Gtk4LayerShell.set_anchor(self.window, Gtk4LayerShell.Edge.BOTTOM, True)
        if left:
            Gtk4LayerShell.set_anchor(self.window, Gtk4LayerShell.Edge.LEFT, True)
        if right:
            Gtk4LayerShell.set_anchor(self.window, Gtk4LayerShell.Edge.RIGHT, True)
        Gtk4LayerShell.set_margin(self.window, Gtk4LayerShell.Edge.TOP, 12)
        Gtk4LayerShell.set_margin(self.window, Gtk4LayerShell.Edge.RIGHT, 12)
        Gtk4LayerShell.set_margin(self.window, Gtk4LayerShell.Edge.BOTTOM, 12)
        Gtk4LayerShell.set_margin(self.window, Gtk4LayerShell.Edge.LEFT, 12)

        theme = load_theme()
        self.css = Gtk.CssProvider()
        self.css.load_from_string(build_css(theme))
        Gtk.StyleContext.add_provider_for_display(
            Gtk.Widget.get_display(self.window), self.css, 800
        )

        # The layer-shell window itself must be transparent; otherwise GTK
        # paints a default (black) background behind the themed cards.
        self.window.add_css_class("olt-root")

        # One themed panel holds every translation entry.
        self.border = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.border.add_css_class("card-border")

        self.card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.card_box.add_css_class("card")

        self.hint_label = Gtk.Label(label="")
        self.hint_label.set_wrap(True)
        self.hint_label.set_halign(Gtk.Align.START)
        self.card_box.append(self.hint_label)

        self.entries = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(False)
        self.scroll.set_child(self.entries)
        self.card_box.append(self.scroll)

        self.border.append(self.card_box)
        self.window.set_child(self.border)

        self.cards: dict[str, Gtk.Box] = {}

        self.window.connect("map", lambda *_: self._relayout())

        # Hidden until the first card appears (e.g. F10 press).
        self.window.set_visible(False)

    def _relayout(self) -> None:
        """Keep the newest entry at the top and cap the panel at the monitor
        height so content scrolls instead of overflowing the screen."""
        try:
            monitor = Gtk4LayerShell.get_monitor(self.window)
            if monitor is None:
                return
            geo = monitor.get_geometry()
            # 12px top + 12px bottom layer margins + card padding/border.
            avail = max(120, geo.height - 48)
            natural = self.entries.get_preferred_height()[1]
            self.scroll.set_size_request(-1, min(natural, avail))
            # Newest is prepended at the top; keep it visible.
            adj = self.scroll.get_vadjustment()
            adj.set_value(0)
        except Exception:
            pass

    def _update_visibility(self) -> None:
        visible = bool(self.cards) or bool(self.hint_label.get_text())
        self.window.set_visible(visible)

    # -- rendering ---------------------------------------------------------

    def _label(self, text: str, css_class: str) -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_selectable(True)
        label.add_css_class(css_class)
        return label

    def card(self, card_id: str, direction: str, source: str, target: str, state: str):
        if card_id in self.cards:
            self.entries.remove(self.cards[card_id])
        state_class = STATE_CLASS.get(state, "olt-draft")

        entry = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        entry.add_css_class("olt-entry")

        if direction == "out":
            entry.append(self._label(source, "olt-src"))
            entry.append(self._label(target, state_class))
        else:
            entry.append(self._label(target, state_class))
            entry.append(self._label(source, "olt-src"))

        self.entries.prepend(entry)
        self.cards[card_id] = entry
        self._update_visibility()
        self._relayout()

    def state(self, card_id: str, state: str):
        pass

    def clear(self, card_id: str):
        entry = self.cards.pop(card_id, None)
        if entry is not None:
            self.entries.remove(entry)
        self._update_visibility()

    def clear_all(self):
        for entry in self.cards.values():
            self.entries.remove(entry)
        self.cards.clear()
        self._update_visibility()

    def hint(self, text: str):
        self.hint_label.set_text(text)
        self.hint_label.set_visible(bool(text))
        self._update_visibility()

    # -- stdin protocol ----------------------------------------------------

    def on_line(self, line: str):
        line = line.strip()
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        cmd = msg.get("cmd")
        if cmd == "card":
            self.card(
                msg.get("id", "?"),
                msg.get("direction", "out"),
                msg.get("source", ""),
                msg.get("target", ""),
                msg.get("state", "draft"),
            )
        elif cmd == "clear":
            self.clear(msg.get("id", ""))
        elif cmd == "clear_all":
            self.clear_all()
        elif cmd == "hint":
            self.hint(msg.get("text", ""))

    def run(self):
        GLib.io_add_watch(sys.stdin, GLib.IO_IN, self._stdin_cb)
        self.window.connect("destroy", lambda *_: self.loop.quit())
        self.loop = GLib.MainLoop()
        self.loop.run()

    def _stdin_cb(self, source, condition):
        line = source.readline()
        if not line:
            return GLib.SOURCE_REMOVE
        self.on_line(line)
        return GLib.SOURCE_CONTINUE


def main():
    position = "top-right"
    if len(sys.argv) > 1:
        position = sys.argv[1]
    app = OverlayApp(position)
    app.run()


if __name__ == "__main__":
    main()
