// Empty state: one sentence and one command, no illustration. `tab` is
// one of now, agents, memory, settings; the text comes from the copy table.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  property string tab: "now"

  readonly property var tk: service ? service.tokens : ({})

  spacing: M.spacing.md
  width: 340

  Text {
    width: parent.width
    text: root.service.ui("ui.empty." + root.tab)
    wrapMode: Text.Wrap
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
  }
  Text {
    width: parent.width
    text: root.service.ui("ui.empty." + root.tab + ".hint")
    wrapMode: Text.Wrap
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }
}
