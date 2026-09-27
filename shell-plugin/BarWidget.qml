import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Bar panel for io.github.duketopceo.dim — polls the daemon's state.json
// directly (tiny file; the service kind also watches it). Shows Dim's
// status, last transcript/result, pending choices, and running agents.
Panel {
  id: root
  moduleName: "io.github.duketopceo.dim"
  ipcTarget: "io.github.duketopceo.dim"

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
    : status === "awaiting_choice" ? urgent
    : status === "error" || status === "offline" ? dim
    : fg

  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/dim-agent/state.json";
  }

  function sendChoice(pick) {
    choiceProc.command = ["dimd", "choice", pick];
    choiceProc.running = true;
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
        root.status = s.status || "idle";
        root.transcript = s.transcript || "";
        root.answer = s.answer || "";
        root.result = s.result || "";
        root.choices = s.choices || [];
        root.tasks = s.tasks || {};
        root.error = s.error || "";
      } catch (e) { root.status = "offline"; }
    }
  }

  Timer {
    interval: 500
    running: true
    repeat: true
    onTriggered: stateView.reload()
  }

  Process {
    id: choiceProc
    command: ["dimd", "choice", ""]
  }

  ColumnLayout {
    anchors.fill: parent
    anchors.margins: Style.spacing.panelPadding
    spacing: Style.spacing.md

    Text {
      text: "Dim — " + root.status
      color: root.stateColor
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
      font.bold: true
    }

    Text {
      visible: root.transcript.length > 0
      text: "heard: " + root.transcript
      color: root.fg
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      wrapMode: Text.WordWrap
      Layout.fillWidth: true
    }

    Text {
      visible: root.answer.length > 0
      text: root.answer
      color: root.accent
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      wrapMode: Text.WordWrap
      Layout.fillWidth: true
    }

    Text {
      visible: root.result.length > 0
      text: root.result
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
      Layout.fillWidth: true
    }

    Flow {
      visible: root.choices.length > 0
      Layout.fillWidth: true
      spacing: Style.spacing.sm

      Repeater {
        model: root.choices
        delegate: Button {
          text: modelData
          onClicked: root.sendChoice(modelData)
        }
      }
    }

    Text {
      visible: Object.keys(root.tasks).length > 0
      text: {
        var lines = [];
        for (var k in root.tasks)
          lines.push(k + " [" + root.tasks[k].status + "]");
        return "agents: " + lines.join("  ");
      }
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
      Layout.fillWidth: true
    }
  }
}
