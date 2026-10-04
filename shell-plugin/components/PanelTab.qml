// Panel tab: text with an accent underline when selected, no fill.
// States: normal, hover, selected.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property string text: ""
  property bool selected: false
  property bool hovered: area.containsMouse
  signal clicked()

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: label.implicitWidth + 2 * M.spacing.xl
  implicitHeight: M.size.control

  Text {
    id: label
    anchors.centerIn: parent
    text: root.text
    color: root.selected || root.hovered ? root.tk.ink : root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: root.selected ? Font.DemiBold : Font.Normal
  }

  Rectangle {
    visible: root.selected
    anchors.bottom: parent.bottom
    width: parent.width
    height: M.size.tabUnderline
    color: root.tk.accent
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    onClicked: root.clicked()
  }
}
