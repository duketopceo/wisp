// Agent row: name, state word, elapsed time and the last log line.
// States: queued, running (ember tick), done, failed, cancelled.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property string name: ""
  property string state: "queued"
  property real seconds: 0
  property string line: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property var tokenFor: ({ queued: "inkMuted", running: "ember",
    done: "ok", failed: "fail", cancelled: "inkMuted" })

  implicitWidth: 340
  implicitHeight: col.implicitHeight + 2 * M.spacing.md

  Rectangle {
    visible: root.state === "running"
    width: M.size.tick
    height: parent.height
    color: root.tk.ember
  }

  Column {
    id: col
    x: M.spacing.lg
    y: M.spacing.md
    width: root.width - 2 * M.spacing.lg
    spacing: M.spacing.xs

    Row {
      width: parent.width
      spacing: M.spacing.lg
      Text {
        id: title
        width: parent.width - stateWord.implicitWidth - clock.implicitWidth - 2 * M.spacing.lg
        text: root.name
        elide: Text.ElideRight
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
      }
      Text {
        id: stateWord
        text: root.service.ui("ui.agent." + root.state)
        color: root.tk[root.tokenFor[root.state] || "inkMuted"]
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
      Text {
        id: clock
        text: M.elapsed(root.seconds)
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
    }

    Text {
      visible: root.line !== ""
      width: parent.width
      text: root.line
      elide: Text.ElideRight
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }
}
