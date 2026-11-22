import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import "lib/state.js" as Reader
import "lib/copy.js" as Copy
import "lib/tokens.js" as Tokens
import "lib/motion.js" as Motion
import "lib/settings.js" as Settings
import "lib/run.js" as Run
import "lib/rate.js" as Rate
import "lib/bar.js" as B
import "lib/scribble.js" as Scribble
import "lib/dev.js" as Dev
import "lib/metrics.js" as Metrics

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
  property var drawings: []
  property var steps: []
  // unified lifecycle stream (contract v2): [{id, kind, label, status,
  // target, reason, undoRef, at, options?, promptId?}]. Supersedes
  // `steps` where a v2 daemon feeds it; `steps` stays for older cores.
  property var actions: []
  property var teach: null
  property var suggestion: null
  property var guide: null
  property var chips: null
  // paper surface (gap-closure U1): live note payload or null
  // {convId, path, raw, objects, plan, closed, rendered}
  property var note: null
  // cua.target stream event (docs/IPC_CONTRACT.md): where a CUA click
  // will land, or null. Drives the cursor buddy; nothing renders when null.
  property var cuaTarget: null
  // composer stream event: bumped each time the daemon asks the companion
  // to open the typed composer (double Control); the host reacts to it.
  property int composerSeq: 0
  property var windowFocus: ({})
  property string goal: ""
  property string goalStatus: ""
  property real level: 0.0
  property var tasks: ({})
  property string error: ""
  property string errorCode: ""
  property var health: ({})
  property var spend: ({})
  // {turn} while a wrong rating waits for its optional note (state.rate_prompt)
  property var ratePrompt: null
  // the prompted turn id, "" when none: surfaces react to this, not to the
  // object (normalize builds a fresh {turn} on every state message)
  readonly property string ratePromptTurn: ratePrompt ? String(ratePrompt.turn || "") : ""
  // The bar pill's done rating window (U3): true for 8 s after a rateable
  // turn finishes, closed by ratingTimer, a new turn or going offline.
  // `pillHover` is set by the bar while the pointer is on the pill and
  // pauses the window.
  property bool ratingWindowOpen: false
  property bool pillHover: false
  // Scribble holds the whole screen while listening (OverlayLayer mask). The
  // hold is the grab itself: taken on the listening edge, dropped when the
  // turn leaves listening, is cancelled or interrupted, and by scribbleTimer
  // a few seconds after the last stroke even if every signal is lost.
  property bool scribbleHeld: false
  function scribbleTouch() { if (scribbleHeld) scribbleTimer.restart(); }
  property string mic: ""     // "open" while the opt-in wake word listens
  property string turnId: ""
  property var seq: null
  property int contractVersion: 1
  // "stream" | "file" | "none"
  property string connection: "none"
  property bool offline: true
  property bool stale: false
  property bool contractNewer: false
  readonly property bool busy: Reader.BUSY.indexOf(status) >= 0
  // The newest run in the action stream (U8): intent, step cursor,
  // in-flight step, outcome + mutation count, live ask_user question.
  // {present, active, intent, key, steps, current, outcome, durationS,
  // mutations, undoRefs, question} — lib/run.js; surfaces show nothing
  // when present is false (empty stream, daemon restart).
  readonly property var run: Run.card(actions, status, promptId, stale,
    goal !== "" ? goal : transcript, Date.now())
  // The last one-shot action through runAction(): {verb, pending, ok,
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
  // Text-size multiplier for every surface, 1 to 2. One source for
  // the in-shell plugin and the standalone configs: WISP_TEXT_SCALE in the
  // shell's environment (unset or bad reads 1).
  readonly property real textScale: Metrics.textScale(Quickshell.env("WISP_TEXT_SCALE"))
  readonly property string motionMode: Motion.resolveMode(motionConfig, animationsEnabled)

  // --- settings (W22): one-shot reads, writes through wispd config set ----
  // Loaded when the Panel opens Settings; nothing here polls.
  property var cuaStatus: null       // wispd cua status --json data
  property var spendModels: []       // wispd spend --json models
  property var configValues: ({})    // "section.key" -> value
  property var configErrors: ({})    // key -> message from the daemon or validator
  property string configSaved: ""    // key last written without error
  // settings window: per-key write state, "queued" | "saving" |
  // "saved" | "error" (lib/settings.js write queue rules)
  property var configState: ({})
  property var configQueue: []       // [{key, value}] waiting, one per key
  // the config read exited (any code); configReadError is its first
  // stderr line when it failed, "" otherwise
  property bool configLoaded: false
  property string configReadError: ""
  property bool configAgain: false   // a read was asked for while one ran
  // exit of the one-shot `wispd status --json`: -1 not read yet, 3 = the
  // daemon is down (settings still read and write config.toml)
  property int statusCode: -1
  readonly property bool settingsOffline: statusCode === 3
  // connector list (`wispd connect list --json`, data.connectors):
  // [{alias, name, connected}], its read state ("loading" | "ready" |
  // "failed"), and the alias being connected with its per-alias errors
  property var connectorList: []
  property string connectorState: "loading"
  property string connectorError: ""
  property string connectorRunning: ""
  property var connectorErrors: ({})

  // B31: one local-only recap read per panel open, never a poll.
  // --claim reserves that completed week before the card is delivered.
  property var weeklyRecap: null
  property bool recapReadRequested: false
  property bool recapSuppressed: false
  property bool recapVisible: false
  onRecapVisibleChanged: { if (recapVisible) root.loadRecap(); }
  readonly property bool recapEnabled: configValues["growth.weekly_recap"] === "true"
  onRecapEnabledChanged: {
    if (!recapEnabled) weeklyRecap = null;
    else recapSuppressed = false;
  }

  // --- dev tab: local only, behind `[dev] panel` or a dev session ------
  // One `wispd dev turns --json` and one `wispd dev runs --json` call per tab
  // open and per refresh press, never on a timer and never with both off.
  readonly property bool devPanel: configValues["dev.panel"] === "true"
  // the dev session (state.dev), and whether the Dev tab exists: the session
  // is on or the flag is
  readonly property bool devOn: Dev.sessionOn(view.raw)
  readonly property int devRunsLeft: Dev.runsLeft(view.raw)
  readonly property bool devTab: devPanel || devOn
  // `wispd dev runs --json`, read with the turns on tab open and refresh
  property var devRuns: null
  property bool devRunsLoading: false
  property string devRunsError: ""
  property var devData: null         // parsed reply data, null until read
  property bool devLoading: false
  property string devError: ""       // "" when fine, else a short code

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
    // The pick can be typed free text: it goes to the child's stdin, never
    // onto the command line, which other local accounts can read.
    var cmd = [wispd, "choice", "--stdin"];
    if (pid) cmd = cmd.concat(["--prompt-id", pid]);
    return runAction(cmd.concat(["--json"]), "choice", null, String(pick));
  }
  // Bar action while offline: start the user service (no daemon to ask).
  function startDaemon() { return runAction(["systemctl", "--user", "start", "wispd.service"], "daemon"); }
  // Interrupt never rides the action queue — an emergency stop that
  // waits for 8 pending picks is no stop at all.
  property bool stopPending: false
  function interrupt() {
    // let go at once: the stop must not wait on the daemon to give the
    // screen back, and a cancelled turn gets no rating window
    scribbleHeld = false;
    ratingWindowOpen = false;
    if (stopProc.running) return true;
    stopPending = true;
    stopProc.command = [wispd, "interrupt", "--json"];
    stopProc.running = true;
    return true;
  }
  function trigger() { return runAction([wispd, "trigger", "--json"], "trigger"); }
  // A click on a part of a 3D card (B13): one typed question, a normal turn.
  function askAbout(text) { return runAction([wispd, "ask", "--stdin", "--json"], "ask", null, String(text)); }
  // Scribble to ask (B7): the strokes drawn while listening, handed to the
  // daemon as a small file (wispd scribble). Its own subprocess: it must not
  // queue behind, or flash a result in, the one action slot. A newer payload
  // replaces one still waiting.
  property var scribblePending: null
  function scribble(payload) {
    if (scribbleProc.running) { root.scribblePending = payload; return; }
    root.sendScribble(payload);
  }
  function sendScribble(p) {
    scribbleProc.command = p.strokes.length === 0
      ? [root.wispd, "scribble", "clear", "--json"]
      : [root.wispd, "scribble", "set", "--json", JSON.stringify(p)];
    scribbleProc.running = true;
  }
  // Rate a turn (U2): `turn` names the card's turn, `note` re-labels it with
  // a typed note. The reply's typed status and the turn ride lastAction, so
  // the card that asked can show its own receipt.
  function label(verdict, turn, note) {
    return runAction(Rate.labelCommand(wispd, verdict, turn || "", note || ""),
                     "label", { turn: turn || "", verdict: verdict },
                     note ? String(note) : null);
  }
  // Esc on the note: close it without writing a label.
  function skipRatePrompt() { return runAction(Rate.skipCommand(wispd), "label-skip"); }

  // Read the settings inputs once (config, cua status, spend by model).
  function loadSettings() {
    if (!cfgProc.running) cfgProc.running = true;
    if (!cuaProc.running) cuaProc.running = true;
    if (!spendProc.running) spendProc.running = true;
  }

  // Settings window: open and Retry. Reruns the config and status reads;
  // the pages show their loading line until the config read exits.
  function retrySettings() {
    root.configLoaded = false;
    root.configReadError = "";
    root.statusCode = -1;
    readConfig();
    if (!statusProc.running) statusProc.running = true;
  }

  function readConfig() {
    if (cfgProc.running) root.configAgain = true;
    else cfgProc.running = true;
  }

  function loadConnectors() {
    root.connectorState = "loading";
    root.connectorError = "";
    if (!connListProc.running) connListProc.running = true;
  }

  // `wispd connect add ALIAS` for one connector at a time; success re-reads
  // the list, a failure leaves the stderr sentence on that alias's row.
  function connectAdd(alias) {
    if (connAddProc.running || alias === "") return false;
    var errs = {};
    for (var k in root.connectorErrors) if (k !== alias) errs[k] = root.connectorErrors[k];
    root.connectorErrors = errs;
    root.connectorRunning = alias;
    connAddProc.command = [wispd, "connect", "add", alias];
    connAddProc.running = true;
    return true;
  }

  function finishConnect(code, stderr) {
    var alias = root.connectorRunning;
    if (alias === "") return;
    root.connectorRunning = "";
    if (code === 0) { loadConnectors(); return; }
    var errs = Settings.clone(root.connectorErrors);
    errs[alias] = Settings.errorText(stderr) || Copy.string("ui.err.unknown");
    root.connectorErrors = errs;
  }

  // Read the config alone (the Panel needs `[dev] panel` before it knows
  // whether the Dev tab exists).
  function loadConfig() {
    root.weeklyRecap = null;
    root.recapReadRequested = true;
    if (!cfgProc.running) cfgProc.running = true;
  }

  function loadRecap() {
    if (!root.recapVisible || !root.recapEnabled || root.recapSuppressed
        || root.weeklyRecap || recapProc.running) return;
    recapProc.running = true;
  }

  function finishRecap(code, text) {
    root.weeklyRecap = null;
    if (code !== 0 || !root.recapEnabled || root.recapSuppressed) return;
    try {
      var reply = JSON.parse(text);
      if (reply.ok && reply.data && reply.data.enabled)
        root.weeklyRecap = reply.data.card || null;
    } catch (e) {}
  }

  function disableRecap() {
    root.weeklyRecap = null;
    // Do not let a claim already in flight restore the card after off.
    root.recapSuppressed = true;
    return runAction([root.wispd, "recap", "--off", "--json"], "recap-off");
  }

  // The Dev tab's reads (turns, then runs). Refused unless the flag or the
  // session is on.
  function loadDev() {
    if (!devTab) return;
    if (!devProc.running) {
      devLoading = true;
      devError = "";
      devProc.command = Dev.command(wispd);
      devProc.running = true;
    }
    if (!devRunsProc.running) {
      devRunsLoading = true;
      devRunsError = "";
      devRunsProc.command = Dev.runsCommand(wispd);
      devRunsProc.running = true;
    }
  }

  // Validate, then `wispd config set KEY VALUE`. A rejected value or a
  // daemon error lands in configErrors[key] and nothing is written. The
  // value is put in schema format first (8 -> 8.00). Writes run one at a
  // time through a FIFO with one entry per key; a write for a key that is
  // queued or saving is ignored.
  function configSet(key, value) {
    var states = configState;
    if (states[key] === "queued" || states[key] === "saving") return;
    value = Settings.formatValue(key, value);
    var bad = Settings.validate(key, value);
    var errs = Settings.clone(configErrors);
    delete errs[key];
    configSaved = "";
    if (bad !== "") {
      errs[key] = Copy.string(bad);
      configErrors = errs;
      configState = Settings.finishWrite(states, key, false);
      return;
    }
    configErrors = errs;
    var q = Settings.enqueueWrite(configQueue, states, key, value);
    configQueue = q.queue;
    configState = q.states;
    pumpConfig();
  }

  // The running write ended: record its state, then start the next one.
  // Ends the write in flight. The next queued write starts from setProc's
  // runningChanged (once the process has really stopped), never from here,
  // so a late running=false cannot be taken for the next write's failure.
  function finishSet(code, stderr) {
    if (!setActive) return;
    setActive = false;
    var errs = Settings.clone(configErrors);
    var ok = code === 0;
    if (ok) {
      delete errs[setKey];
      var vals = Settings.clone(configValues);
      vals[setKey] = setValue;
      configValues = vals;
      configSaved = setKey;
    } else {
      errs[setKey] = Settings.errorText(stderr) || Copy.string("ui.err.unknown");
    }
    configErrors = errs;
    configState = Settings.finishWrite(configState, setKey, ok);
    if (ok) configDirty = true;
  }

  // Start the oldest queued write when none is running.
  function settleSet() {
    if (setProc.running) return;
    if (setActive) finishSet(127, "");
    pumpConfig();
  }

  // Start the oldest queued write. When none is left, read the config once
  // so the rows show the daemon's values after a burst of writes.
  function pumpConfig() {
    if (setProc.running || setActive) return;
    var n = Settings.nextWrite(configQueue, configState);
    if (n.write === null) {
      if (configDirty) { configDirty = false; readConfig(); }
      return;
    }
    configQueue = n.queue;
    configState = n.states;
    setKey = n.write.key;
    setValue = n.write.value;
    setProc.command = Settings.setCommand(wispd, n.write.key, n.write.value);
    setActive = true;
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
  // Actions through runAction() are serial: while one subprocess is in flight
  // the next commands queue in click order (8 deep — the daemon sees
  // what the user clicked). A click past the cap refuses loudly via
  // lastAction; nothing is dropped silently.
  property var actionQueue: []
  property string actionVerb: ""

  property var actionMeta: ({})
  // Private text for the in-flight action's stdin (null: none). Typed
  // answers and notes ride here, not in argv, which other local accounts
  // can read while the process runs. One line: newlines become spaces.
  property var actionStdin: null

  function _line(s) { return s === null || s === undefined ? null : String(s).replace(/[\r\n]+/g, " "); }

  function writeActionStdin() {
    if (root.actionStdin !== null) actionProc.write(root.actionStdin + "\n");
    root.actionStdin = null;
  }

  function _launch(cmd, verb, meta, stdin) {
    root.actionStdin = _line(stdin);
    root.actionVerb = verb || "";
    root.actionMeta = meta || {};
    root.lastAction = { verb: root.actionVerb, pending: true,
                        ok: false, message: "", at: Date.now(),
                        turn: root.actionMeta.turn || "", verdict: root.actionMeta.verdict || "" };
    actionProc.command = cmd;
    actionProc.running = true;
  }

  function runAction(cmd, verb, meta, stdin) {
    if (actionProc.running) {
      if (actionQueue.length >= 8) {
        root.lastAction = { verb: verb || "", pending: false, ok: false,
          message: Copy.errorMessage("busy"), at: Date.now() };
        return false;
      }
      actionQueue = actionQueue.concat([{ cmd: cmd, verb: verb || "", meta: meta || {}, stdin: stdin }]);
      return true;
    }
    _launch(cmd, verb, meta, stdin);
    return true;
  }

  function finishAction(code) {
    if (!root.lastAction || root.lastAction.pending !== true) return;
    var r = Reader.actionResult(code, actionOut.text, actionErr.text);
    var msg = r.text;
    if (Reader.ERROR_CODES.indexOf(r.error) >= 0)
      msg = Copy.errorMessage(r.error);
    if (msg === "")
      msg = r.ok ? Copy.string("ui.noted") : Copy.errorMessage("internal");
    root.lastAction = { verb: root.actionVerb, pending: false,
                        ok: r.ok, message: msg, at: Date.now(), status: r.status || "",
                        turn: root.actionMeta.turn || "", verdict: root.actionMeta.verdict || "" };
    if (root.actionQueue.length > 0) {
      var nxt = root.actionQueue[0];
      root.actionQueue = root.actionQueue.slice(1);
      _launch(nxt.cmd, nxt.verb, nxt.meta, nxt.stdin);
    }
  }

  function adopt(r) {
    if (r.refused) refused = true;
    var v = r.view;
    var prevTurn = root.turnId;
    var prevStatus = root.status;
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
    root.teach = v.teach;
    root.suggestion = v.suggestion;
    root.guide = v.guide;
    root.chips = v.chips;
    root.note = v.note;
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
    var rp = v.ratePrompt;
    var rpTurn = rp ? String(rp.turn || "") : "";
    if (rpTurn !== root.ratePromptTurn) root.ratePrompt = rp;
    root.mic = v.mic;
    root.seq = v.seq;
    root.contractVersion = v.contractVersion;
    root.connection = v.connection;
    root.offline = v.offline;
    root.contractNewer = v.contractNewer;
    root.stale = Reader.isStale(v, Date.now(), root.staleAfterMs);
    root.turnId = v.turnId;
    var win = B.windowAction(prevStatus, root.status, prevTurn, v.turnId, root.offline,
      Rate.rateable(root.status, root.answer, root.result, root.errorCode), root.errorCode);
    var hold = Scribble.holdAction(prevStatus, root.status, root.errorCode, prevTurn, v.turnId);
    if (hold === "grab") root.scribbleHeld = true;
    else if (hold === "release") root.scribbleHeld = false;
    if (win === "open") root.ratingWindowOpen = true;
    else if (win === "close") root.ratingWindowOpen = false;
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
        if (line.indexOf("\"composer\"") >= 0) {
          try {
            var m = JSON.parse(line);
            if (m && m.type === "event" && m.name === "composer" && m.data && m.data.action === "open")
              root.composerSeq = root.composerSeq + 1;
          } catch (e) {}
        }
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

  // The done rating window: one single-shot, armed on the done edge (the
  // window opening), paused while the pill is hovered, off once it fires or
  // a new turn closes the window. Never runs at idle.
  Timer {
    id: ratingTimer
    interval: B.WINDOW_MS
    repeat: false
    running: root.ratingWindowOpen && !root.pillHover
    onTriggered: root.ratingWindowOpen = false
  }

  // The hard cap on a scribble hold: single-shot, runs only while held, so
  // a lost release signal gives the screen back (click-through) in seconds.
  Timer {
    id: scribbleTimer
    interval: Scribble.HOLD_MS
    repeat: false
    running: root.scribbleHeld
    onTriggered: root.scribbleHeld = false
  }

  // Stale check ticks only while busy (nothing to age when idle).
  Timer {
    interval: 1000
    running: root.busy
    repeat: true
    onTriggered: root.stale = Reader.isStale(root.view, Date.now(), root.staleAfterMs)
  }

  // --- theme tokens -----------------------------------------------------
  readonly property string themeDir: Commons.Color.currentThemePath

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
    target: Commons.Color
    function onAccentChanged() { colorsView.reload(); }
    function onBackgroundChanged() { colorsView.reload(); }
    function onForegroundChanged() { colorsView.reload(); }
    function onUrgentChanged() { colorsView.reload(); }
  }

  property string setKey: ""
  property string setValue: ""
  // a config write is in flight (set when it starts, cleared when it ends)
  property bool setActive: false
  // a write succeeded since the last config read
  property bool configDirty: false

  Process {
    id: setProc
    stderr: StdioCollector { id: setErr }
    onExited: function (code, status) { root.finishSet(code, setErr.text); }
    // settle a tick after the process stops, whichever of exited and
    // runningChanged comes first: a write still in flight then means a
    // spawn failure (no exited); then start the next queued write
    onRunningChanged: { if (!setProc.running) Qt.callLater(root.settleSet); }
  }

  Process {
    id: scribbleProc
    onRunningChanged: {
      if (scribbleProc.running || root.scribblePending === null) return;
      var next = root.scribblePending;
      root.scribblePending = null;
      root.sendScribble(next);
    }
  }

  Process {
    id: cfgProc
    command: [root.wispd, "config", "show", "--json"]
    stdout: StdioCollector { id: cfgOut }
    stderr: StdioCollector { id: cfgErr }
    onExited: function (code) {
      root.configLoaded = true;
      if (code !== 0) {
        root.configReadError = Settings.errorText(cfgErr.text) || Copy.string("ui.err.unknown");
        root.recapReadRequested = false;
      } else {
        root.configReadError = "";
        try { root.configValues = Settings.flatten(JSON.parse(cfgOut.text)); } catch (e) {}
        if (root.recapReadRequested) {
          root.recapReadRequested = false;
          root.loadRecap();
        }
      }
      if (root.configAgain) {
        root.configAgain = false;
        cfgProc.running = true;
      }
    }
  }

  // one-shot daemon probe for the settings window: exit 3 = daemon down
  Process {
    id: statusProc
    command: [root.wispd, "status", "--json"]
    onExited: function (code) { root.statusCode = code; }
  }

  Process {
    id: connListProc
    command: [root.wispd, "connect", "list", "--json"]
    stdout: StdioCollector { id: connListOut }
    stderr: StdioCollector { id: connListErr }
    onExited: function (code) {
      var list = null;
      if (code === 0) {
        try {
          var doc = JSON.parse(connListOut.text);
          if (doc && doc.data && Array.isArray(doc.data.connectors)) list = doc.data.connectors;
        } catch (e) {}
      }
      if (list === null) {
        root.connectorError = code === 0 ? Copy.string("ui.err.unknown")
          : (Settings.errorText(connListErr.text) || Copy.string("ui.err.unknown"));
        root.connectorState = "failed";
        return;
      }
      root.connectorList = list;
      root.connectorError = "";
      root.connectorState = "ready";
    }
  }

  Process {
    id: connAddProc
    stderr: StdioCollector { id: connAddErr }
    onExited: function (code) { root.finishConnect(code, connAddErr.text); }
    // a tick later, so a normal exit is recorded first in either order
    onRunningChanged: {
      if (!connAddProc.running) Qt.callLater(function () {
        if (!connAddProc.running) root.finishConnect(127, "");
      });
    }
  }

  Process {
    id: recapProc
    command: [root.wispd, "recap", "--claim", "--json"]
    stdout: StdioCollector { id: recapOut }
    onExited: function (code) { root.finishRecap(code, recapOut.text); }
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

  Process {
    id: devProc
    command: [root.wispd, "dev", "turns", "--json"]
    stdout: StdioCollector { id: devOut }
    onExited: function (code) {
      var r = Dev.parse(devOut.text);
      root.devLoading = false;
      if (r.ok) { root.devData = r.data; root.devError = ""; }
      else root.devError = r.error || "error";
    }
    // a spawn failure flips running without exited
    onRunningChanged: {
      if (!devProc.running && root.devLoading) {
        root.devLoading = false;
        root.devError = "spawn";
      }
    }
  }

  Process {
    id: devRunsProc
    command: [root.wispd, "dev", "runs", "--json"]
    stdout: StdioCollector { id: devRunsOut }
    onExited: function (code) {
      var r = Dev.parseRuns(devRunsOut.text);
      root.devRunsLoading = false;
      if (r.ok) { root.devRuns = r.data; root.devRunsError = ""; }
      else root.devRunsError = r.error || "error";
    }
    onRunningChanged: {
      if (!devRunsProc.running && root.devRunsLoading) {
        root.devRunsLoading = false;
        root.devRunsError = "spawn";
      }
    }
  }

  // The one action subprocess (see run/lastAction): stdout+stderr are
  // collected so a daemon refusal or a spawn failure reaches the
  // surfaces as a typed result, never silence.
  Process {
    id: actionProc
    command: [root.wispd, "status"]
    // stdin stays open for the whole run: a command that takes typed text
    // reads one line from it (--stdin), the others never read it.
    stdinEnabled: true
    onStarted: root.writeActionStdin()
    stdout: StdioCollector { id: actionOut }
    stderr: StdioCollector { id: actionErr }
    onExited: function (code, status) { root.finishAction(code); }
    // A spawn failure emits runningChanged without exited — resolve the
    // pending action (and drain the queue) instead of pending forever.
    onRunningChanged: {
      if (!actionProc.running) root.finishAction(127);
    }
  }

  // The preempt lane for interrupt(): a second Process so the stop
  // command reaches the daemon while actionProc is mid-flight.
  Process {
    id: stopProc
    command: [root.wispd, "interrupt", "--json"]
    stdout: StdioCollector { id: stopOut }
    stderr: StdioCollector { id: stopErr }
    onExited: function (code) {
      root.stopPending = false;
      var r = Reader.actionResult(code, stopOut.text, stopErr.text);
      var msg = r.text;
      if (Reader.ERROR_CODES.indexOf(r.error) >= 0)
        msg = Copy.errorMessage(r.error);
      root.lastAction = { verb: "interrupt", pending: false,
                          ok: r.ok, message: msg ||
                          (r.ok ? Copy.string("ui.noted")
                           : Copy.errorMessage("internal")),
                          at: Date.now() };
    }
    // spawn failure: running flips false without exited
    onRunningChanged: {
      if (!stopProc.running && root.stopPending) {
        root.stopPending = false;
        root.lastAction = { verb: "interrupt", pending: false, ok: false,
                            message: Copy.errorMessage("internal"), at: Date.now() };
      }
    }
  }

  Component.onCompleted: stateView.reload()
}
