// Bar mark: one glyph per status (assets/icons bar-*) in a status token,
// with a 2px ember underline strip only while a turn is busy. Used by the
// bar widget and the status line.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property string status: service ? service.status : "offline"
  property real size: M.size.creatureBar
  readonly property bool busy: service ? service.busy : false

  implicitWidth: size
  implicitHeight: size + (busy ? M.spacing.xs : 0)

  Icon {
    id: glyph
    name: M.markIcon(root.status)
    size: root.size
    color: root.service ? root.service.tokens[M.markToken(root.status)] : "transparent"
  }

  Rectangle {
    visible: root.busy
    x: 0
    y: root.size + 1
    width: root.size
    height: M.size.tick
    color: root.service ? root.service.tokens.ember : "transparent"
  }
}
