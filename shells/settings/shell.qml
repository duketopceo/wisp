import QtQuick
import Quickshell
import Quickshell.Io
import "components"
import "lib/settings.js" as S

// Wisp settings window (overhaul U4). Started by `wispd settings` as its
// own Quickshell process (quickshell -n -p shells/settings), so it never
// dies with the bar shell. The first category comes from
// WISP_SETTINGS_CATEGORY; a running window takes later requests through
// the `settings` IPC target (`quickshell ipc -p <dir> call settings open
// <category>`). The body is the window-free SettingsHost component; this
// file only hosts it, feeds it from the service (config values, write
// states, read and daemon state, connectors) and wires IPC. The daemon
// stream is off, so the window holds no socket, reconnect timers or
// state.json watch: it reads config, status and the connector list once on
// open and again on Retry. Ctrl+F is a Shortcut inside the host.

FloatingWindow {
  id: win
  title: "Wisp settings"
  implicitWidth: 960
  implicitHeight: 700
  minimumSize: Qt.size(720, 520)
  color: svc.tokens.canvas

  WispService { id: svc; streamEnabled: false }

  readonly property string startCategory: {
    var c = Quickshell.env("WISP_SETTINGS_CATEGORY") || "";
    return S.CATEGORIES.indexOf(c) >= 0 ? c : S.CATEGORIES[0];
  }

  // the connector list asks the gateway, so it is read only once the
  // Connectors page is first shown
  property bool connectorsRead: false
  function readConnectorsOnce() {
    if (connectorsRead || host.category !== "connectors") return;
    connectorsRead = true;
    svc.loadConnectors();
  }

  Component.onCompleted: {
    svc.retrySettings();
    readConnectorsOnce();
  }

  SettingsHost {
    id: host
    anchors.fill: parent
    service: svc
    category: win.startCategory
    onCategoryChanged: win.readConnectorsOnce()
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
    onCommit: (key, value) => svc.configSet(key, value)
    onRetry: svc.retrySettings()
    onRetryConnectors: svc.loadConnectors()
    onConnectAlias: (alias) => svc.connectAdd(alias)
  }

  IpcHandler {
    target: "settings"

    // open a category (or keep the current one for ""); the CLI then
    // focuses the window through Hyprland, which a client cannot do itself
    function open(category: string): void {
      if (category !== "") host.select(category);
    }
  }
}
