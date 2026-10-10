import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import "lib/state.js" as Reader
import "lib/copy.js" as Copy
import "lib/tokens.js" as Tokens
import "lib/motion.js" as Motion
import "lib/settings.js" as Settings

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
  property int staleAfterMs: 20000  // W3 heartbeat is 15 s
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
  // {promptId, prompt, timeoutS} while a confirm card waits, else null
  property var confirm: null
  property var points: []
  property var steps: []
  // unified lifecycle stream (contract v2): [{id, kind, label, status,
  // target, reason, undoRef, at, options?, promptId?}]. Supersedes
  // `steps` where a v2 daemon feeds it; `steps` stays for older cores.
  property var actions: []
  property var suggestion: null
  property var guide: null
  // cua.target stream event (docs/IPC_CONTRACT.md): where a CUA click
  // will land, or null. Drives GhostCursor; nothing renders when null.
  property var cuaTarget: null
  property var windowFocus: ({})
  property string goal: ""
  property string goalStatus: ""
  property real level: 0.0
  property var tasks: ({})
  property string error: ""
  property string errorCode: ""
  property var health: ({})
  property var spend: ({})
  property string turnId: ""
  property var seq: null
  property int contractVersion: 1
  // "stream" | "file" | "none"
  property string connection: "none"
  property bool offline: true
  property bool stale: false
  property bool contractNewer: false
  readonly property bool busy: Reader.BUSY.indexOf(status) >= 0
  // The last one-shot action through run(): {verb, pending, ok,
  // message, at} — pending while the subprocess is in flight, then the
  // terminal outcome (daemon refusal text or typed error code mapped
  // to copy). A local refusal (stale pick, full queue) lands here too,
  // so no click is ever silent.
  property var lastAction: null

  // --- copy (wisp/copy.py via lib/copy.js) ----------------------------
  readonly property string statusWord: Copy.statusWord(status)
  readonly property string statusTone: Copy.statusTone(status)
  // The one live-state word every surface shows (pill, console status
  // line, bar tooltip): reconnecting while stale, the typed message on an
  // error, blocked for a blocked turn, else the status word.
  readonly property var wordView: Copy.wordView(status, result, errorCode, stale)
  readonly property var resultView: Copy.translateResult(result)
  readonly property string errorMessage: errorCode !== "" ? Copy.errorMessage(errorCode) : ""
  readonly property string errorHint: errorCode !== "" ? Copy.errorHint(errorCode) : ""
  // One line for banners: offline or newer-contract; "" when fine (a stale
  // turn says so through wordView).
  readonly property string notice: offline ? Copy.string("state.offline")
    : contractNewer ? Copy.string("state.newer") : ""

  // --- tokens and motion (lib/tokens.js, lib/motion.js) ----------------
  property var tokens: Tokens.load("", "", "dark").tokens
  property string tokenSource: "fallback"
  property string themeMode: "dark"
  // Family for text; surfaces and components bind font.family to it.
  readonly property string fontFamily: Style.fontFamily
  readonly property string motionMode: Motion.resolveMode(motionConfig, animationsEnabled)

  // --- settings (W22): one-shot reads, writes through wispd config set ----
  // Loaded when the Panel opens Settings; nothing here polls.
  property var cuaStatus: null       // wispd cua status --json data
  property var spendModels: []       // wispd spend --json models
  property var configValues: ({})    // "section.key" -> value
  property var configErrors: ({})    // key -> message from the daemon or validator
  property string configSaved: ""    // key last written without error

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

  // Reply to the prompt the card shows (or a suggestion-card pick, which
  // needs no prompt id — the daemon resolves those before the broker).
  // A pick the view refuses — answered, timed out, replaced or never
  // offered — still reaches a terminal state: the "that question
  // expired" nudge in lastAction instead of a silent drop.
  function sendChoice(pick, pid) {
    if (!Reader.acceptChoice(root.view, pick, pid)) {
      root.lastAction = { verb: "choice", pending: false, ok: false,
        message: Copy.errorMessage("stale_prompt"), at: Date.now() };
      return false;
    }
    var cmd = [wispd, "choice", pick];
    if (pid) cmd = cmd.concat(["--prompt-id", pid]);
    return run(cmd.concat(["--json"]), "choice");
  }
  // Bar action while offline: start the user service (no daemon to ask).
  function startDaemon() { return run(["systemctl", "--user", "start", "wispd.service"], "daemon"); }
  function interrupt() { return run([wispd, "interrupt", "--json"], "interrupt"); }
  function trigger() { return run([wispd, "trigger", "--json"], "trigger"); }
  function label(verdict) { return run([wispd, "label", "set", verdict, "--json"], "label"); }

  // Read the settings inputs once (config, cua status, spend by model).
  function loadSettings() {
    if (!cfgProc.running) cfgProc.running = true;
    if (!cuaProc.running) cuaProc.running = true;
    if (!spendProc.running) spendProc.running = true;
  }

  // Validate, then `wispd config set KEY VALUE`. A rejected value or a
  // daemon error lands in configErrors[key] and nothing is written.
  function configSet(key, value) {
    var bad = Settings.validate(key, value);
    var errs = {};
    for (var k in configErrors) errs[k] = configErrors[k];
    delete errs[key];
    configSaved = "";
    if (bad !== "") {
      errs[key] = Copy.string(bad);
      configErrors = errs;
      return;
    }
    configErrors = errs;
    setKey = key;
    setValue = String(value).replace(/^\s+|\s+$/g, "");
    setProc.command = Settings.setCommand(wispd, key, value);
    setProc.running = true;
  }

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
  // Actions through run() are serial: while one subprocess is in flight
  // the next commands queue in click order (8 deep — the daemon sees
  // what the user clicked). A click past the cap refuses loudly via
  // lastAction; nothing is dropped silently.
  property var actionQueue: []
  property string actionVerb: ""

  function _launch(cmd, verb) {
    root.actionVerb = verb || "";
    root.lastAction = { verb: root.actionVerb, pending: true,
                        ok: false, message: "", at: Date.now() };
    actionProc.command = cmd;
    actionProc.running = true;
  }

  function run(cmd, verb) {
    if (actionProc.running) {
      if (actionQueue.length >= 8) {
        root.lastAction = { verb: verb || "", pending: false, ok: false,
          message: Copy.errorMessage("busy"), at: Date.now() };
        return false;
      }
      actionQueue = actionQueue.concat([{ cmd: cmd, verb: verb || "" }]);
      return true;
    }
    _launch(cmd, verb);
    return true;
  }

  function finishAction(code) {
    var r = Reader.actionResult(code, actionOut.text, actionErr.text);
    var msg = r.text;
    if (Reader.ERROR_CODES.indexOf(r.error) >= 0)
      msg = Copy.errorMessage(r.error);
    if (msg === "")
      msg = r.ok ? Copy.string("ui.noted") : Copy.errorMessage("internal");
    root.lastAction = { verb: root.actionVerb, pending: false,
                        ok: r.ok, message: msg, at: Date.now() };
    if (root.actionQueue.length > 0) {
      var nxt = root.actionQueue[0];
      root.actionQueue = root.actionQueue.slice(1);
      _launch(nxt.cmd, nxt.verb);
    }
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
    root.confirm = v.confirm;
    root.points = v.points;
    root.steps = v.steps;
    root.actions = v.actions;
    root.suggestion = v.suggestion;
    root.guide = v.guide;
    root.cuaTarget = v.cuaTarget;
    root.windowFocus = v.focus;
    root.goal = v.goal;
    root.goalStatus = v.goalStatus;
    root.level = v.level;
    root.tasks = v.tasks;
    root.error = v.error;
    root.errorCode = v.errorCode;
    root.health = v.health;
    root.spend = v.spend;
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

  property string setKey: ""
  property string setValue: ""

  Process {
    id: setProc
    stderr: StdioCollector { id: setErr }
    onExited: function (code, status) {
      var errs = {};
      for (var k in root.configErrors) errs[k] = root.configErrors[k];
      if (code === 0) {
        delete errs[root.setKey];
        var vals = {};
        for (var j in root.configValues) vals[j] = root.configValues[j];
        vals[root.setKey] = root.setValue;
        root.configValues = vals;
        root.configSaved = root.setKey;
      } else {
        errs[root.setKey] = Settings.errorText(setErr.text) || Copy.string("ui.err.unknown");
      }
      root.configErrors = errs;
    }
  }

  Process {
    id: cfgProc
    command: [root.wispd, "config", "show", "--json"]
    stdout: StdioCollector { id: cfgOut }
    onExited: function (code) {
      if (code !== 0) return;
      try { root.configValues = Settings.flatten(JSON.parse(cfgOut.text)); } catch (e) {}
    }
  }

  Process {
    id: cuaProc
    command: [root.wispd, "cua", "status", "--json"]
    stdout: StdioCollector { id: cuaOut }
    onExited: function (code) {
      // exit 4 (cua selected but down) still carries the data
      try { root.cuaStatus = JSON.parse(cuaOut.text).data || null; } catch (e) { root.cuaStatus = null; }
    }
  }

  Process {
    id: spendProc
    command: [root.wispd, "spend", "--json"]
    stdout: StdioCollector { id: spendOut }
    onExited: function (code) {
      if (code !== 0) return;
      try { root.spendModels = JSON.parse(spendOut.text).data.models || []; } catch (e) {}
    }
  }

  // The one action subprocess (see run/lastAction): stdout+stderr are
  // collected so a daemon refusal or a spawn failure reaches the
  // surfaces as a typed result, never silence.
  Process {
    id: actionProc
    command: [root.wispd, "status"]
    stdout: StdioCollector { id: actionOut }
    stderr: StdioCollector { id: actionErr }
    onExited: function (code, status) { root.finishAction(code); }
  }

  Component.onCompleted: stateView.reload()
}
