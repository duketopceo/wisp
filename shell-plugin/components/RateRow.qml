// Rate row: the answer card's two one-tap buttons, "good" and "wrong"
// (thumb icon plus word, each with an accessible name), then a short
// receipt in their place once a tap went out ("rated good"). Shown for a
// finished answer only: a cancelled or errored turn gets nothing. Each tap
// rates `turn`, the turn this card belongs to, and leaves through `rate`
// (the host calls service.label). A refused rating (not_found,
// not_ratable) shows a muted line instead of the receipt. Reads state
// only from `service`; no keyboard: the overlay never takes focus.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/rate.js" as Rate

Item {
  id: root

  property var service: null
  // the turn this card rates (service.turnId while the card is current)
  property string turn: service ? service.turnId : ""
  // "correct" | "incorrect" once this card was tapped; a tap belongs to
  // the turn it rated, so a newer turn starts the row fresh
  property string tapped: ""
  property string tappedFor: ""
  readonly property bool rated: tapped !== "" && (tappedFor === "" || tappedFor === turn)
  // the host may hold the row back (a confirm card owns the bubble)
  property bool allowed: true
  signal rate(string verdict, string turn)

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool canRate: service !== null
    && Rate.rateable(service.status, service.answer, service.result, service.errorCode)
  readonly property var ack: service
    ? Rate.receipt(service.lastAction, turn, tapped, function (k) { return service.ui(k) })
    : ({ kind: "none", text: "" })
  readonly property string line: ack.kind !== "none" ? ack.text
    : service ? service.ui(tapped === "incorrect" ? "ui.rate.wrong" : "ui.rate.good") : ""

  visible: canRate && allowed
  implicitWidth: !rated ? buttons.implicitWidth : receiptText.implicitWidth
  implicitHeight: !rated ? buttons.implicitHeight : receiptText.implicitHeight

  component Btn: Rectangle {
    id: btn
    property var tk: ({})
    property string fontFamily: ""
    property string icon: ""
    property string word: ""
    property bool hovered: area.containsMouse
    signal pressed()

    implicitWidth: row.implicitWidth + 2 * M.spacing.xl
    implicitHeight: M.size.control
    radius: Math.min(M.radius.chrome, M.radius.chip)
    color: area.pressed ? tk.selection : tk.raised
    border.width: M.size.keyline
    border.color: hovered ? tk.keylineStrong : tk.keyline
    Accessible.role: Accessible.Button
    Accessible.name: word

    Row {
      id: row
      anchors.centerIn: parent
      spacing: M.spacing.md
      Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: btn.icon
        size: M.font.icon
        color: btn.tk.ink
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: btn.word
        color: btn.tk.ink
        font.family: btn.fontFamily
        font.pixelSize: M.font.label
      }
    }

    MouseArea {
      id: area
      anchors.fill: parent
      hoverEnabled: true
      onClicked: btn.pressed()
    }
  }

  Row {
    id: buttons
    visible: !root.rated
    spacing: M.spacing.md
    Btn {
      tk: root.tk
      fontFamily: root.service ? root.service.fontFamily : ""
      icon: "thumb-up"
      word: root.service ? root.service.ui("ui.label.good") : ""
      onPressed: { root.tapped = "correct"; root.tappedFor = root.turn; root.rate("correct", root.turn); }
    }
    Btn {
      tk: root.tk
      fontFamily: root.service ? root.service.fontFamily : ""
      icon: "thumb-down"
      word: root.service ? root.service.ui("ui.label.wrong") : ""
      onPressed: { root.tapped = "incorrect"; root.tappedFor = root.turn; root.rate("incorrect", root.turn); }
    }
  }

  Text {
    id: receiptText
    visible: root.rated
    text: root.line
    color: root.tk.inkMuted
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
  }
}
