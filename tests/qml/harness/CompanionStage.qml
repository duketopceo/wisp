import QtQuick
import "../../../shell-plugin/components"

// Snapshot-only composition of the Companion host: the OverlayLayer the
// wisp-points window mounts. The corner creature is gone (the bar pill is
// the live surface), so the stage is the overlay alone over a
// desktop-colored output. Window flags, the input regions and the timers
// live in Companion.qml and are not drawn.
Item {
  id: root

  property var service: null
  property var pointer: null
  property bool bubbleDismissed: false
  property real refreshHz: 60

  width: 1280
  height: 720

  OverlayLayer {
    anchors.fill: parent
    service: root.service
    pointer: root.pointer
    refreshHz: root.refreshHz
    bubbleDismissed: root.bubbleDismissed
  }
}
