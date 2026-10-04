// Choice chip: humanized label, optional key hint (1, 2, 3). States:
// normal, hover, pressed, selected, disabled. Hover and pressed come from
// the MouseArea unless a caller (or the snapshot harness) sets them.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  property string label: ""
  property string hint: ""
  property bool selected: false
  property bool hovered: area.containsMouse
  property bool pressed: area.pressed
  signal clicked()

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: row.implicitWidth + 2 * M.spacing.xl
  implicitHeight: M.size.control
  radius: Math.min(M.radius.chrome, M.radius.chip)
  opacity: enabled ? 1 : 0.5
  color: pressed || selected ? tk.selection : tk.raised
  border.width: M.size.keyline
  border.color: selected || hovered ? tk.keylineStrong : tk.keyline

  Row {
    id: row
    anchors.centerIn: parent
    spacing: M.spacing.md

    Text {
      visible: root.hint !== ""
      anchors.verticalCenter: parent.verticalCenter
      text: root.hint
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.label
      color: root.selected ? root.tk.accent : root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    enabled: root.enabled
    onClicked: root.clicked()
  }
}
