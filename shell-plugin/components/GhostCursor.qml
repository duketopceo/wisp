// Ghost cursor: shows where a click will land while the real pointer stays
// put. States: traveling, clicking (ripple at the tip), parked (guide, with
// its label), returning (dimmed). W21 mounts the creature on it.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property string state: "parked"
  property string label: ""

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: Math.max(M.size.cursorHeight, tag.visible ? tag.width : 0) + M.spacing.huge
  implicitHeight: M.size.cursorHeight + (tag.visible ? tag.height + M.spacing.md : 0)
  opacity: state === "returning" ? 0.55 : 1

  Rectangle {
    visible: root.state === "clicking"
    x: 1
    y: 1
    width: M.size.cursorHeight
    height: width
    radius: width / 2
    color: Qt.alpha(root.tk.ember, 0.18)
    border.width: M.size.keyline
    border.color: root.tk.ember
  }

  Icon {
    id: arrow
    name: "ghost-cursor"
    size: M.size.cursorHeight
    color: root.state === "traveling" ? root.tk.emberCore : root.tk.ember
  }

  Rectangle {
    id: tag
    visible: root.state === "parked" && root.label !== ""
    x: M.spacing.lg
    y: M.size.cursorHeight + M.spacing.sm
    width: txt.implicitWidth + 2 * M.spacing.lg
    height: txt.implicitHeight + 2 * M.spacing.sm
    radius: M.radius.chip
    color: root.tk.canvas
    border.width: M.size.keyline
    border.color: root.tk.keyline

    Text {
      id: txt
      anchors.centerIn: parent
      text: root.label
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }
}
