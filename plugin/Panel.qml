import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "bstail.live-translator"
  ipcTarget: "bstail.live-translator"
  manageIpc: false

  property var anchorItem: null
  property bool openedFromHotkey: false
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  // Label shown on the bar icon: the language glyph is static; the panel
  // keeps the widget visible at all times.
  readonly property string label: "\uf1ab"

  // --- live state (mirrors the controller's /status) ----------------------
  property bool serviceRunning: false
  property string direction: "en-es"
  property bool autoSpeak: false
  property string outputDestination: "speakers"
  property bool incomingEnabled: true
  property string incomingDirection: "es-en"
  property bool multimedia: false
  property bool glossaryEnabled: false
  property var glossaryPhrases: []
  property real glossaryBoost: 3.0
  property bool activationEnabled: false
  property string activationClass: ""
  property string activationTitle: ""

  property bool pending: false

  function open() {
    openedFromHotkey = false
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
    root.refreshStatus()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
    root.refreshStatus()
    Qt.callLater(function() {
      if (root.opened) setCenterHoverRevealSuppressed(true)
    })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "_centerHoverRevealSuppressed" in root.bar)
      root.bar._centerHoverRevealSuppressed = value
  }

  // --- controller bridge --------------------------------------------------

  function refreshStatus() {
    statusProbe.running = false
    statusProbe.running = true
  }

  function applySettings(settings) {
    var msg = { "action": "set", "settings": settings }
    ctlProc.payload = JSON.stringify(msg)
    ctlProc.running = false
    ctlProc.running = true
  }

  function toggleService() {
    var action = root.serviceRunning ? "stop" : "start"
    svcProc.action = action
    svcProc.running = false
    svcProc.running = true
  }

  function copyDiagnostics() {
    root.bar.run("omarchy-launch-floating-terminal-with-presentation olt-ctl diagnostics")
  }

  Process {
    id: statusProbe
    command: ["curl", "-fsS", "--max-time", "3", "http://127.0.0.1:8670/status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        try {
          var d = JSON.parse(String(text || "{}"))
          root.serviceRunning = true
          root.direction = d.direction || "en-es"
          root.autoSpeak = !!d.auto_speak
          root.outputDestination = d.output_destination || "speakers"
          root.incomingEnabled = !!d.incoming_enabled
          root.incomingDirection = d.incoming_direction || "es-en"
          root.multimedia = !!d.multimedia
          if (d.glossary) {
            root.glossaryEnabled = !!d.glossary.enabled
            root.glossaryPhrases = d.glossary.phrases || []
            root.glossaryBoost = Number(d.glossary.boost) || 3.0
          }
          if (d.activation) {
            root.activationEnabled = !!d.activation.enabled
            root.activationClass = d.activation.app_class || ""
            root.activationTitle = d.activation.app_title || ""
          }
        } catch (e) {
          root.serviceRunning = false
        }
      }
    }
    onExited: if (exitCode !== 0) root.serviceRunning = false
  }

  Process {
    id: ctlProc
    property string payload: ""
    command: ["curl", "-fsS", "--max-time", "5",
              "-X", "POST",
              "-H", "Content-Type: application/json",
              "-d", ctlProc.payload,
              "http://127.0.0.1:8670/ctl"]
    onExited: Qt.callLater(root.refreshStatus)
  }

  Process {
    id: svcProc
    property string action: ""
    command: ["systemctl", "--user", svcProc.action,
              "omarchy-live-translator.service", "libretranslate-live.service"]
    onExited: Qt.callLater(root.refreshStatus)
  }

  Timer {
    interval: 4000
    running: root.opened
    repeat: true
    onTriggered: root.refreshStatus()
  }

  // --- panel --------------------------------------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(settingsColumn.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: settingsScroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: settingsColumn.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: settingsColumn
          width: settingsScroll.width
          spacing: Style.space(10)

          // ---- header ----------------------------------------------------
          Item {
            width: parent.width
            height: Style.space(40)

            Text {
              id: headerGlyph
              text: "\uf1ab"
              color: root.serviceRunning ? Style.hoverStateColor(root.bar.foreground, Color.accent) : Qt.darker(root.bar.foreground, 1.5)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.heading
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: headerText
              anchors.left: headerGlyph.right
              anchors.leftMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.spacing.xs

              Text {
                text: "Live Translator"
                color: root.bar.foreground
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
              }

              Text {
                text: root.serviceRunning ? "Running — offline en↔es" : "Stopped"
                color: root.serviceRunning ? Qt.darker(root.bar.foreground, 1.3) : Color.urgent
                font.family: root.bar.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            Button {
              id: headerButton
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: root.serviceRunning ? "Stop" : "Start"
              iconText: "\uf011"
              bordered: true
              foreground: root.bar.foreground
              accent: Color.accent
              fontFamily: root.bar.fontFamily
              onClicked: root.toggleService()
            }
          }

          PanelSeparator {}

          // ---- outgoing --------------------------------------------------
          PanelSectionHeader { text: "OUTGOING" }

          ButtonGroup {
            id: directionGroup
            width: parent.width
            foreground: root.bar.foreground
            background: Color.popups.background
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            value: root.direction
            options: [
              { value: "en-es", label: "EN → ES", tooltip: "You speak English, it speaks Spanish" },
              { value: "es-en", label: "ES → EN", tooltip: "You speak Spanish, it speaks English" }
            ]
            onChanged: function(v) { root.direction = v; root.applySettings({ "direction": v }) }
          }

          Toggle {
            width: parent.width
            label: "Auto-speak"
            description: "Speak the translation automatically after you release F10"
            checked: root.autoSpeak
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.autoSpeak = !root.autoSpeak
              root.applySettings({ "auto_speak": root.autoSpeak })
            }
          }

          Toggle {
            width: parent.width
            label: "Speak through speakers"
            description: "ON: play translation on your speakers (testing). OFF: route to the virtual microphone (calls)."
            checked: root.outputDestination === "speakers"
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.outputDestination = (root.outputDestination === "speakers") ? "virtual_mic" : "speakers"
              root.applySettings({ "output_destination": root.outputDestination })
            }
          }

          PanelSeparator {}

          // ---- incoming --------------------------------------------------
          PanelSectionHeader { text: "INCOMING" }

          Toggle {
            width: parent.width
            label: "Listen for incoming speech"
            description: "Transcribe the other side of the call (holds the mic open)"
            checked: root.incomingEnabled
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.incomingEnabled = !root.incomingEnabled
              root.applySettings({ "incoming_enabled": root.incomingEnabled })
            }
          }

          ButtonGroup {
            id: incomingDirectionGroup
            width: parent.width
            foreground: root.bar.foreground
            background: Color.popups.background
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            value: root.incomingDirection
            options: [
              { value: "es-en", label: "ES → EN", tooltip: "The other person speaks Spanish" },
              { value: "en-es", label: "EN → ES", tooltip: "The other person speaks English" }
            ]
            onChanged: function(v) {
              root.incomingDirection = v
              root.applySettings({ "incoming_direction": v })
            }
          }

          Toggle {
            width: parent.width
            label: "Multimedia mode"
            description: "For videos/voice messages: segments long continuous speech into cards"
            checked: root.multimedia
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.multimedia = !root.multimedia
              root.applySettings({ "multimedia": root.multimedia })
            }
          }

          PanelSeparator {}

          // ---- glossary --------------------------------------------------
          PanelSectionHeader { text: "GLOSSARY" }

          Toggle {
            width: parent.width
            label: "Word boosting"
            description: "Bias recognition toward names and terms you add below"
            checked: root.glossaryEnabled
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.glossaryEnabled = !root.glossaryEnabled
              root.applySettings({ "glossary": { "enabled": root.glossaryEnabled, "phrases": root.glossaryPhrases, "boost": root.glossaryBoost } })
            }
          }

          TextField {
            id: glossaryField
            width: parent.width
            placeholderText: "Add a term, press Enter (e.g. Kowalczyk)"
            foreground: root.bar.foreground
            accent: Color.accent
            font.family: root.bar.fontFamily
            onAccepted: {
              var t = text.trim()
              if (t === "") return
              var list = root.glossaryPhrases.slice()
              if (list.indexOf(t) < 0) list.push(t)
              root.glossaryPhrases = list
              text = ""
              root.applySettings({ "glossary": { "enabled": root.glossaryEnabled, "phrases": root.glossaryPhrases, "boost": root.glossaryBoost } })
            }
          }

          Flow {
            width: parent.width
            spacing: Style.space(6)
            visible: root.glossaryPhrases.length > 0

            Repeater {
              model: root.glossaryPhrases

              Rectangle {
                required property var modelData
                width: chipRow.implicitWidth + Style.space(16)
                height: Style.space(26)
                radius: Style.cornerRadius
                color: Style.hoverFillFor(root.bar.foreground, Color.accent)

                Row {
                  id: chipRow
                  anchors.centerIn: parent
                  spacing: Style.space(8)

                  Text {
                    text: modelData
                    color: root.bar.foreground
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                  }

                  Text {
                    text: "✕"
                    color: Qt.darker(root.bar.foreground, 1.4)
                    font.family: root.bar.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter

                    MouseArea {
                      anchors.fill: parent
                      cursorShape: Qt.PointingHandCursor
                      onClicked: {
                        var list = root.glossaryPhrases.slice()
                        var i = list.indexOf(modelData)
                        if (i >= 0) list.splice(i, 1)
                        root.glossaryPhrases = list
                        root.applySettings({ "glossary": { "enabled": root.glossaryEnabled, "phrases": root.glossaryPhrases, "boost": root.glossaryBoost } })
                      }
                    }
                  }
                }
              }
            }
          }

          PanelSeparator {}

          // ---- activation -------------------------------------------------
          PanelSectionHeader { text: "ACTIVATION" }

          Toggle {
            width: parent.width
            label: "Only translate in the call app"
            description: "Pause when the focused window isn't your call app"
            checked: root.activationEnabled
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: {
              root.activationEnabled = !root.activationEnabled
              root.applySettings({ "activation": { "enabled": root.activationEnabled, "app_class": root.activationClass, "app_title": root.activationTitle } })
            }
          }

          TextField {
            id: activationField
            width: parent.width
            placeholderText: "Window class (e.g. zoom, teams, discord)"
            text: root.activationClass
            foreground: root.bar.foreground
            accent: Color.accent
            font.family: root.bar.fontFamily
            onEditingFinished: {
              root.activationClass = text.trim()
              root.applySettings({ "activation": { "enabled": root.activationEnabled, "app_class": root.activationClass, "app_title": root.activationTitle } })
            }
          }

          PanelSeparator {}

          // ---- diagnostics ------------------------------------------------
          PanelSectionHeader { text: "DIAGNOSTICS" }

          Button {
            width: parent.width
            text: "Open diagnostics"
            iconText: "\uf188"
            bordered: true
            foreground: root.bar.foreground
            accent: Color.accent
            fontFamily: root.bar.fontFamily
            onClicked: root.copyDiagnostics()
          }

          Text {
            width: parent.width
            text: "Opens a terminal with service state, controller status, recent logs, and engine info."
            color: Qt.darker(root.bar.foreground, 1.5)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }
        }
      }
    }
  }
}
