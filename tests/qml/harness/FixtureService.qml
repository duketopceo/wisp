import QtQuick
import "../../../shell-plugin/lib/state.js" as Reader
import "../../../shell-plugin/lib/copy.js" as Copy
import "../../../shell-plugin/lib/motion.js" as Motion
import "../../../shell-plugin/lib/run.js" as Run
import "../../../shell-plugin/lib/rate.js" as Rate

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
  property string themeMode: "dark"
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
  property var confirm: null
  property var points: []
  property var drawings: []
  property var steps: []
  property var actions: []
  property var suggestion: null
  property var guide: null
  property var chips: null
  property var cuaTarget: null
  property var note: null
  property string goal: ""
  property string goalStatus: ""
  property real level: 0
  property var tasks: ({})
  property string error: ""
  property string errorCode: ""
  property var health: ({})
  property var spend: ({})
  property var ratePrompt: null
  // the prompted turn id, "" when none: surfaces react to this, not to the
  // object (normalize builds a fresh {turn} on every state message)
  readonly property string ratePromptTurn: ratePrompt ? String(ratePrompt.turn || "") : ""
  // the bar pill's done rating window (WispService.ratingWindowOpen); the
  // single-shot timer mirrors the real one. load() sets the window from the
  // fixture alone (mods.ratingWindow overrides), never from the previous case.
  property bool ratingWindowOpen: false
  property bool pillHover: false
  property alias ratingTimer: ratingTimerItem
  Timer {
    id: ratingTimerItem
    interval: 8000
    repeat: false
    running: root.ratingWindowOpen && !root.pillHover
    onTriggered: root.ratingWindowOpen = false
  }
  // label() calls the harness received, for the pill's thumb tests
  property var labelCalls: []
  property string mic: ""
  property string turnId: ""
  property bool offline: true
  property bool stale: false
  property bool contractNewer: false
  readonly property bool busy: Reader.BUSY.indexOf(status) >= 0
  // mirrors WispService.run (lib/run.js) — 0 as nowMs: the card's
  // duration then comes from entry timestamps alone, snapshot-stable
  readonly property var run: Run.card(actions, status, promptId, stale,
    goal !== "" ? goal : transcript, 0)
  // {verb, pending, ok, message, at} — mirrors WispService.lastAction;
  // the harness never runs actions, so null unless a scene sets it
  property var lastAction: null

  readonly property string statusWord: Copy.statusWord(status)
  readonly property string statusTone: Copy.statusTone(status)
  readonly property var wordView: Copy.wordView(status, result, errorCode, stale)
  readonly property var resultView: Copy.translateResult(result)
  readonly property string errorMessage: errorCode !== "" ? Copy.errorMessage(errorCode) : ""
  readonly property string errorHint: errorCode !== "" ? Copy.errorHint(errorCode) : ""
  readonly property string notice: offline ? Copy.string("state.offline")
    : contractNewer ? Copy.string("state.newer") : ""
  readonly property string motionMode: Motion.resolveMode(motionConfig, animationsEnabled)

  // the bar actions call these; the harness never talks to a daemon
  function trigger() {}
  function interrupt() {}
  function askAbout(text) { return false; }
  function startDaemon() {}
  function sendChoice(pick, pid) { return false; }
  function label(verdict, turn, note) {
    root.labelCalls = root.labelCalls.concat([{ verdict: verdict, turn: turn, note: note }]);
    return true;
  }
  function skipRatePrompt() { return false; }

  function ui(key) { return Copy.string(key); }
  function pickLabel(pick) { return Copy.pickLabel(pick); }

  // snapshot: raw state.json object; mods: {offline, stale}
  function load(snapshot, mods) {
    var v = Reader.initial();
    if (mods && mods.patch) {
      // a variant overrides raw snapshot fields (health, spend, tasks)
      var merged = {};
      for (var sk in snapshot) merged[sk] = snapshot[sk];
      for (var pk in mods.patch) merged[pk] = mods.patch[pk];
      snapshot = merged;
    }
    if (mods && mods.offline) {
      v = Reader.markOffline(v, 0);
    } else {
      v = Reader.applySnapshot(v, snapshot, 1000, "stream").view;
      // a cua.target stream event, through the real reducer
      if (mods && mods.target)
        v = Reader.applyEvent(v, { type: "event", name: "cua.target", data: mods.target }, 1001).view;
    }
    root.view = v;
    root.status = v.status;
    root.rawStatus = v.rawStatus;
    root.transcript = v.transcript;
    root.answer = v.answer;
    root.result = v.result;
    root.choices = v.choices;
    root.promptId = v.promptId;
    root.confirm = v.confirm;
    root.points = v.points;
    root.drawings = v.drawings;
    root.steps = v.steps;
    root.actions = v.actions;
    root.suggestion = v.suggestion;
    root.guide = v.guide;
    root.chips = v.chips;
    root.cuaTarget = v.cuaTarget;
    root.goal = v.goal;
    root.goalStatus = v.goalStatus;
    root.level = v.level;
    root.tasks = v.tasks;
    root.error = v.error;
    root.errorCode = v.errorCode;
    root.health = v.health;
    root.spend = v.spend;
    var rp = v.ratePrompt;
    var rpTurn = rp ? String(rp.turn || "") : "";
    if (rpTurn !== root.ratePromptTurn) root.ratePrompt = rp;
    root.mic = v.mic;
    root.turnId = v.turnId;
    root.offline = v.offline;
    root.contractNewer = v.contractNewer;
    root.stale = !!(mods && mods.stale);
    var win = mods && mods.ratingWindow !== undefined ? mods.ratingWindow
      : Rate.rateable(root.status, root.answer, root.result, root.errorCode);
    root.ratingWindowOpen = !!win && root.status === "done" && !root.offline
      && Rate.rateable(root.status, root.answer, root.result, root.errorCode);
    // a rated card's reply (verb label, turn, status), for receipt scenes
    root.lastAction = mods && mods.lastAction ? mods.lastAction : null;
  }
}
