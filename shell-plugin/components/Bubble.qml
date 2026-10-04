// Answer bubble: the answer (or translated result, or the typed error with
// its hint), on canvas with a keyline; keylineStrong while it belongs to
// the live turn. The label prompt and dismissal live in the host.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  signal moreClicked()

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool failed: service.status === "error"
  readonly property bool has: failed || service.answer !== "" || service.resultView.text !== ""
  readonly property bool attached: service.busy || service.status === "speaking"

  visible: has
  implicitWidth: 360
  implicitHeight: has ? col.implicitHeight + 2 * M.spacing.xxl : 0
  radius: M.radius.chrome
  color: tk.canvas
  border.width: M.size.keyline
  border.color: attached ? tk.keylineStrong : tk.keyline

  Column {
    id: col
    x: M.spacing.xxl
    y: M.spacing.xxl
    width: root.width - 2 * M.spacing.xxl
    spacing: M.spacing.md

    Text {
      visible: root.failed
      width: parent.width
      text: root.service.errorMessage !== "" ? root.service.errorMessage : root.service.statusWord
      wrapMode: Text.Wrap
      color: root.tk.fail
      font.family: root.service.fontFamily
      font.pixelSize: M.font.answer
      font.weight: Font.DemiBold
    }
    Text {
      visible: root.failed && root.service.errorHint !== ""
      width: parent.width
      text: root.service.errorHint
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }

    Answer {
      visible: !root.failed && has
      width: parent.width
      service: root.service
      onMoreClicked: root.moreClicked()
    }
  }
}
