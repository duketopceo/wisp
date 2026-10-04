// One step of a turn: state icon plus the humanized step text. States:
// pending, running (2px ember tick), done, failed, confirm (needs your ok).
// The raw tool string stays on `raw` for a tooltip or details view.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property string text: ""
  property string state: "done"
  property string raw: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property var look: ({
    pending: { icon: "history", token: "inkMuted" },
    running: { icon: "act", token: "ember" },
    done: { icon: "check", token: "ok" },
    failed: { icon: "cross", token: "fail" },
    confirm: { icon: "warning", token: "needsYou" }
  })
  readonly property var mine: look[state] || look.done

  implicitWidth: 300
  implicitHeight: Math.max(M.size.control - M.spacing.lg, label.implicitHeight)

  Rectangle {
    visible: root.state === "running"
    width: M.size.tick
    height: parent.height
    color: root.tk.ember
  }

  Icon {
    id: icon
    x: M.spacing.lg
    anchors.verticalCenter: parent.verticalCenter
    name: root.mine.icon
    size: M.font.icon
    color: root.tk[root.mine.token]
  }

  Text {
    id: label
    x: icon.x + icon.width + M.spacing.md
    width: root.width - x - (root.state === "confirm" ? confirmTag.implicitWidth + M.spacing.lg : 0)
    anchors.verticalCenter: parent.verticalCenter
    text: root.text
    elide: Text.ElideRight
    color: root.state === "pending" ? root.tk.inkMuted : root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
  }

  Text {
    id: confirmTag
    visible: root.state === "confirm"
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    text: root.service.ui("ui.step.confirm")
    color: root.tk.needsYou
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
  }
}
