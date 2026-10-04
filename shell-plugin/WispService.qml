import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "lib/state.js" as Reader
import "lib/copy.js" as Copy
import "lib/tokens.js" as Tokens
import "lib/motion.js" as Motion

// WispService: the one reader of wispd state for every surface (Companion,
// Panel, bar widget). Surfaces bind to this object (shell.serviceFor(
// manifest.id)) and never open state.json, the socket or colors.toml
// themselves.
//
// Transport (swappable, the reducer in lib/state.js is transport-neutral):
//   1. push stream: unix socket, {"cmd":"subscribe"}, hello, snapshot,
//      state diffs, events, pings (docs/IPC_CONTRACT.md "Push stream");
//   2. fallback: state.json via FileView (watched; a 2 s poll runs only
//      while a turn is active).
// Contract handling: contract_version (newer than we know is flagged, still
// read), seq (gaps and overflow reconnect for a fresh snapshot), turn_id,
// and a stale flag when a busy turn stops changing for staleAfterMs.
Item {
  id: root

  property var shell: null
  property var manifest: null

  // --- configuration -------------------------------------------------
  property int staleAfterMs: 5000
  property bool streamEnabled: true
  // [ui] motion from config ("full" | "reduced" | "off" | ""), and the
  // Hyprland animations switch; resolved into motionMode.
  property string motionConfig: ""
  property bool animationsEnabled: true

  // --- state (read-only to surfaces) ---------------------------------
  property var view: Reader.initial()
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
  property var windowFocus: ({})
  property string goal: ""
  property string goalStatus: ""
  property real level: 0.0
  property var tasks: ({})
  property string error: ""
  property string errorCode: ""
  property var health: ({})
  property string turnId: ""
  property var seq: null
  property int contractVersion: 1
  // "stream" | "file" | "none"
  property string connection: "none"
  property bool offline: true
  property bool stale: false
  property bool contractNewer: false
  readonly property bool busy: Reader.BUSY.indexOf(status) >= 0

  // --- copy (wisp/copy.py via lib/copy.js) ----------------------------
  readonly property string statusWord: Copy.statusWord(status)
  readonly property string statusTone: Copy.statusTone(status)
  readonly property var resultView: Copy.translateResult(result)
  readonly property string errorMessage: errorCode !== "" ? Copy.errorMessage(errorCode) : ""
  readonly property string errorHint: errorCode !== "" ? Copy.errorHint(errorCode) : ""
  // One line for banners: offline, stale, or newer-contract; "" when fine.
  readonly property string notice: offline ? Copy.string("state.offline")
    : stale ? Copy.string("state.stale")
    : contractNewer ? Copy.string("state.newer") : ""

  // --- tokens and motion (lib/tokens.js, lib/motion.js) ----------------
  property var tokens: Tokens.load("", "", "dark").tokens
  property string tokenSource: "fallback"
  property string themeMode: "dark"
  readonly property string motionMode: Motion.resolveMode(motionConfig, animationsEnabled)

  signal stateApplied(var view)
  signal turnChanged(string turnId)

  readonly property string runtimeDir: {
    var rd = Quickshell.env("XDG_RUNTIME_DIR");
    return (!rd || rd.length === 0) ? "/tmp" : rd;
  }
  readonly property string stateFile: runtimeDir + "/wisp/state.json"
  readonly property string socketPath: runtimeDir + "/wisp/wispd.sock"
  readonly property string wispd: Quickshell.env("HOME") + "/.local/bin/wispd"

  // --- public functions -------------------------------------------------
  function ui(key) { return Copy.string(key); }
  function pickLabel(pick) { return Copy.pickLabel(pick); }

  function sendChoice(pick, pid) {
    var cmd = [wispd, "choice", pick];
    if (pid) cmd = cmd.concat(["--prompt-id", pid]);
    run(cmd);
  }
  function interrupt() { run([wispd, "interrupt"]); }
  function trigger() { run([wispd, "trigger"]); }
  function label(verdict) { run([wispd, "label", verdict]); }

  // Re-read now: fresh stream snapshot when connected, else the file.
  function refresh() {
    if (connection === "stream") reconnect();
    else stateView.reload();
  }
  // Drop the socket and subscribe again (also the resync path).
  function reconnect() {
    attempt = 0;
    sock.connected = false;
    reconnectTimer.interval = 50;
    reconnectTimer.restart();
  }

  // --- internals --------------------------------------------------------
  property int attempt: 0
  property bool refused: false

  function run(cmd) {
    actionProc.command = cmd;
    actionProc.running = true;
  }

  function adopt(r) {
    if (r.refused) refused = true;
    var v = r.view;
    var prevTurn = root.turnId;
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
    root.windowFocus = v.focus;
    root.goal = v.goal;
    root.goalStatus = v.goalStatus;
    root.level = v.level;
    root.tasks = v.tasks;
    root.error = v.error;
    root.errorCode = v.errorCode;
    root.health = v.health;
    root.seq = v.seq;
    root.contractVersion = v.contractVersion;
    root.connection = v.connection;
    root.offline = v.offline;
    root.contractNewer = v.contractNewer;
    root.stale = Reader.isStale(v, Date.now(), root.staleAfterMs);
    root.turnId = v.turnId;
    if (v.turnId !== prevTurn) root.turnChanged(v.turnId);
    root.stateApplied(v);
    if (r.resync && root.connection === "stream") root.reconnect();
  }

  // Stream gone (resync, overflow, restart): keep what we show and let the
  // file fallback or the next subscription supply a snapshot.
  function disconnected() {
    adopt({ view: Reader.markDisconnected(root.view), ok: true, resync: false, refused: false });
  }

  // Socket failing repeatedly with no refusal: the daemon is not running,
  // so a leftover state.json must not be read as live.
  readonly property bool daemonDown: streamEnabled && !refused && attempt >= 2 && connection !== "stream"

  function goOffline() {
    adopt({ view: Reader.markOffline(root.view, Date.now()), ok: true, resync: false, refused: false });
  }

  // --- stream transport -----------------------------------------------
  Socket {
    id: sock
    path: root.socketPath
    connected: root.streamEnabled && !root.refused
    onConnectedChanged: {
      if (connected) {
        root.attempt = 0;
        write(JSON.stringify(Reader.subscribeRequest()) + "\n");
        flush();
      } else if (root.connection === "stream") {
        root.disconnected();
        stateView.reload();
      }
    }
    onError: function (err) {
      root.scheduleReconnect();
      if (root.daemonDown) root.goOffline();
    }
    parser: SplitParser {
      onRead: function (line) {
        root.adopt(Reader.applyMessage(root.view, line, Date.now(), "stream"));
      }
    }
  }

  function scheduleReconnect() {
    if (!streamEnabled) return;
    reconnectTimer.interval = Reader.backoffMs(attempt);
    attempt = attempt + 1;
    reconnectTimer.restart();
  }

  Timer {
    id: reconnectTimer
    repeat: false
    onTriggered: {
      sock.connected = false;
      sock.connected = Qt.binding(function () { return root.streamEnabled && !root.refused; });
    }
  }

  // A refused subscription (older daemon) is retried once a minute.
  Timer {
    interval: 60000
    running: root.refused && root.streamEnabled
    repeat: true
    onTriggered: root.refused = false
  }

  // --- file fallback ----------------------------------------------------
  FileView {
    id: stateView
    path: root.stateFile
    watchChanges: root.connection !== "stream"
    onFileChanged: if (root.connection !== "stream") reload()
    onLoadFailed: if (root.connection !== "stream") root.goOffline()
    onLoaded: {
      if (root.connection === "stream" || root.daemonDown) return;
      try {
        var snap = JSON.parse(stateView.text());
        root.adopt(Reader.applySnapshot(root.view, snap, Date.now(), "file"));
      } catch (e) {
        root.adopt({ view: Reader.applyMessage(root.view, "{bad", Date.now(), "file").view, ok: false, resync: false, refused: false });
      }
    }
  }

  // Poll only while a turn is active and the stream is not carrying it.
  Timer {
    interval: 2000
    running: root.connection !== "stream" && root.status !== "idle" && root.status !== "offline"
    repeat: true
    onTriggered: stateView.reload()
  }

  // Stale check ticks only while busy (nothing to age when idle).
  Timer {
    interval: 1000
    running: root.busy
    repeat: true
    onTriggered: root.stale = Reader.isStale(root.view, Date.now(), root.staleAfterMs)
  }

  // --- theme tokens -----------------------------------------------------
  readonly property string themeDir: Color.currentThemePath

  function loadTokens() {
    var colors = "", shellToml = "";
    try { colors = colorsView.text(); } catch (e) {}
    try { shellToml = shellView.text(); } catch (e) {}
    var t = Tokens.load(colors, shellToml, "dark");
    root.tokens = t.tokens;
    root.tokenSource = t.source;
    root.themeMode = t.mode;
  }

  FileView {
    id: colorsView
    path: root.themeDir + "/colors.toml"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.loadTokens()
    onLoadFailed: root.loadTokens()
  }

  FileView {
    id: shellView
    path: root.themeDir + "/shell.toml"
    watchChanges: true
    onFileChanged: reload()
    onLoaded: root.loadTokens()
  }

  // Omarchy swaps the theme directory and then pushes only these colors,
  // so a file watch alone can miss the change: re-read on either signal.
  Connections {
    target: Color
    function onAccentChanged() { colorsView.reload(); }
    function onBackgroundChanged() { colorsView.reload(); }
    function onForegroundChanged() { colorsView.reload(); }
    function onUrgentChanged() { colorsView.reload(); }
  }

  Process {
    id: actionProc
    command: [root.wispd, "status"]
  }

  Component.onCompleted: stateView.reload()
}
