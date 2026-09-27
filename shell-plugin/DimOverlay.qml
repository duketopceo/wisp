import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// DimOverlay — breathing-dim listening surface for io.github.duketopceo.dim.
// Watches state.json: opens while the daemon is listening/deciding or
// awaiting a choice, closes when it returns to idle/done/error.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: false

  property string status: "offline"
  property string transcript: ""
  property var choices: []
  property real level: 0.0

  readonly property color fg: Color.foreground
  readonly property color accent: Color.accent
  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/dim-agent/state.json";
  }

  function open(payload) { root.opened = true; }
  function close() { root.opened = false; }
  function toggle() { root.opened ? root.close() : root.open(""); }
  function dismiss() {
    root.close();
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id)
                      || "io.github.duketopceo.dim");
  }

  function sendChoice(pick) {
    choiceProc.command = ["dimd", "choice", pick];
    choiceProc.running = true;
  }

  // Follow the daemon lifecycle: show while a listen cycle is active.
  onStatusChanged: {
    var active = ["listening", "transcribing", "deciding",
                  "awaiting_choice", "acting"].indexOf(root.status) >= 0;
    if (active && !root.opened) root.open("");
    if (!active && root.opened) root.close();
  }

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    onFileChanged: reload()
    onLoaded: {
      try {
        var s = JSON.parse(stateView.text());
        root.status = s.status || "idle";
        root.transcript = s.transcript || "";
        root.choices = s.choices || [];
        root.level = s.level || 0.0;
      } catch (e) { root.status = "offline"; }
    }
  }

  Timer {
    interval: 250
    running: root.opened
    repeat: true
    onTriggered: stateView.reload()
  }

  Process {
    id: choiceProc
    command: ["dimd", "choice", ""]
  }

  // Breathing darkness: opacity follows mic amplitude (0 = clear, 1 = dark).
  Rectangle {
    anchors.fill: parent
    visible: root.opened
    color: "black"
    opacity: root.opened ? 0.15 + root.level * 0.55 : 0
    Behavior on opacity { NumberAnimation { duration: 120 } }
  }

  Column {
    visible: root.opened
    anchors.centerIn: parent
    spacing: 12
    width: Math.min(parent.width * 0.5, 640)

    Text {
      anchors.horizontalCenter: parent.horizontalCenter
      text: root.status === "listening" ? "listening…"
          : root.status === "awaiting_choice" ? "which did you mean?"
          : "Dim"
      color: root.accent
      font.family: "sans-serif"
      font.pixelSize: 22
    }

    Text {
      visible: root.transcript.length > 0
      width: parent.width
      horizontalAlignment: Text.AlignHCenter
      wrapMode: Text.WordWrap
      text: root.transcript
      color: root.fg
      font.family: "sans-serif"
      font.pixelSize: 15
    }

    Row {
      visible: root.choices.length > 0
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: 8

      Repeater {
        model: root.choices
        delegate: Button {
          text: modelData
          onClicked: {
            root.sendChoice(modelData);
            root.close();
          }
        }
      }
    }
  }
}
