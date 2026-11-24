import QtQuick
import Quickshell
import Quickshell.Io
import "components"
import "lib/settings.js" as S
import "lib/manage.js" as Manage

// Wisp settings window (overhaul U4; Status and management pages from
// one-surface U3, which retired the console app). Started by `wispd
// settings` as its own Quickshell process (quickshell -n -p
// shells/settings), so it never dies with the bar shell. The first page
// comes from WISP_SETTINGS_CATEGORY (Home when unset or unknown); a running
// window takes later requests through the `settings` IPC target
// (`quickshell ipc -p <dir> call settings open <page>`). The body is the
// window-free SettingsHost component; this file only hosts it, feeds it
// from the service and the files below, runs its actions through
// WispService.runAction and wires IPC.
//
// The daemon stream follows the page (plan KTD2): on while a Status or
// management page is open, off on a config category, so idle settings use
// holds no socket or reconnect timers. A page shows its loading state
// until the first state after the stream turns on. Config, status and the
// connector list are read once on open and again on Retry; nothing polls.
// Files are read when their page opens and watched only while it is open
// (decisions, corrections and suggestions on Activity, the cua audit log
// on Audit); the cua, spend and binds reads run when their page opens.

FloatingWindow {
  id: win
  title: "Wisp settings"
  implicitWidth: 960
  implicitHeight: 700
  minimumSize: Qt.size(720, 520)
  color: svc.tokens.canvas

  readonly property string dataDir: Quickshell.env("HOME") + "/.local/share/wisp"
  // wisp/cua_safety.audit_default_path()
  readonly property string auditPath: {
    var base = Quickshell.env("XDG_STATE_HOME");
    if (!base || base.length === 0) base = Quickshell.env("HOME") + "/.local/state";
    return base + "/wisp/cua.jsonl";
  }

  readonly property bool streamOn: S.isPage(host.category)
  WispService { id: svc; streamEnabled: win.streamOn }

  readonly property string startCategory: S.startPage(Quickshell.env("WISP_SETTINGS_CATEGORY") || "")

  // the first state since the stream last turned on has arrived
  property bool heard: false
  onStreamOnChanged: heard = false
  Connections {
    target: svc
    function onStateApplied(view) { if (win.streamOn) win.heard = true; }
  }

  property string decisionsText: ""
  property string corrText: ""
  property string suggText: ""
  property string memoryText: ""
  property string userText: ""
  property string auditText: ""
  property var bindsData: null
  property string bindsError: ""

  // the connector list asks the gateway, so it is read only once the
  // Connectors page is first shown
  property bool connectorsRead: false
  function readConnectorsOnce() {
    if (connectorsRead || host.category !== "connectors") return;
    connectorsRead = true;
    svc.loadConnectors();
  }

  // one-shot reads when a page opens (and on its Retry), never on a timer
  function enter(page) {
    if (page === "health" || page === "spend") svc.loadSettings();
    if (page === "binds" && !bindsProc.running) {
      bindsError = "";
      bindsProc.running = true;
    }
    if (page === "activity") { decisionsView.reload(); corrView.reload(); suggView.reload(); }
    if (page === "audit") auditView.reload();
    if (page === "memory") { memoryView.reload(); userView.reload(); }
  }
  function retryPage() {
    svc.reconnect();
    enter(host.category);
  }
  function wispd(args, verb) {
    svc.runAction([svc.wispd].concat(args).concat(["--json"]), verb);
  }
  function daemon(verb) {
    svc.runAction(["systemctl", "--user", verb, "wispd"], "daemon");
  }

  Component.onCompleted: {
    svc.retrySettings();
    readConnectorsOnce();
    enter(host.category);
  }

  FileView {
    id: decisionsView
    onLoaded: win.decisionsText = decisionsView.text()
    onLoadFailed: win.decisionsText = ""
    path: win.dataDir + "/decisions.jsonl"
    watchChanges: host.category === "activity"
    printErrors: false
    onFileChanged: reload()
  }
  FileView {
    id: corrView
    onLoaded: win.corrText = corrView.text()
    onLoadFailed: win.corrText = ""
    path: win.dataDir + "/corrections.jsonl"
    watchChanges: host.category === "activity"
    printErrors: false
    onFileChanged: reload()
  }
  FileView {
    id: suggView
    onLoaded: win.suggText = suggView.text()
    onLoadFailed: win.suggText = ""
    path: win.dataDir + "/suggestions.jsonl"
    watchChanges: host.category === "activity"
    printErrors: false
    onFileChanged: reload()
  }
  FileView {
    id: memoryView
    path: win.dataDir + "/MEMORY.md"
    printErrors: false
    onLoaded: win.memoryText = memoryView.text()
    onLoadFailed: win.memoryText = ""
  }
  FileView {
    id: userView
    path: win.dataDir + "/USER.md"
    printErrors: false
    onLoaded: win.userText = userView.text()
    onLoadFailed: win.userText = ""
  }
  // the cua audit log: read only; a missing log is an empty page
  FileView {
    id: auditView
    path: win.auditPath
    watchChanges: host.category === "audit"
    printErrors: false
    onFileChanged: reload()
    onLoaded: win.auditText = auditView.text()
    onLoadFailed: win.auditText = ""
  }

  Process {
    id: bindsProc
    command: [svc.wispd, "binds", "--json"]
    stdout: StdioCollector { id: bindsOut }
    onExited: function (code) {
      var r = Manage.bindsRead(code, bindsOut.text);
      win.bindsData = r.data;
      win.bindsError = r.error;
    }
  }

  SettingsHost {
    id: host
    anchors.fill: parent
    service: svc
    category: win.startCategory
    onCategoryChanged: { win.readConnectorsOnce(); win.enter(host.category); }
    values: svc.configValues
    saveStates: svc.configState
    errors: svc.configErrors
    loaded: svc.configLoaded
    readError: svc.configReadError
    offline: svc.settingsOffline
    connectors: svc.connectorList
    connectorState: svc.connectorState
    connectorError: svc.connectorError
    connectorRunning: svc.connectorRunning
    connectorErrors: svc.connectorErrors
    heard: win.heard
    pageError: host.category === "binds" ? win.bindsError : ""
    turns: Manage.turnRows(win.decisionsText, 30)
    suggestions: Manage.openSuggestions(win.suggText)
    corrections: Manage.correctionLines(win.corrText, 6)
    memoryText: win.memoryText
    userText: win.userText
    auditText: win.auditText
    binds: win.bindsData
    cua: svc.cuaStatus
    spendModels: svc.spendModels
    onCommit: (key, value) => svc.configSet(key, value)
    onRetry: svc.retrySettings()
    onRetryConnectors: svc.loadConnectors()
    onConnectAlias: (alias) => svc.connectAdd(alias)
    onRetryPage: win.retryPage()
    onTalk: svc.trigger()
    onRestart: win.daemon("restart")
    onStop: win.daemon("stop")
    onAnswer: (pick) => svc.sendChoice(pick)
    onSaveMemory: (which, text) => win.wispd(["memory", "write", which, Qt.btoa(text)], "memory")
    onStartTask: (text) => win.wispd(["task", "run", text], "task")
    onCancelTask: (name) => win.wispd(["task", "cancel", name], "task")
  }

  IpcHandler {
    target: "settings"

    // open a page or category (or keep the current one for ""); the CLI
    // then focuses the window through Hyprland, which a client cannot do
    // itself
    function open(category: string): void {
      if (category !== "") host.select(category);
    }
  }
}
