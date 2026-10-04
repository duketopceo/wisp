// Beacon: a pin that marks a point the guide wants you to see, numbered by
// step. States: landing (one spring overshoot, halo ring), holding, fading
// (after 8 s; the host drops it on the next turn). The life cycle runs as
// one finite animation, so an idle beacon costs nothing. Motion off starts
// in holding and never fades on its own.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/motion.js" as Motion
import "../lib/cursor.js" as Cursor

Item {
  id: root

  property var service: null
  property int index: 1
  // "" runs landing -> holding -> fading; fixtures pin a state
  property string forceState: ""
  property string motion: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")
  property string phase: motionMode === "off" ? "holding" : "landing"
  readonly property string cstate: forceState !== "" ? forceState : phase

  implicitWidth: M.size.beacon * 2
  implicitHeight: M.size.beacon * 2
  opacity: cstate === "fading" ? 0.45 : 1

  Item {
    id: pin
    anchors.fill: parent
    transformOrigin: Item.Bottom
    scale: 1

    Rectangle {
      visible: root.cstate === "landing"
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

  SequentialAnimation {
    running: root.forceState === "" && root.motionMode !== "off"
    NumberAnimation {
      target: pin
      property: "scale"
      from: root.motionMode === "full" ? 0.6 : 1
      to: 1
      duration: root.motionMode === "full" ? Cursor.BEACON_LAND_MS : 0
      easing.type: Easing.OutBack
    }
    ScriptAction { script: root.phase = "holding" }
    PauseAnimation { duration: Cursor.BEACON_HOLD_MS }
    ScriptAction { script: root.phase = "fading" }
  }
}
