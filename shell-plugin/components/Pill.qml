// Listening pill: one row with the riding creature, status word and the
// transcript tail with a mic icon; while a choice is pending it adds
// chips, the first three keyed 1 2 3 and the rest click or voice only.
// Keyline is ember at 0.35 + level * 0.4 while listening.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/companion.js" as Companion

Rectangle {
  id: root

  property var service: null
  signal choose(string pick, int index)

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool listening: service.status === "listening"
  readonly property var picks: service.choices.slice(0, 5)
  // the host shows the pill for these statuses (Companion.pillVisible)
  readonly property bool wanted: Companion.pillVisible(service.status)

  implicitWidth: 380
  implicitHeight: col.implicitHeight + 2 * M.spacing.xl
  radius: M.pillRadius(Math.min(height, M.size.control + 2 * M.spacing.sm), M.radius.chrome)
  color: tk.canvas
  border.width: M.size.keyline
  border.color: listening ? Qt.alpha(tk.ember, 0.35 + 0.4 * service.level) : tk.keyline

  Column {
    id: col
    anchors.fill: parent
    anchors.margins: M.spacing.xl
    spacing: M.spacing.lg

    Row {
      spacing: M.spacing.lg
      width: parent.width

      Creature {
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
        size: M.size.creaturePill
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: root.service.statusWord
        color: root.tk[M.toneToken(root.service.statusTone)]
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
        font.weight: Font.DemiBold
      }
      Icon {
        id: mic
        anchors.verticalCenter: parent.verticalCenter
        visible: root.service.transcript !== ""
        name: "mic"
        size: M.font.icon
        color: root.tk.inkMuted
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - x
        visible: root.service.transcript !== ""
        text: root.service.transcript
        elide: Text.ElideLeft
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
        font.italic: false
      }
    }

    Row {
      visible: root.picks.length > 0
      spacing: M.spacing.md

      Repeater {
        model: root.picks
        delegate: Chip {
          required property string modelData
          required property int index
          service: root.service
          label: root.service.pickLabel(modelData)
          hint: index < 3 ? String(index + 1) : ""
          onClicked: root.choose(modelData, index)
        }
      }
    }
  }
}
