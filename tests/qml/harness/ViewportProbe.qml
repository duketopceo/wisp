import QtQuick
import "../../../shell-plugin/lib/metrics.js" as M

// Harness-only: a text-free window-shaped layout (sidebar, header strip,
// content blocks) drawn from service.tokens and the spacing scale. Snap.qml
// sets its size from the scene's named viewport, so the harness proves a
// surface can be rendered at 1728x1080 (scale 2) and 3440x1440 (scale 1).
// No text on purpose: the golden does not depend on fonts.
Item {
  id: root
  property var service: null
  readonly property var tk: service ? service.tokens : ({})
  implicitWidth: 960
  implicitHeight: 700

  Rectangle {
    anchors.fill: parent
    color: root.tk.canvas
  }

  Rectangle {
    id: sidebar
    x: 0
    y: 0
    width: 4 * M.scale.space.huge
    height: root.height
    color: root.tk.raised
    border.width: M.size.keyline
    border.color: root.tk.keyline
  }

  Rectangle {
    id: header
    x: sidebar.width + M.scale.space.lg
    y: M.scale.space.lg
    width: root.width - x - M.scale.space.lg
    height: M.scale.control.window
    radius: M.radius.chip
    color: root.tk.raised
    border.width: M.size.keyline
    border.color: root.tk.keylineStrong
  }

  Repeater {
    model: 6
    Rectangle {
      required property int index
      x: header.x
      y: header.y + header.height + M.scale.space.lg
         + index * (M.scale.control.window + M.scale.space.sm)
      width: Math.min(header.width, 960)
      height: M.scale.control.window
      radius: M.radius.chip
      color: index % 2 === 0 ? root.tk.selection : root.tk.raised
    }
  }
}
