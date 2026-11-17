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
// file only hosts it and wires IPC. No timers, no polling.

FloatingWindow {
  id: win
  title: "Wisp settings"
  implicitWidth: 960
  implicitHeight: 700
  minimumSize: Qt.size(720, 520)
  color: svc.tokens.canvas

  WispService { id: svc }

  readonly property string startCategory: {
    var c = Quickshell.env("WISP_SETTINGS_CATEGORY") || "";
    return S.CATEGORIES.indexOf(c) >= 0 ? c : S.CATEGORIES[0];
  }

  SettingsHost {
    id: host
    anchors.fill: parent
    service: svc
    category: win.startCategory
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
