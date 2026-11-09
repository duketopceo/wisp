import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import "components"

// The typed-question window (companion core U1). The full-screen overlay
// (wisp-points) never takes the keyboard; this small window, centered under
// the bar, exists only while the composer is open and holds the keyboard so
// the question gets every key. Enter sends, Esc or an empty Enter closes;
// either way the window reports `closed` and the host unloads it.
PanelWindow {
  id: win

  property var service: null
  signal closed()

  color: "transparent"
  anchors { top: true }
  margins.top: Style.gapsOut + Style.bar.sizeVertical + 16
  implicitWidth: composer.implicitWidth
  implicitHeight: composer.implicitHeight
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "wisp-composer"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

  Composer {
    id: composer
    anchors.fill: parent
    service: win.service
    onSubmitted: win.closed()
    onDismissed: win.closed()
  }

  // opening after creation runs the composer's own reset and focus grab
  Component.onCompleted: composer.open = true
}
