// Beacon: a pin that marks a point the guide wants you to see, numbered by
// step. States: landing (halo ring), holding, fading (dimmed).
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property int index: 1
  property string state: "holding"

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: M.size.beacon * 2
  implicitHeight: M.size.beacon * 2
  opacity: state === "fading" ? 0.45 : 1

  Rectangle {
    visible: root.state === "landing"
    anchors.horizontalCenter: parent.horizontalCenter
    y: 0
    width: M.size.beacon * 1.6
    height: width
    radius: width / 2
    color: "transparent"
    border.width: M.size.keyline
    border.color: Qt.alpha(root.tk.ember, 0.7)
  }

  Icon {
    anchors.horizontalCenter: parent.horizontalCenter
    y: (M.size.beacon * 1.6 - M.size.beacon) / 2
    name: "beacon"
    size: M.size.beacon
    color: root.tk.ember
  }

  Text {
    anchors.horizontalCenter: parent.horizontalCenter
    y: (M.size.beacon * 1.6 - M.size.beacon) / 2 + M.size.beacon * 0.18
    text: String(root.index)
    color: root.tk.canvas
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
    font.weight: Font.Bold
  }
}
