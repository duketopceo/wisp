// Choice chip: humanized label, optional key hint (1, 2, 3). States:
// normal, hover, pressed, selected, disabled. Hover and pressed come from
// the MouseArea unless a caller (or the snapshot harness) sets them.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  property string label: ""
  property string hint: ""
  property bool selected: false
  property bool hovered: area.containsMouse
  property bool pressed: area.pressed
  // opt in to keyboard use (settings window pages): Tab reaches it, Enter
  // or Space press it, and focus draws the accent ring
  property bool focusable: false
  signal clicked()

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: row.implicitWidth + 2 * M.scale.space.md
  implicitHeight: M.fitControl(row.implicitHeight)
  radius: Math.min(M.radius.chrome, M.radius.chip)
  opacity: enabled ? 1 : 0.5
  color: pressed || selected ? tk.selection : tk.raised
  border.width: activeFocus ? M.scale.focusRing : M.size.keyline
  border.color: activeFocus ? tk.accent : selected || hovered ? tk.keylineStrong : tk.keyline
  activeFocusOnTab: focusable
  Accessible.role: Accessible.Button
  Accessible.name: label
  Accessible.onPressAction: if (enabled) clicked()
  Keys.onReturnPressed: if (enabled) clicked()
  Keys.onEnterPressed: if (enabled) clicked()
  Keys.onSpacePressed: if (enabled) clicked()

  Row {
    id: row
    anchors.centerIn: parent
    spacing: M.scale.space.sm

    Text {
      textFormat: Text.PlainText
      visible: root.hint !== ""
      anchors.verticalCenter: parent.verticalCenter
      text: root.hint
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }
    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      text: root.label
      color: root.selected ? root.tk.accent : root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("label", root.ts)
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
