import QtQuick
import "../../../shell-plugin/components"

// Snapshot-only composition of the Companion host: the OverlayLayer the
// wisp-points window mounts. The corner creature is gone (the bar pill is
// the live surface), so the stage is the overlay alone over a
// desktop-colored output. Window flags, the input regions, the pointer feed
// and the frame clock live in Companion.qml and are not drawn: a scene hands
// in a fixed lib/buddy.js view (null draws no buddy).
Item {
  id: root

  property var service: null
  property bool bubbleDismissed: false
  property real refreshHz: 60
  property var buddyView: null

  width: 1280
  height: 720

  OverlayLayer {
    anchors.fill: parent
    service: root.service
    refreshHz: root.refreshHz
    bubbleDismissed: root.bubbleDismissed
    buddyView: root.buddyView
    buddyWanted: root.buddyView !== null
  }
}
