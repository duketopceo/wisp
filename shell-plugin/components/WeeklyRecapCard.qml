// Private weekly recap (B31): local numbers only. The service owns reading,
// weekly dedupe and the off switch; this component has no I/O or timers.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root
  property var service: null
  readonly property real ts: service ? service.textScale : 1
  property var card: null
  signal dismiss()
  signal offClicked()
  readonly property var tk: service ? service.tokens : ({})

  width: 340
  implicitHeight: col.implicitHeight + 2 * M.scale.space.md
  radius: M.radius.chrome
  color: root.tk.raised
  border.width: M.size.keyline
  border.color: root.tk.keyline

  Column {
    id: col
    x: M.scale.space.md
    y: M.scale.space.md
    width: root.width - 2 * M.scale.space.md
    spacing: M.scale.space.md

    Text {
      textFormat: Text.PlainText
      objectName: "recapTitle"
      width: parent.width
      text: root.card ? root.card.title : ""
      wrapMode: Text.Wrap
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("body", root.ts)
      font.weight: Font.DemiBold
    }
    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: root.card ? root.card.week_start + " / " + root.card.week_end : ""
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }
    Text {
      textFormat: Text.PlainText
      objectName: "recapSummary"
      width: parent.width
      text: root.card ? root.card.summary : ""
      wrapMode: Text.Wrap
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("body", root.ts)
    }
    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      width: parent.width
      text: root.card ? root.card.activity_note || "" : ""
      wrapMode: Text.Wrap
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("label", root.ts)
    }
    Text {
      textFormat: Text.PlainText
      objectName: "recapSpendNote"
      width: parent.width
      text: root.card ? root.card.spend_note : ""
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("label", root.ts)
    }
    Flow {
      width: parent.width
      spacing: M.scale.space.sm
      Chip {
        objectName: "recapDismiss"
        service: root.service
        label: root.service.ui("ui.hide")
        onClicked: root.dismiss()
      }
      Chip {
        objectName: "recapOff"
        service: root.service
        label: root.service.ui("ui.set.off")
        onClicked: root.offClicked()
      }
    }
  }
}
