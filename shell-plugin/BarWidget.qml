import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar button for io.github.duketopceo.wisp — a small status glyph in the
// bar (colored by daemon state). Left-click opens the popup Panel with
// transcript/answer/choices; right-click toggles a recording.
BarWidget {
  id: root
  moduleName: "io.github.duketopceo.wisp"

  property string status: "offline"
  property string transcript: ""
  property string answer: ""
  property string result: ""
  property var choices: []
  property var tasks: ({})
  property string error: ""

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property color stateColor: status === "listening" ? accent
    : status === "transcribing" || status === "deciding"
      || status === "acting" ? Color.tertiary || accent
    : status === "awaiting_choice" || status === "suggestion" ? urgent
    : status === "error" ? urgent
    : status === "offline" ? dim
    : fg

  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp/state.json";
  }

  readonly property bool opened: panelLoader.item
    ? panelLoader.item.opened === true
    : false

  function open() { if (panelLoader.item) panelLoader.item.open() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }

  function injectPanel() {
    if (!panelLoader.item) return
    panelLoader.item.bar = root.bar
    panelLoader.item.anchorItem = button
    panelLoader.item.hostWidget = root
  }

  visible: true
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.applyState(text)
    onLoadFailed: root.status = "offline"
  }

  Timer {
    interval: 500
    running: true
    repeat: true
    onTriggered: stateView.reload()
  }

  function applyState(raw) {
    try {
      var s = JSON.parse(raw)
      root.status = s.status || "idle"
      root.transcript = s.transcript || ""
      root.answer = s.answer || ""
      root.result = s.result || ""
      root.choices = s.choices || []
      root.tasks = s.tasks || {}
      root.error = s.error || ""
    } catch (e) {
      root.status = "offline"
    }
  }

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

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "✦"
    foreground: root.stateColor
    active: ["listening", "awaiting_choice", "suggestion",
             "acting", "deciding"].indexOf(root.status) >= 0
    tooltipText: {
      var tip = "Wisp — " + root.status
      if (root.transcript) tip += " · heard: " + root.transcript.slice(0, 60)
      if (root.result) tip += " — " + root.result.slice(0, 60)
      tip += "\nclick: details · right-click: record/stop"
      return tip
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.LeftButton) {
        root.toggle()
      } else if (buttonCode === Qt.RightButton) {
        talkProc.running = true
      }
    }
  }

  Process {
    id: talkProc
    command: ["wispd", "trigger"]
  }

  Process {
    id: choiceProc
    command: ["wispd", "choice", ""]
  }

  function sendChoice(pick) {
    choiceProc.command = ["wispd", "choice", pick]
    choiceProc.running = true
  }
}
