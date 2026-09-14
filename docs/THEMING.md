# Theming the overlay on Omarchy

How `omarchy-live-translator` themes its GTK4 overlay so it follows the
user's active Omarchy theme dynamically. Reuse this pattern for any future
GTK4 window that must match Omarchy's look.

## Goal

The overlay must match whatever theme the user currently has set — never a
hardcoded palette. Omarchy themes are separate from the GTK theme, so a plain
GTK window does **not** automatically pick up Omarchy's colors. We resolve
them explicitly.

## How Omarchy stores the active theme

- Active theme name: `~/.local/state/omarchy/current/theme.name`
  (a single line, e.g. `theme-event-horizon-rounded`).
- Theme colors: `~/.config/omarchy/themes/<name>/colors.toml`
  (keys like `bg`, `fg`, `light_fg`, `accent`, `green`, `red`, `cyan`, and
  `hyprland_active_border`).
- Surface tokens (borders, spacing, popups, notifications): the same theme's
  `shell.toml`, with `[popups]`, `[notifications]`, etc. The colorful border
  seen on Omarchy panels/notifications comes from `hyprland.active-border`,
  which resolves to the `hyprland_active_border` gradient in `colors.toml`.

## What we do

1. `src/olt/theme.py`:
   - Reads `theme.name` → finds `<theme>/colors.toml`.
   - Returns the raw color tokens (no fallback hardcoding).
   - `border_gradient_css()` converts the Omarchy `hyprland_active_border`
     string into a GTK CSS `linear-gradient(...)`. The Omarchy format is
     Hyprland-style: `rgb(59E1E3) rgb(59E1E3) … 45deg`. We normalize each
     `rgb(hex)` / `#hex` token and append the angle.

2. `src/olt/overlay.py`:
   - Calls `load_theme()` once at startup and builds a `Gtk.CssProvider`
     from the returned colors.
   - If no Omarchy theme is found, falls back to GTK named colors
     (`@theme_bg_color`, `@theme_fg_color`, `@accent_color`,
     `@success_color`) so it still follows the GTK theme.

## Gradient border technique (the colorful ring)

GTK CSS does **not** allow `linear-gradient(...)` in the `border` shorthand.
The working approach is a gradient ring:

- Outer `box.card-border`: `background-image: linear-gradient(...)`,
  `border-radius: 10px`, `padding: 2px`.
- Inner `box.card`: solid `background: alpha(bg, 0.92)`,
  `border-radius: 8px`.

The outer box's padding reveals the gradient as a thin border around the inner
card. This is the same visual language Omarchy uses for notifications and
popups.

## Pitfalls we hit (do not repeat)

1. **Pango markup does not accept GTK named colors.** `set_markup('<span
   color="@theme_fg_color">…')` fails with "should be a color specification".
   Use CSS classes (`label.add_css_class(...)`) instead of markup colors.
2. **GTK CSS does not accept `@theme_fg_color` named colors either** (only
   `@define-color` names, which are deprecated). Resolve to real hex values
   from the Omarchy theme, or use GTK's `@theme_*` only as a last-resort
   fallback.
3. **`linear-gradient` in `border:` is invalid** — GTK reports "Expected a
   valid color". Use the `background-image` + `padding` ring technique above.
4. **`Gtk.main()` / `Gtk.main_quit()` do not exist in GTK4.** Use
   `GLib.MainLoop()` and `loop.run()` / `loop.quit()`.
5. **gtk4-layer-shell must be linked before libwayland-client.** For a Python
   (PyGObject) app, preload it when spawning the overlay:
   `LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so`.
6. **The layer-shell window paints an opaque (black) background by default.**
   Add `window.olt-root { background: transparent; }` (and add the class to the
   window) so only the themed cards render — otherwise a black rectangle
   appears behind the cards.

## Keeping it dynamic

- Read the theme at overlay startup; the overlay is short-lived and restarted
  with the plugin, so a theme change is picked up on next start.
- Never hardcode `#1C1E26` or any theme's specific colors in the overlay.
  All values come from `load_theme()`.
