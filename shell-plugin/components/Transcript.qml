// Heard transcript: mic icon plus the text in inkMuted. Never italic.
// Live and final look the same; the daemon decides when it changes.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  property int maxLines: 2
  readonly property var tk: service ? service.tokens : ({})
  readonly property bool has: service.transcript !== ""

  implicitWidth: 240
  implicitHeight: has ? label.implicitHeight : 0
  visible: has

  Icon {
    id: mic
    name: "mic"
    size: M.scale.icon
    color: root.tk.inkMuted
    y: Math.round((M.fontSize("label", root.ts) * M.lineHeight - size) / 2)
  }

  Text {
    textFormat: Text.PlainText
    id: label
    x: mic.width + M.scale.space.sm
    width: root.width - x
    text: root.service.transcript
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("label", root.ts)
    font.italic: false
    lineHeight: M.lineHeight
    wrapMode: Text.Wrap
    maximumLineCount: root.maxLines
    elide: Text.ElideRight
  }
}
