pragma Singleton
import QtQuick

// Stand-in for the Omarchy shell's qs.Commons Style (this app is its own
// Quickshell process, so WispService, which imports qs.Commons, needs the two
// names it reads). Only what WispService uses.
QtObject {
  readonly property string fontFamily: "JetBrainsMono NF"
}
