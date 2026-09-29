import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons

// WispService — polls the wispd daemon's state.json and exposes it as
// properties. BarWidget and WispOverlay bind to these; the plugin never
// holds the IPC socket itself.
Item {
  id: root

  property var shell: null
  property var manifest: null

  property string status: "offline"
  property string transcript: ""
  property string answer: ""
  property string result: ""
  property var choices: []
  property var points: []
  property real level: 0.0
  property var tasks: ({})
  property string error: ""

  readonly property string stateFile: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    if (!rd || rd.length === 0) rd = "/tmp";
    return rd + "/wisp/state.json";
  }

  function sendChoice(pick) {
    choiceProc.command = ["wispd", "choice", pick];
    choiceProc.running = true;
  }

  function refresh() {
    stateView.reload();
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
        root.points = s.points || [];
        root.level = s.level || 0.0;
        root.tasks = s.tasks || {};
        root.error = s.error || "";
      } catch (e) {
        root.status = "offline";
      }
    }
  }

  // Fallback poll in case file watching misses a transition.
  Timer {
    interval: 500
    running: true
    repeat: true
    onTriggered: stateView.reload()
  }

  Process {
    id: choiceProc
    command: ["wispd", "choice", ""]
  }
}
