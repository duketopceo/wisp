// Agent row: name, state word, elapsed time and the last log line.
// States: queued, running (ember tick), done, failed, cancelled,
// interrupted (waiting on the user to say continue).
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  readonly property real ts: service ? service.textScale : 1
  property string name: ""
  property string state: "queued"
  property real seconds: 0
  property string line: ""
  property bool unread: false

  readonly property var tk: service ? service.tokens : ({})
  readonly property var tokenFor: ({ queued: "inkMuted", running: "ember",
    done: "ok", failed: "fail", cancelled: "inkMuted",
    interrupted: "needsYou" })

  implicitWidth: 340
  implicitHeight: col.implicitHeight + 2 * M.scale.space.sm

  Rectangle {
    visible: root.state === "running"
    width: M.size.tick
    height: parent.height
    color: root.tk.ember
  }

  Column {
    id: col
    x: M.scale.space.sm
    y: M.scale.space.sm
    width: root.width - 2 * M.scale.space.sm
    spacing: M.scale.space.xs

    Row {
      width: parent.width
      spacing: M.scale.space.sm
      Rectangle {
        id: unreadDot
        visible: root.unread
        width: M.scale.space.xs
        height: M.scale.space.xs
        radius: M.scale.space.xs
        anchors.verticalCenter: title.verticalCenter
        color: root.tk.ember
      }
      Text {
        textFormat: Text.PlainText
        id: title
        width: parent.width - stateWord.implicitWidth - clock.implicitWidth - (root.unread ? unreadDot.width + M.scale.space.sm : 0) - 2 * M.scale.space.sm
        text: root.name
        elide: Text.ElideRight
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
      }
      Text {
        textFormat: Text.PlainText
        id: stateWord
        text: root.service.ui("ui.agent." + root.state)
        color: root.tk[root.tokenFor[root.state] || "inkMuted"]
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("label", root.ts)
      }
      Text {
        textFormat: Text.PlainText
        id: clock
        text: M.elapsed(root.seconds)
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("caption", root.ts)
      }
    }

    Text {
      textFormat: Text.PlainText
      visible: root.line !== ""
      width: parent.width
      text: root.line
      elide: Text.ElideRight
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("caption", root.ts)
    }
  }
}
