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
  property var steps: []

  readonly property bool busy:
    ["listening", "transcribing", "deciding", "acting"]
      .indexOf(status) >= 0

  function statusWord() {
    switch (root.status) {
    case "listening": return "listening";
    case "transcribing": return "hearing";
    case "deciding": return "thinking";
    case "acting": return "working";
    case "suggestion": return "an idea";
    case "awaiting_choice": return "needs you";
    case "speaking": return "speaking";
    case "error": return "error";
    default: return root.status;
    }
  }

  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp/state.json";
  }

  // The orb is persistent — the shell host calls close()/hide() on
  // overlays for reasons that aren't ours (plugins rescan, panel
  // sweep), so close() only collapses the card. `opened` is accepted
  // for the plugin contract but nothing reads it to hide the orb.
  function open(payload) { root.opened = true; }
  function close() { root.expanded = false; }
  function toggle() { root.expanded = !root.expanded; }
  function dismiss() {
    root.expanded = false;
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
    if (root.status === "suggestion") return "#e0af68";
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
        root.steps = s.steps || [];
        // Surfacing: the card pops while Wisp works (status + step log),
        // on an answer, a question, or an error — then auto-collapses.
        // Clicking the orb pins it open; auto-hide resumes on done.
        if (root.busy || newStatus === "awaiting_choice"
            || newStatus === "suggestion") {
          root.expanded = true;
          root.userPinned = false;
          autoHide.stop();
        } else {
          if (newChoices.length > 0 ||
              (newAnswer.length > 0 && newAnswer !== root.lastAnswer) ||
              newError.length > 0) {
            root.lastAnswer = newAnswer;
            root.expanded = true;
            root.userPinned = false;
          }
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

  Process {
    id: labelProc
    command: ["wispd", "label", "correct"]
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
    visible: true  // persistent — host close() collapses the card only
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

      // Jupiter rings — two arcs orbit the orb while Wisp works
      Item {
        id: rings
        visible: root.busy && !root.expanded
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 24
        width: 44; height: 44

        Rectangle {
          anchors.centerIn: parent
          width: 58; height: 58; radius: 29
          color: "transparent"
          border.color: "#7aa2f7"
          border.width: 1
          opacity: 0.35
        }

        Canvas {
          id: ringA
          anchors.fill: parent
          onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.strokeStyle = "#7aa2f7";
            ctx.lineWidth = 2.5;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, 29, 0, Math.PI * 0.85);
            ctx.stroke();
          }
          onVisibleChanged: requestPaint()
          RotationAnimator on rotation {
            running: root.busy
            from: 0; to: 360; duration: 1100
            loops: Animation.Infinite
          }
        }

        Canvas {
          id: ringB
          anchors.fill: parent
          onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            ctx.strokeStyle = "#bb9af7";
            ctx.lineWidth = 2;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.arc(width / 2, height / 2, 22, Math.PI * 0.4,
                    Math.PI * 1.1);
            ctx.stroke();
          }
          onVisibleChanged: requestPaint()
          RotationAnimator on rotation {
            running: root.busy
            from: 360; to: 0; duration: 1600
            loops: Animation.Infinite
          }
        }
      }

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
          running: root.busy || root.status === "speaking"
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
            Item {
              width: 12; height: 12
              anchors.verticalCenter: parent.verticalCenter
              Canvas {
                anchors.fill: parent
                visible: root.busy
                onPaint: {
                  var ctx = getContext("2d");
                  ctx.reset();
                  ctx.strokeStyle = "#7aa2f7";
                  ctx.lineWidth = 2;
                  ctx.lineCap = "round";
                  ctx.beginPath();
                  ctx.arc(6, 6, 4.5, 0, Math.PI * 1.4);
                  ctx.stroke();
                }
                onVisibleChanged: requestPaint()
                RotationAnimator on rotation {
                  running: root.busy
                  from: 0; to: 360; duration: 800
                  loops: Animation.Infinite
                }
              }
              Rectangle {
                visible: !root.busy
                anchors.centerIn: parent
                width: 10; height: 10; radius: 5
                color: root.orbColor
              }
            }
            Text {
              text: "Wisp — " + root.statusWord()
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

          // live act-loop step log — "screenshot → ok" style, last 4
          Column {
            visible: root.steps.length > 0
            width: parent.width
            spacing: 2
            Repeater {
              model: root.steps
              Text {
                width: parent.width
                text: "› " + modelData
                color: "#565f89"
                font.pixelSize: 10
                font.family: "monospace"
                elide: Text.ElideRight
              }
            }
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
                  text: String(modelData).replace(/^suggestion:/, "")
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
              text: "✓"
              color: "#9ece6a"
              font.pixelSize: 12
              font.bold: true
              MouseArea {
                anchors.fill: parent
                onClicked: {
                  labelProc.command = ["wispd", "label", "correct"];
                  labelProc.running = true;
                }
              }
            }
            Text {
              text: "✗"
              color: "#e05555"
              font.pixelSize: 12
              font.bold: true
              MouseArea {
                anchors.fill: parent
                onClicked: {
                  labelProc.command = ["wispd", "label", "incorrect"];
                  labelProc.running = true;
                }
              }
            }
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
