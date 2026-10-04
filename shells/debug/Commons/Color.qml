pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Stand-in for the Omarchy shell's qs.Commons Color: the theme directory
// WispService reads colors.toml from, plus the change signals it listens to.
// This process never gets Omarchy's theme IPC, so it watches
// current/theme.name and bumps the four palette properties when the theme
// swaps, which makes WispService re-read colors.toml. Event driven, no timer.
QtObject {
  id: root

  readonly property string currentThemePath:
      Quickshell.env("HOME") + "/.local/state/omarchy/current/theme"

  // change tickers only: WispService reads colors.toml itself
  property int foreground: 0
  property int background: 0
  property int accent: 0
  property int urgent: 0

  property FileView themeName: FileView {
    path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme.name"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.bump()
  }

  function bump() {
    foreground += 1
    background += 1
    accent += 1
    urgent += 1
  }
}
