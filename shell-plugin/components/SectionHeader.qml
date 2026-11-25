// Section heading inside a settings page (U3): a title, an optional
// one-line note under it, and a keyline above when it is not the first
// section on the page.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  property string title: ""
  property string note: ""
  property bool first: false

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1

  width: 480
  spacing: M.scale.space.xs
  topPadding: first ? 0 : M.scale.space.md

  Accessible.role: Accessible.Heading
  Accessible.name: title

  Rectangle {
    visible: !root.first
    width: parent.width
    height: M.size.keyline
    color: root.tk.keyline
  }
  Item { visible: !root.first; width: 1; height: M.scale.space.sm }

  Text {
    textFormat: Text.PlainText
    width: parent.width
    wrapMode: Text.Wrap
    text: root.title
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("title", root.ts)
    font.weight: Font.DemiBold

    // a page heading takes focus on a page change: show where it is
    Rectangle {
      visible: root.activeFocus
      anchors.fill: parent
      anchors.leftMargin: -M.scale.space.xs
      anchors.rightMargin: -M.scale.space.xs
      radius: M.radius.chip
      color: "transparent"
      border.width: M.scale.focusRing
      border.color: root.tk.accent
    }
  }
  Text {
    textFormat: Text.PlainText
    visible: root.note !== ""
    width: parent.width
    wrapMode: Text.Wrap
    text: root.note
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
  }
}
