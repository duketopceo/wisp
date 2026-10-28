// AskChips: up to three asks that fit the focused app, shown after a quick
// tap of the talk key. Text only and click-through: the user says one aloud.
// The host (OverlayLayer) keeps them down during a live turn; the Companion
// window sets `expired` after Chips.SHOW_MS. Fade only in full motion.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/chips.js" as Chips
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  // state.chips: {app, asks, seq}
  property var chips: null
  // fixtures and tests pin these
  property string motion: service ? service.motionMode : "off"
  property bool expired: false

  readonly property var tk: service ? service.tokens : ({})
  readonly property var v: Chips.view(chips)
  readonly property bool shown: v.show && !expired

  width: col.implicitWidth
  height: col.implicitHeight
  visible: shown
  opacity: shown ? 1 : 0

  Behavior on opacity {
    enabled: Chips.fadeMs(root.motion) > 0
    NumberAnimation { duration: Chips.fadeMs(root.motion) }
  }

  // a new tap (new chips value) shows them again; the host times them out
  onChipsChanged: expired = false

  Column {
    id: col
    spacing: M.spacing.md

    Text {
      objectName: "chipsTitle"
      text: root.v.title
      color: root.tk.inkMuted
      font.family: root.service ? root.service.fontFamily : ""
      font.pixelSize: M.font.caption
      leftPadding: M.spacing.xs
    }
    Repeater {
      model: root.v.asks
      delegate: Rectangle {
        id: chip
        required property string modelData
        objectName: "askChip"
        implicitWidth: label.implicitWidth + 2 * M.spacing.xl
        implicitHeight: M.size.control
        radius: Math.min(M.radius.chrome, M.radius.chip)
        color: root.tk.raised
        border.width: M.size.keyline
        border.color: root.tk.keyline
        Text {
          id: label
          anchors.centerIn: parent
          text: chip.modelData
          color: root.tk.ink
          font.family: root.service ? root.service.fontFamily : ""
          font.pixelSize: M.font.label
        }
      }
    }
  }
}
