// Heard transcript: mic icon plus the text in inkMuted. Never italic.
// Live and final look the same; the daemon decides when it changes.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property int maxLines: 2
  readonly property var tk: service ? service.tokens : ({})
  readonly property bool has: service.transcript !== ""

  implicitWidth: 240
  implicitHeight: has ? label.implicitHeight : 0
  visible: has

  Icon {
    id: mic
    name: "mic"
    size: M.font.icon
    color: root.tk.inkMuted
    y: Math.round((M.font.label * M.lineHeight - size) / 2)
  }

  Text {
    id: label
    x: mic.width + M.spacing.md
    width: root.width - x
    text: root.service.transcript
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
    font.italic: false
    lineHeight: M.lineHeight
    wrapMode: Text.Wrap
    maximumLineCount: root.maxLines
    elide: Text.ElideRight
  }
}
