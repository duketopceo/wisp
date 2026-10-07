// Bar pill: the live-activities row that grows beside the bar mark while
// the daemon works — the wordView word in its tone plus a mic-level meter
// while listening. Collapses to zero width at idle so the bar keeps its
// rest footprint; the WidgetButton's animated width does the grow/shrink.
// No timers, no polling: every value binds straight to WispService.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: service ? service.motionMode : "off"
  readonly property var view: service ? service.wordView : ({ word: "", tone: "muted" })
  readonly property bool listening: service ? service.status === "listening" : false
  // live while the daemon works or waits on the user; an error keeps the
  // word up until the next turn so a failed ask isn't silent
  readonly property bool live: service !== null && (
    service.busy || service.status === "listening" ||
    service.status === "awaiting_choice" || service.confirm !== null ||
    service.suggestion !== null || service.status === "error")

  clip: true
  implicitWidth: live ? row.implicitWidth + M.spacing.lg : 0
  implicitHeight: row.implicitHeight
  opacity: live ? 1 : 0
  Behavior on opacity {
    enabled: root.motionMode !== "off"
    NumberAnimation { duration: 140 }
  }

  Row {
    id: row
    anchors.verticalCenter: parent.verticalCenter
    spacing: M.spacing.md

    Column {
      anchors.verticalCenter: parent.verticalCenter
      spacing: 2

      Text {
        width: Math.min(implicitWidth, 160)
        elide: Text.ElideRight
        text: root.view.word
        color: root.tk[M.toneToken(root.view.tone)]
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
        font.weight: Font.DemiBold
      }

      // mic level, listening only: the pill breathes with the voice
      Rectangle {
        visible: root.listening
        width: 36
        height: 3
        radius: 1.5
        color: root.tk.inkMuted ? Qt.alpha(root.tk.inkMuted, 0.35) : "transparent"
        Rectangle {
          width: parent.width * Math.max(0.08, root.service ? root.service.level : 0)
          height: parent.height
          radius: parent.radius
          color: root.tk.ember
        }
      }
    }
  }
}
