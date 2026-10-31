// Private weekly recap (B31): local numbers only. The service owns reading,
// weekly dedupe and the off switch; this component has no I/O or timers.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root
  property var service: null
  property var card: null
  signal dismiss()
  signal offClicked()
  readonly property var tk: service ? service.tokens : ({})

  width: 340
  implicitHeight: col.implicitHeight + 2 * M.spacing.xxl
  radius: M.radius.chrome
  color: root.tk.raised
  border.width: M.size.keyline
  border.color: root.tk.keyline

  Column {
    id: col
    x: M.spacing.xxl
    y: M.spacing.xxl
    width: root.width - 2 * M.spacing.xxl
    spacing: M.spacing.xl

    Text {
      textFormat: Text.PlainText
      objectName: "recapTitle"
      width: parent.width
      text: root.card ? root.card.title : ""
      wrapMode: Text.Wrap
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }
    Text {
      textFormat: Text.PlainText
      width: parent.width
      text: root.card ? root.card.week_start + " / " + root.card.week_end : ""
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
    Text {
      textFormat: Text.PlainText
      objectName: "recapSummary"
      width: parent.width
      text: root.card ? root.card.summary : ""
      wrapMode: Text.Wrap
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
    }
    Text {
      textFormat: Text.PlainText
      visible: text !== ""
      width: parent.width
      text: root.card ? root.card.activity_note || "" : ""
      wrapMode: Text.Wrap
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
    Text {
      textFormat: Text.PlainText
      objectName: "recapSpendNote"
      width: parent.width
      text: root.card ? root.card.spend_note : ""
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
    Flow {
      width: parent.width
      spacing: M.spacing.lg
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
