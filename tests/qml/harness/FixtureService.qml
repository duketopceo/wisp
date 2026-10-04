import QtQuick
import "../../../shell-plugin/lib/state.js" as Reader
import "../../../shell-plugin/lib/copy.js" as Copy
import "../../../shell-plugin/lib/motion.js" as Motion

// Stand-in for WispService in the snapshot harness: the same property and
// function names components read, filled from a lib/state.js view built from
// a fixture snapshot (tests/fixtures/states/*.json). No Quickshell, no
// sockets, no files. tests/test_components.py checks that every
// `service.X` a component uses exists here and on WispService.
Item {
  id: root

  property var view: Reader.initial()
  property var tokens: ({})
  property string fontFamily: "Liberation Mono"
  // snapshot mode: motion off, so no animation can change a frame
  property string motionConfig: "off"
  property bool animationsEnabled: false

  property string status: "offline"
  property string rawStatus: "offline"
  property string transcript: ""
  property string answer: ""
  property string result: ""
  property var choices: []
  property string promptId: ""
  property var points: []
  property var steps: []
  property var suggestion: null
  property var guide: null
  property string goal: ""
  property string goalStatus: ""
  property real level: 0
  property var tasks: ({})
  property string error: ""
  property string errorCode: ""
  property var health: ({})
  property string turnId: ""
  property bool offline: true
  property bool stale: false
  property bool contractNewer: false
  readonly property bool busy: Reader.BUSY.indexOf(status) >= 0

  readonly property string statusWord: Copy.statusWord(status)
  readonly property string statusTone: Copy.statusTone(status)
  readonly property var resultView: Copy.translateResult(result)
  readonly property string errorMessage: errorCode !== "" ? Copy.errorMessage(errorCode) : ""
  readonly property string errorHint: errorCode !== "" ? Copy.errorHint(errorCode) : ""
  readonly property string notice: offline ? Copy.string("state.offline")
    : stale ? Copy.string("state.stale")
    : contractNewer ? Copy.string("state.newer") : ""
  readonly property string motionMode: Motion.resolveMode(motionConfig, animationsEnabled)

  function ui(key) { return Copy.string(key); }
  function pickLabel(pick) { return Copy.pickLabel(pick); }

  // snapshot: raw state.json object; mods: {offline, stale}
  function load(snapshot, mods) {
    var v = Reader.initial();
    if (mods && mods.offline) {
      v = Reader.markOffline(v, 0);
    } else {
      v = Reader.applySnapshot(v, snapshot, 1000, "stream").view;
    }
    root.view = v;
    root.status = v.status;
    root.rawStatus = v.rawStatus;
    root.transcript = v.transcript;
    root.answer = v.answer;
    root.result = v.result;
    root.choices = v.choices;
    root.promptId = v.promptId;
    root.points = v.points;
    root.steps = v.steps;
    root.suggestion = v.suggestion;
    root.guide = v.guide;
    root.goal = v.goal;
    root.goalStatus = v.goalStatus;
    root.level = v.level;
    root.tasks = v.tasks;
    root.error = v.error;
    root.errorCode = v.errorCode;
    root.health = v.health;
    root.turnId = v.turnId;
    root.offline = v.offline;
    root.contractNewer = v.contractNewer;
    root.stale = !!(mods && mods.stale);
  }
}
