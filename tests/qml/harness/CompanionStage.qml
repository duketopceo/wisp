import QtQuick
import "../../../shell-plugin/components"

// Snapshot-only composition of the Companion host: the same CornerLayer
// (Top window) and OverlayLayer (Overlay window) Companion.qml mounts,
// stacked over a desktop-colored output with the host's wiring between them
// (the console extent steps the bubble aside). Window flags, the input
// regions and the timers live in Companion.qml and are not drawn.
Item {
  id: root

  property var service: null
  property bool hidden: false
  property bool fullscreen: false
  property bool userOpen: false
  property var pointer: null
  property bool bubbleDismissed: false
  property real refreshHz: 60

  width: 1280
  height: 720

  CornerLayer {
    id: top
    anchors.fill: parent
    service: root.service
    hidden: root.hidden
    fullscreen: root.fullscreen
    userOpen: root.userOpen
    refreshHz: root.refreshHz
  }

  OverlayLayer {
    anchors.fill: parent
    service: root.service
    pointer: root.pointer
    refreshHz: root.refreshHz
    consoleExtent: top.consoleExtent
    bubbleDismissed: root.bubbleDismissed
  }
}
