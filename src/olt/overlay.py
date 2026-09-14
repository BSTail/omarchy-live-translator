"""Floating bilingual overlay (GTK4 layer-shell).

The overlay only renders; the controller drives it through a small JSON line
protocol over stdin. Each line is a command:

    {"cmd": "card", "id": "out-1", "direction": "out",
     "source": "…", "target": "…", "state": "draft"}
    {"cmd": "state", "id": "out-1", "state": "ready"}
    {"cmd": "clear", "id": "out-1"}
    {"cmd": "clear_all"}
    {"cmd": "hint", "text": "reconnecting…"}
"""

from __future__ import annotations

import json
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
from gi.repository import GLib, Gtk, Gtk4LayerShell  # noqa: E402

STATE_COLORS = {
    "draft": "rgba(255,255,255,0.55)",
    "ready": "rgba(255,255,255,0.95)",
    "spoken": "rgba(120,220,140,0.9)",
    "incoming": "rgba(140,190,255,0.95)",
}


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

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.box.set_vexpand(False)
        self.window.set_child(self.box)

        self.hint_label = Gtk.Label(label="")
        self.hint_label.set_wrap(True)
        self.hint_label.set_halign(Gtk.Align.START)
        self.box.append(self.hint_label)

        self.cards: dict[str, Gtk.Box] = {}

        self.window.present()

    # -- rendering ---------------------------------------------------------

    def _label(self, text: str, color: str, size: str = "medium") -> Gtk.Label:
        label = Gtk.Label(label=text)
        label.set_wrap(True)
        label.set_xalign(0.0)
        label.set_selectable(True)
        markup = GLib.markup_escape_text(text)
        if size == "small":
            label.set_markup(f'<span size="small" color="{color}">{markup}</span>')
        else:
            label.set_markup(f'<span color="{color}">{markup}</span>')
        return label

    def card(self, card_id: str, direction: str, source: str, target: str, state: str):
        if card_id in self.cards:
            self.box.remove(self.cards[card_id])
        color = STATE_COLORS.get(state, STATE_COLORS["draft"])

        frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        css = Gtk.CssProvider()
        css.load_from_string(
            "box.card { background: rgba(20,20,24,0.85);"
            " border-radius: 8px; padding: 8px; }"
        )
        frame.add_css_class("card")
        frame.get_style_context().add_provider(css, 800)

        if direction == "out":
            frame.append(self._label(source, "rgba(220,220,220,0.9)", "small"))
            frame.append(self._label(target, color))
        else:
            frame.append(self._label(target, color))
            frame.append(self._label(source, "rgba(220,220,220,0.7)", "small"))

        self.box.append(frame)
        self.cards[card_id] = frame

    def state(self, card_id: str, state: str):
        # Simplest correct approach: re-render the card with the new state.
        # The controller sends full card data on state changes.
        pass

    def clear(self, card_id: str):
        frame = self.cards.pop(card_id, None)
        if frame is not None:
            self.box.remove(frame)

    def clear_all(self):
        for frame in self.cards.values():
            self.box.remove(frame)
        self.cards.clear()

    def hint(self, text: str):
        self.hint_label.set_text(text)
        self.hint_label.set_visible(bool(text))

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
