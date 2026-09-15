import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "bstail.omatranslate"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
  }

  function refresh() {
    if (panelLoader.item && panelLoader.item.refreshStatus) panelLoader.item.refreshStatus()
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  visible: panelLoader.item && panelLoader.item.label !== ""
  implicitWidth: row.implicitWidth
  implicitHeight: row.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: injectPanel()

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Row {
    id: row
    anchors.fill: parent
    spacing: Style.space(2)

    BarIconButton {
      id: button
      bar: root.bar
      text: panelLoader.item ? panelLoader.item.label : ""
      slotSize: Style.bar.statusSlot
      tooltipText: "OmaTranslate"

      onPressed: function(b) {
        if (!root.bar) return
        if (b === Qt.RightButton) root.refresh()
        else root.togglePanel()
      }
    }

    BarIconButton {
      id: clipButton
      bar: root.bar
      text: "\uf0ea"
      slotSize: Style.bar.statusSlot
      tooltipText: "Translate clipboard to the other language"

      onPressed: function(b) {
        if (b !== Qt.LeftButton) return
        clipProc.running = false
        clipProc.running = true
      }
    }
  }

  Process {
    id: clipProc
    command: ["olt-ctl", "clipboard_translate"]
    onExited: {
      if (!root.bar) return
      if (exitCode === 0) {
        root.bar.showTooltip(clipButton, "Translated → clipboard")
      } else {
        root.bar.showTooltip(clipButton, "Clipboard translate failed")
      }
      clipTimer.restart()
    }
  }

  Timer {
    id: clipTimer
    interval: 2000
    onTriggered: if (root.bar) root.bar.hideTooltip(clipButton)
  }
}
