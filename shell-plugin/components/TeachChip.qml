// TeachChip: the teaching step's caption, a "say continue" chip beside the
// "2 of 5" step counter. Text only and click-through: no pointer or focus
// handler, so the layer under it keeps every click. Ink on the raised
// surface, the same pair as Chip, so contrast follows the theme (checked at
// 4.5:1 on every fixture theme in tst_teach). Hidden when the step names no
// chip and no counter, and at once when the step ends.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  // Teach.view(): { chip, counter, visible }
  property var step: null

  readonly property var tk: service ? service.tokens : ({})
  readonly property string chipText: step && step.visible ? step.chip : ""
  readonly property string counterText: step && step.visible ? step.counter : ""
  readonly property bool shown: chipText !== "" || counterText !== ""

  visible: shown
  width: row.implicitWidth
  height: row.implicitHeight
  // never a focus target
  focus: false
  activeFocusOnTab: false

  Row {
    id: row
    spacing: M.spacing.md

    Rectangle {
      objectName: "teachChip"
      visible: root.chipText !== ""
      implicitWidth: chipLabel.implicitWidth + 2 * M.spacing.xl
      implicitHeight: M.size.control
      width: implicitWidth
      height: implicitHeight
      radius: Math.min(M.radius.chrome, M.radius.chip)
      color: root.tk.raised
      border.width: M.size.keyline
      border.color: root.tk.keylineStrong

      Text {
        id: chipLabel
        objectName: "teachChipText"
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.chipText
        color: root.tk.ink
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
      }
    }

    Rectangle {
      objectName: "teachCounter"
      visible: root.counterText !== ""
      implicitWidth: counterLabel.implicitWidth + 2 * M.spacing.xl
      implicitHeight: M.size.control
      width: implicitWidth
      height: implicitHeight
      radius: Math.min(M.radius.chrome, M.radius.chip)
      color: root.tk.raised
      border.width: M.size.keyline
      border.color: root.tk.keyline

      Text {
        id: counterLabel
        objectName: "teachCounterText"
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.counterText
        color: root.tk.ink
        font.family: root.service ? root.service.fontFamily : ""
        font.pixelSize: M.font.label
      }
    }
  }
}
