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
  readonly property real ts: service ? service.textScale : 1
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
    spacing: M.scale.space.sm

    Text {
      textFormat: Text.PlainText
      objectName: "chipsTitle"
      text: root.v.title
      color: root.tk.inkMuted
      font.family: root.service ? root.service.fontFamily : ""
      font.pixelSize: M.fontSize("caption", root.ts)
      leftPadding: M.scale.space.xs
    }
    Repeater {
      model: root.v.asks
      delegate: Rectangle {
        id: chip
        required property string modelData
        objectName: "askChip"
        implicitWidth: label.implicitWidth + 2 * M.scale.space.md
        // the hit target, grown when a large text scale needs the room
        implicitHeight: Math.max(M.size.control, label.implicitHeight + 2 * M.scale.space.xs)
        radius: Math.min(M.radius.chrome, M.radius.chip)
        color: root.tk.raised
        border.width: M.size.keyline
        border.color: root.tk.keyline
        Text {
          textFormat: Text.PlainText
          id: label
          anchors.centerIn: parent
          text: chip.modelData
          color: root.tk.ink
          font.family: root.service ? root.service.fontFamily : ""
          font.pixelSize: M.fontSize("label", root.ts)
        }
      }
    }
  }
}
