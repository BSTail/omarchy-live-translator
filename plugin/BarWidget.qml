import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "bstail.live-translator"

  // Green when the translation service is running, muted otherwise.
  readonly property bool running: statusText === "running"
  property string statusText: "unknown"

  property QtObject shell: null

  function refreshStatus() {
    statusProbe.running = false
    statusProbe.running = true
  }

  Process {
    id: statusProbe
    command: ["systemctl", "--user", "is-active", "omarchy-live-translator.service"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var s = String(text || "").trim()
        root.statusText = (s === "active") ? "running" : "stopped"
      }
    }
  }

  Component.onCompleted: root.refreshStatus()

  Timer {
    interval: 5000
    running: true
    repeat: true
    onTriggered: root.refreshStatus()
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    bar: root.bar
    text: "\uf1ab" // fa-language glyph
    tooltipText: root.running ? "Live Translator — running" : "Live Translator — stopped"
    active: root.running
    useActiveColor: false
    onPressed: function(b) {
      if (b === Qt.LeftButton) root.toggleService()
      else if (b === Qt.RightButton) root.refreshStatus()
    }
  }

  function toggleService() {
    var action = root.running ? "stop" : "start"
    var proc = toggleProc
    proc.action = action
    proc.running = false
    proc.running = true
  }

  Process {
    id: toggleProc
    property string action: ""
    command: ["systemctl", "--user", toggleProc.action, "omarchy-live-translator.service", "libretranslate-live.service"]
    onRunningChanged: if (!running) root.refreshStatus()
  }
}