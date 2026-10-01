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
  property var steps: []
  property var suggestion: null
  property var focus: ({})
  property string error: ""

  readonly property bool busy: ["listening", "transcribing",
    "deciding", "acting"].indexOf(status) >= 0

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
      root.steps = s.steps || []
      root.suggestion = s.suggestion || null
      root.focus = s.focus || {}
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
      if (root.focus.app) tip += " · " + root.focus.app
      if (root.transcript) tip += " · heard: " + root.transcript.slice(0, 60)
      if (root.steps.length)
        tip += "\nstep " + root.steps.length + ": " +
               String(root.steps[root.steps.length - 1]).slice(0, 70)
      else if (root.result) tip += " — " + root.result.slice(0, 60)
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

  // busy strip — slides under the glyph while the daemon is working
  Rectangle {
    anchors.bottom: button.bottom
    anchors.bottomMargin: -2
    anchors.horizontalCenter: button.horizontalCenter
    width: root.busy ? button.width * 0.7 : 0
    height: 2
    radius: 1
    color: root.stateColor
    opacity: root.busy ? 1 : 0
    Behavior on width { NumberAnimation { duration: 180 } }
    Behavior on opacity { NumberAnimation { duration: 180 } }
  }

  // suggestion/attention badge dot — pending suggestion or choice
  Rectangle {
    visible: root.suggestion !== null
      || root.status === "awaiting_choice"
      || root.status === "suggestion"
    anchors.top: button.top
    anchors.right: button.right
    width: 6
    height: 6
    radius: 3
    color: root.urgent
    SequentialAnimation on opacity {
      running: parent.visible
      loops: Animation.Infinite
      NumberAnimation { to: 0.35; duration: 700 }
      NumberAnimation { to: 1.0; duration: 700 }
    }
  }

  Process {
    id: talkProc
    command: [Quickshell.env("HOME") + "/.local/bin/wispd", "trigger"]
  }

  Process {
    id: choiceProc
    command: [Quickshell.env("HOME") + "/.local/bin/wispd", "choice", ""]
  }

  function sendChoice(pick) {
    choiceProc.command = [Quickshell.env("HOME") + "/.local/bin/wispd", "choice", pick]
    choiceProc.running = true
  }
}
