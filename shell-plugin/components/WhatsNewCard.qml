// What's-new card (B26): the three headline lines of the version just
// installed, a link to the full changelog and one button. It shows once per
// version: the Panel marks the version seen when it closes. Data comes from
// lib/whatsnew.js (`wispd whatsnew --json`); the card emits dismiss and
// openLink and never starts anything itself. Every string is from the copy
// table or the changelog.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  // the card from lib/whatsnew.js parse(): {title, date, lines, more, url}
  property var card: null
  signal dismiss()
  signal openLink(string url)

  readonly property var tk: service ? service.tokens : ({})

  width: 340
  implicitHeight: col.implicitHeight + 2 * M.scale.space.md
  radius: M.radius.chrome
  color: tk.raised
  border.width: M.size.keyline
  border.color: tk.keyline

  Column {
    id: col
    x: M.scale.space.md
    y: M.scale.space.md
    width: root.width - 2 * M.scale.space.md
    spacing: M.scale.space.md

    Text {
      textFormat: Text.PlainText
      objectName: "whatsnewTitle"
      width: parent.width
      text: root.service.ui("ui.whatsnew.title") + (root.card ? " " + root.card.title : "")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("body", root.ts)
      font.weight: Font.DemiBold
      elide: Text.ElideRight
    }

    Repeater {
      model: root.card ? root.card.lines : []
      delegate: Text {
        textFormat: Text.PlainText
        required property string modelData
        objectName: "whatsnewLine"
        width: col.width
        text: modelData
        wrapMode: Text.Wrap
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("label", root.ts)
      }
    }

    Text {
      textFormat: Text.PlainText
      objectName: "whatsnewMore"
      visible: root.card !== null && root.card.more > 0
      width: parent.width
      text: root.card && root.card.more > 0 ? "+" + root.card.more + " " + root.service.ui("ui.whatsnew.more") : ""
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }

    Row {
      spacing: M.scale.space.sm
      Chip {
        objectName: "whatsnewLink"
        service: root.service
        label: root.service.ui("ui.whatsnew.link")
        onClicked: root.openLink(root.card ? root.card.url : "")
      }
      Chip {
        objectName: "whatsnewDismiss"
        service: root.service
        label: root.service.ui("ui.whatsnew.dismiss")
        onClicked: root.dismiss()
      }
    }
  }
}
