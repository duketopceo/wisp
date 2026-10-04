// Flat creature: halo, body and core drawn from ember tokens. Window-free
// stand-in for the W21 WispCreature shader, with the same inputs (status,
// level, size) so the corner, pill and cursor can mount it now. Only this
// component loops, only while the status needs it, only in full motion.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/motion.js" as Motion

Item {
  id: root

  property var service: null
  property string status: service ? service.status : "idle"
  property real level: service ? service.level : 0
  property real size: M.creatureSize(status)

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: service ? service.motionMode : "off"
  readonly property real energy: M.energy(status, level)
  readonly property color tone: tk[M.creatureToken(status)]
  readonly property bool dashed: status === "offline"

  implicitWidth: size
  implicitHeight: size
  width: size
  height: size

  // soft corona: the one soft edge on screen
  Rectangle {
    id: halo
    anchors.centerIn: parent
    width: root.size
    height: root.size
    radius: width / 2
    color: Qt.alpha(root.tone, 0.10 + 0.30 * root.energy)
    border.width: root.dashed ? M.size.keyline : 0
    border.color: Qt.alpha(root.tone, 0.6)
    opacity: pulse.running ? 1 : 1

    SequentialAnimation on opacity {
      id: pulse
      running: Motion.loops(root.status, root.motionMode)
      loops: Animation.Infinite
      NumberAnimation { to: 0.7; duration: 700; easing.type: Easing.InOutSine }
      NumberAnimation { to: 1.0; duration: 700; easing.type: Easing.InOutSine }
    }
  }

  Rectangle {
    id: body
    anchors.centerIn: parent
    width: root.size * 0.62
    height: width
    radius: width / 2
    color: root.dashed ? "transparent" : Qt.alpha(root.tone, 0.55 + 0.4 * root.energy)
    border.width: root.dashed ? M.size.keyline : 0
    border.color: root.tone
    Behavior on color {
      enabled: root.motionMode !== "off"
      ColorAnimation { duration: Motion.duration.effectsDefault; easing.type: Easing.OutCubic }
    }
  }

  Rectangle {
    id: core
    anchors.centerIn: parent
    width: root.size * 0.30
    height: width
    radius: width / 2
    visible: !root.dashed
    color: root.status === "error" ? root.tone : root.tk.emberCore
  }
}
