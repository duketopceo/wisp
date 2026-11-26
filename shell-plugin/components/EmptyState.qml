// Empty state: one sentence and one command, no illustration. `tab` is
// one of now, agents, memory, settings, activity; the text comes from the
// copy table. A settings-window page sets `textKey` to its page state
// (ui.page.loading, offline, stale, error) and, for offline and error,
// `action` to a button label that emits act() (Retry).
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  property string tab: "now"
  property string textKey: "ui.empty." + tab
  property string action: ""
  signal act()

  readonly property var tk: service ? service.tokens : ({})

  spacing: M.scale.space.sm
  width: 340

  Text {
    textFormat: Text.PlainText
    width: parent.width
    text: root.service.ui(root.textKey)
    wrapMode: Text.Wrap
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("body", root.ts)
  }
  Text {
    textFormat: Text.PlainText
    width: parent.width
    text: root.service.ui(root.textKey + ".hint")
    wrapMode: Text.Wrap
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("label", root.ts)
  }
  Chip {
    objectName: "action"
    visible: root.action !== ""
    service: root.service
    label: root.action
    focusable: true
    onClicked: root.act()
  }
}
