// Console card: status line, goal, step timeline, stop. Opens on user
// click or when a choice is pending (the host decides); it never repeats
// the answer, the bubble owns that. The compress watchdog still lives in
// Companion.qml until W21 moves it here unchanged (plan KTD8).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/steps.js" as Steps

Rectangle {
  id: root

  property var service: null
  signal stopClicked()

  readonly property var tk: service ? service.tokens : ({})
  readonly property var rows: Steps.rows(service.steps, service.busy)

  implicitWidth: 340
  implicitHeight: col.implicitHeight + 2 * M.spacing.xxl
  radius: M.radius.chrome
  color: tk.canvas
  border.width: M.size.keyline
  border.color: service.busy ? tk.keylineStrong : tk.keyline

  Column {
    id: col
    x: M.spacing.xxl
    y: M.spacing.xxl
    width: root.width - 2 * M.spacing.xxl
    spacing: M.spacing.lg

    StatusLine { service: root.service }

    Row {
      visible: root.service.goal !== ""
      spacing: M.spacing.md
      width: parent.width
      Text {
        text: root.service.ui("ui.goal")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
        font.letterSpacing: M.font.caption * 0.06
      }
      Text {
        width: parent.width - x
        text: root.service.goal
        elide: Text.ElideRight
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
      }
    }

    Column {
      width: parent.width
      Repeater {
        model: root.rows
        delegate: StepRow {
          required property var modelData
          width: col.width
          service: root.service
          text: modelData.text
          state: modelData.state
          raw: modelData.raw
        }
      }
    }

    Text {
      visible: root.rows.length === 0
      text: root.service.ui("ui.steps.none")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }

    StopControl {
      service: root.service
      onClicked: root.stopClicked()
    }
  }
}
