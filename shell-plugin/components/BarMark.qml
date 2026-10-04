// Bar mark: the one glyph the bar shows (Mark), dimmed while offline or
// stale, with a static needs-you badge dot on a pending suggestion and a hollow ring while stale.
// Static by design: no looping animation, no timers, so it needs no motion
// gate and costs nothing at idle.
import QtQuick
import "../lib/bar.js" as B
import "../lib/creature.js" as C
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property real size: M.size.creatureBar
  readonly property var tk: service ? service.tokens : ({})
  readonly property string creatureState: C.stateFor(service ? service.status : "offline", "", false)
  readonly property bool dim: B.dimmed(service ? service.offline : true,
                                       service ? service.stale : false)
  readonly property bool badged: service ? B.badge(service.status, service.suggestion !== null) : false
  readonly property real dot: 6

  implicitWidth: size + M.spacing.sm
  implicitHeight: size + M.spacing.sm

  Mark {
    id: mark
    anchors.centerIn: parent
    service: root.service
    size: root.size
    opacity: root.dim ? 0.5 : 1
  }

  // pending choice or suggestion
  Rectangle {
    visible: root.badged && !root.dim
    x: parent.width - width
    y: 0
    width: root.dot
    height: root.dot
    radius: root.dot / 2
    color: root.tk[C.toneToken("awaiting_choice")]
  }

  // stale: hollow ring, same corner
  Rectangle {
    visible: root.service ? root.service.stale && !root.service.offline : false
    x: parent.width - width
    y: 0
    width: root.dot
    height: root.dot
    radius: root.dot / 2
    color: "transparent"
    border.width: M.size.keyline
    border.color: root.tk.inkMuted
  }
}
