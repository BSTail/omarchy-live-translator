import QtQuick
import qs.Commons
import qs.Ui

// A bordered Button with accent-colored selected text and an explicit idle
// border color. The stock Button uses the theme's subtle `selected-color` and
// `normal-border` tokens; these two overrides make the chosen state and the
// resting border follow the accent (or a caller-supplied `borderColor`)
// instead, without leaving the shell kit.
Ui.Button {
  id: root
  property color borderColor: root.accent

  // Selected text is the accent color (stock honors the theme's
  // `selected-color` token, which is bright foreground, not accent).
  readonly property color _selectedColor: root.accent

  // Idle bordered chrome uses `borderColor` rather than the theme's
  // `normal-border` token, so a button can sit in a colored outline.
  readonly property var _normalBorderSpec: Border.flat(root.borderColor, Style.normalBorderWidth)
}