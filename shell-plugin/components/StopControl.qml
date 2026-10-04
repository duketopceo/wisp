// Stop control: icon, "stop" and the Esc hint. Visible only while a turn
// is busy (or alwaysShow, for previews); hover turns it to the fail token.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  property bool alwaysShow: false
  property bool hovered: area.containsMouse
  signal clicked()

  readonly property var tk: service ? service.tokens : ({})
  readonly property color fg: hovered ? tk.fail : tk.inkMuted

  visible: alwaysShow || service.busy || service.status === "speaking"
  implicitWidth: row.implicitWidth + 2 * M.spacing.xl
  implicitHeight: M.size.control
  radius: Math.min(M.radius.chrome, M.radius.chip)
  color: "transparent"
  border.width: M.size.keyline
  border.color: hovered ? tk.fail : tk.keyline

  Row {
    id: row
    anchors.centerIn: parent
    spacing: M.spacing.md

    Icon {
      anchors.verticalCenter: parent.verticalCenter
      name: "stop"
      size: M.font.icon
      color: root.fg
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.service.ui("ui.stop")
      color: root.fg
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.service.ui("ui.esc")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    onClicked: root.clicked()
  }
}
