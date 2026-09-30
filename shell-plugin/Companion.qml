import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons

// Companion — the Clicky-style orb for io.github.duketopceo.wisp.
// A small floating orb anchored bottom-right that breathes while Wisp
// works; clicking expands a card with transcript, answer, and choice
// buttons. Two layer-shell windows: a fullscreen click-through surface
// for [POINT] markers, and a small corner window for the orb itself.
// Bound to $XDG_RUNTIME_DIR/wisp/state.json like WispService, so it
// works whether or not the bar widget is placed.
Item {
  id: root

  property var shell: null
  property var manifest: null
  property bool opened: true   // orb is persistent; expanded card toggles
  property bool expanded: false

  property string status: "offline"
  property string transcript: ""
  property string answer: ""
  property string result: ""
  property var choices: []
  property var points: []
  property bool pointsVisible: false
  property real level: 0.0
  property string error: ""
  property string lastAnswer: ""
  property bool userPinned: false

  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp/state.json";
  }

  function open(payload) { root.opened = true; }
  function close() { root.opened = false; }
  function toggle() { root.opened ? root.close() : root.open(""); }
  function dismiss() {
    root.expanded = false;
    root.close();
  }

  function sendChoice(pick) {
    choiceProc.command = ["wispd", "choice", pick];
    choiceProc.running = true;
  }

  readonly property color orbColor: {
    if (root.status === "error" || root.error.length > 0) return "#e05555";
    if (root.status === "listening") return "#7aa2f7";
    if (["transcribing", "deciding"].indexOf(root.status) >= 0) return "#bb9af7";
    if (["acting", "awaiting_choice"].indexOf(root.status) >= 0) return "#9ece6a";
    if (root.status === "speaking") return "#e0af68";
    if (root.status === "offline") return "#565f89";
    return "#3b4261";
  }

  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: true
    onFileChanged: reload()
    onLoadFailed: root.status = "offline"
    onLoaded: {
      try {
        var s = JSON.parse(stateView.text());
        var newStatus = s.status || "idle";
        var newAnswer = s.answer || "";
        var newChoices = s.choices || [];
        var newError = s.error || "";
        root.status = newStatus;
        root.transcript = s.transcript || "";
        root.answer = newAnswer;
        root.result = s.result || "";
        root.choices = newChoices;
        var pts = s.points || [];
        if (pts.length > 0 &&
            JSON.stringify(pts) !== JSON.stringify(root.points)) {
          root.points = pts;
          root.pointsVisible = true;
          pointsTimer.restart();
        }
        root.level = s.level || 0.0;
        root.error = newError;
        // Clicky-style surfacing: the card pops itself when there's
        // something to show — an answer, a question (choices), or an
        // error — then auto-collapses. Clicking the orb still forces
        // it open; `userPinned` suppresses the auto-hide.
        if (newChoices.length > 0 ||
            (newAnswer.length > 0 && newAnswer !== root.lastAnswer) ||
            newError.length > 0) {
          root.lastAnswer = newAnswer;
          root.expanded = true;
          root.userPinned = false;
          autoHide.restart();
        }
      } catch (e) { root.status = "offline"; }
    }
  }

  Timer {
    id: autoHide
    interval: 15000
    onTriggered: if (!root.userPinned) root.expanded = false
  }

  Timer {
    interval: 500
    running: true
    repeat: true
    onTriggered: stateView.reload()
  }

  Timer {
    id: pointsTimer
    interval: 8000
    onTriggered: root.pointsVisible = false
  }

  Process {
    id: choiceProc
    command: ["wispd", "choice", ""]
  }

  // ── point markers ────────────────────────────────────────────────
  // Fullscreen click-through overlay: logical coords straight from
  // state.json (normalized by the daemon). Visual guidance only —
  // empty input mask so it never eats clicks. Auto-hides after 8s.
  PanelWindow {
    id: pointsWin
    visible: root.pointsVisible && root.points.length > 0
    color: "transparent"
    anchors { left: true; right: true; top: true; bottom: true }
    exclusionMode: ExclusionMode.Ignore
    mask: Region {}
    WlrLayershell.namespace: "wisp-points"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Item {
      id: ptsHost
      anchors.fill: parent

      Repeater {
        model: root.points
        delegate: Item {
          // clamp inside the surface so edge/overshoot coords stay visible
          x: Math.max(16, Math.min(ptsHost.width - 16, modelData.x))
          y: Math.max(16, Math.min(ptsHost.height - 16, modelData.y))
          width: 0; height: 0

          Rectangle {
            x: -14; y: -14
            width: 28; height: 28; radius: 14
            color: "transparent"
            border.color: "#7aa2f7"
            border.width: 3

            SequentialAnimation on scale {
              running: true
              loops: Animation.Infinite
              NumberAnimation { to: 1.2; duration: 600; easing.type: Easing.InOutSine }
              NumberAnimation { to: 1.0; duration: 600; easing.type: Easing.InOutSine }
            }

            Text {
              anchors.centerIn: parent
              text: index + 1
              color: "#7aa2f7"
              font.pixelSize: 12
              font.bold: true
            }
          }

          Rectangle {
            visible: (modelData.label || "").length > 0
            x: 20; y: -12
            width: lbl.implicitWidth + 14
            height: 24
            radius: 6
            color: "#1a1b26"
            border.color: "#3b4261"
            Text {
              id: lbl
              anchors.centerIn: parent
              text: modelData.label || ""
              color: "#c0caf5"
              font.pixelSize: 11
            }
          }
        }
      }
    }
  }

  // ── orb + expanded card ──────────────────────────────────────────
  // Small window hugging bottom-right; grows when the card expands.
  PanelWindow {
    id: orbWin
    visible: root.opened
    color: "transparent"
    anchors { right: true; bottom: true }
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: root.expanded ? 388 : 92
    implicitHeight: root.expanded
      ? cardCol.implicitHeight + 52 : 92
    WlrLayershell.namespace: "wisp-companion"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Item {
      anchors.fill: parent

      // Orb
      Rectangle {
        id: orb
        visible: !root.expanded
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
        width: 44
        height: 44
        radius: 22
        color: root.orbColor
        opacity: 0.9

        SequentialAnimation on scale {
          running: root.status === "listening" || root.status === "speaking"
          loops: Animation.Infinite
          NumberAnimation { to: 1.15; duration: 700; easing.type: Easing.InOutSine }
          NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
        }

        // mic waveform while listening — bars ride state.json `level`
        Row {
          visible: root.status === "listening"
          anchors.centerIn: parent
          spacing: 3
          Repeater {
            model: 5
            Rectangle {
              width: 3
              radius: 1.5
              color: "#c0caf5"
              anchors.verticalCenter: parent.verticalCenter
              // level is 0..~0.3 RMS; stagger so bars wave, not mirror
              height: 4 + Math.min(20, root.level * 90) *
                    (1.0 - 0.5 * Math.abs(index - 2) / 2)
              Behavior on height {
                NumberAnimation { duration: 80 }
              }
            }
          }
        }

        Text {
          anchors.centerIn: parent
          visible: root.status !== "listening"
          text: root.status === "speaking" ? "♪" : "◉"
          font.pixelSize: 18
          color: "#c0caf5"
        }

        // pointer badge: dots when guidance markers are on screen
        Rectangle {
          visible: root.pointsVisible
          anchors.top: parent.top
          anchors.right: parent.right
          width: 14; height: 14; radius: 7
          color: "#7aa2f7"
          Text {
            anchors.centerIn: parent
            text: root.points.length
            color: "#1a1b26"
            font.pixelSize: 9
            font.bold: true
          }
        }

        MouseArea {
          anchors.fill: parent
          onClicked: {
            root.expanded = true;
            root.userPinned = true;
            autoHide.stop();
          }
        }
      }

      // Expanded card
      Rectangle {
        visible: root.expanded
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
        width: 340
        height: cardCol.implicitHeight + 28
        radius: 12
        color: "#1a1b26"
        border.color: "#3b4261"
        border.width: 1

        Column {
          id: cardCol
          anchors.fill: parent
          anchors.margins: 14
          spacing: 8

          Row {
            spacing: 8
            Rectangle {
              width: 10; height: 10; radius: 5
              color: root.orbColor
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              text: "Wisp — " + root.status
              color: "#c0caf5"
              font.pixelSize: 13
              font.bold: true
            }
          }

          Text {
            visible: root.transcript.length > 0
            width: parent.width
            wrapMode: Text.Wrap
            text: "“" + root.transcript + "”"
            color: "#9aa5ce"
            font.pixelSize: 12
            font.italic: true
          }

          Text {
            visible: root.answer.length > 0
            width: parent.width
            wrapMode: Text.Wrap
            text: root.answer
            color: "#c0caf5"
            font.pixelSize: 13
          }

          Text {
            visible: root.answer.length === 0 && root.result.length > 0
            width: parent.width
            wrapMode: Text.Wrap
            text: root.result
            color: "#9aa5ce"
            font.pixelSize: 12
          }

          Text {
            visible: root.error.length > 0
            width: parent.width
            wrapMode: Text.Wrap
            text: root.error
            color: "#e05555"
            font.pixelSize: 12
          }

          Flow {
            width: parent.width
            spacing: 6
            visible: root.choices.length > 0
            Repeater {
              model: root.choices
              Rectangle {
                height: 28
                width: Math.min(160, choiceLabel.implicitWidth + 18)
                radius: 6
                color: "#283457"
                Text {
                  id: choiceLabel
                  anchors.centerIn: parent
                  text: modelData
                  color: "#c0caf5"
                  font.pixelSize: 11
                  elide: Text.ElideRight
                  width: 140
                }
                MouseArea {
                  anchors.fill: parent
                  onClicked: {
                    root.sendChoice(modelData);
                    root.expanded = false;
                  }
                }
              }
            }
          }

          Row {
            spacing: 10
            Text {
              text: "collapse"
              color: "#7aa2f7"
              font.pixelSize: 11
              MouseArea {
                anchors.fill: parent
                onClicked: root.expanded = false
              }
            }
            Text {
              text: "hide orb"
              color: "#565f89"
              font.pixelSize: 11
              MouseArea {
                anchors.fill: parent
                onClicked: root.close()
              }
            }
            Text {
              text: "Super+D to talk"
              color: "#565f89"
              font.pixelSize: 11
            }
          }
        }
      }
    }
  }
}
