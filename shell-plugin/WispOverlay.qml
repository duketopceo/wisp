import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// WispOverlay — bottom-center listening pill for io.github.duketopceo.wisp.
// Spotlight anatomy, not a dialog: lives at the bottom of the focused
// monitor, shows the mic arc + status word + transcript tail, hosts the
// disambiguation chips inline. Watches state.json; the breathing dim is
// kept deliberately faint so the screen stays readable underneath.
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
  readonly property color dim: Qt.darker(fg, 1.6)
  readonly property color accent: Color.accent
  readonly property color canvas: Color.surface
  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp/state.json";
  }

  readonly property string statusWord:
      status === "listening" ? "listening"
    : status === "transcribing" ? "hearing"
    : status === "deciding" ? "thinking"
    : status === "acting" ? "acting"
    : status === "awaiting_choice" ? "which one?"
    : "wisp"

  function open(payload) { root.opened = true; }
  function close() { root.opened = false; }
  function toggle() { root.opened ? root.close() : root.open(""); }
  function dismiss() {
    root.close();
    if (root.shell && typeof root.shell.hide === "function")
      root.shell.hide((root.manifest && root.manifest.id)
                      || "io.github.duketopceo.wisp");
  }

  function sendChoice(pick) {
    choiceProc.command = [Quickshell.env("HOME") + "/.local/bin/wispd", "choice", pick];
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
    command: [Quickshell.env("HOME") + "/.local/bin/wispd", "choice", ""]
  }

  // Faint breathing dim — mic amplitude modulates it (0 = clear, 1 = dark),
  // capped low enough that the screen stays readable.
  Rectangle {
    anchors.fill: parent
    visible: root.opened
    color: "black"
    opacity: root.opened ? 0.08 + root.level * 0.35 : 0
    Behavior on opacity { NumberAnimation { duration: 120 } }
  }

  // The pill — bottom-center, grows with content, click-through shell;
  // the chips inside are the only interactive elements.
  Rectangle {
    id: pill
    visible: root.opened
    anchors {
      bottom: parent.bottom
      bottomMargin: 96
      horizontalCenter: parent.horizontalCenter
    }
    width: Math.min(parent.width * 0.6, pillRow.implicitWidth + 32)
    height: pillRow.implicitHeight + 22
    radius: height / 2
    color: Qt.rgba(canvas.r, canvas.g, canvas.b, 0.92)
    border.color: Qt.rgba(accent.r, accent.g, accent.b,
                          0.35 + root.level * 0.4)
    border.width: 1

    opacity: visible ? 1 : 0
    scale: visible ? 1 : 0.96
    Behavior on opacity { NumberAnimation { duration: 140 } }
    Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }

    Column {
      id: pillRow
      anchors.centerIn: parent
      spacing: 8

      Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 10

        // mic arc — three bars driven by level
        Row {
          anchors.verticalCenter: parent.verticalCenter
          spacing: 2
          Repeater {
            model: 3
            Rectangle {
              anchors.bottom: parent.bottom
              width: 3; radius: 1.5
              height: 4 + root.level * (8 + index * 4)
              color: root.accent
              Behavior on height { NumberAnimation { duration: 80 } }
            }
          }
          height: 14
        }

        Text {
          anchors.verticalCenter: parent.verticalCenter
          text: root.statusWord
          color: root.accent
          font.pixelSize: 13
          font.bold: true
        }

        Text {
          visible: root.transcript.length > 0
          anchors.verticalCenter: parent.verticalCenter
          text: {
            var t = root.transcript;
            return t.length > 80 ? "…" + t.slice(-78) : t;
          }
          color: root.fg
          font.pixelSize: 13
          elide: Text.ElideLeft
          width: Math.min(implicitWidth, 420)
        }
      }

      Row {
        visible: root.choices.length > 0
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 6

        Repeater {
          model: root.choices
          delegate: Rectangle {
            width: chipLbl.implicitWidth + 16
            height: chipLbl.implicitHeight + 8
            radius: height / 2
            color: chipMa.containsMouse
                   ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.3)
                   : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.10)
            border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.5)
            Text {
              id: chipLbl
              anchors.centerIn: parent
              text: modelData
              color: root.fg
              font.pixelSize: 12
            }
            MouseArea {
              id: chipMa
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: { root.sendChoice(modelData); root.close(); }
            }
          }
        }
      }
    }
  }
}
