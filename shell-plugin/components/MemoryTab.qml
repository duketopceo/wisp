// Panel Memory tab: imported skills and the recent decision ledger. Both
// lists are data the Panel hands in (read once from skills.json and
// decisions.jsonl by the shell side); this item only draws them.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  property var skills: []
  // [{ts, route, text, res, failed}]
  property var decisions: []
  property int maxSkills: 8
  property int maxDecisions: 8

  readonly property var tk: service ? service.tokens : ({})

  width: 340
  spacing: M.spacing.xl

  EmptyState {
    visible: root.skills.length === 0 && root.decisions.length === 0
    service: root.service
    tab: "memory"
    width: parent.width
  }

  Column {
    visible: root.skills.length > 0
    width: parent.width
    spacing: M.spacing.sm
    Text {
      text: root.skills.length + " " + root.service.ui("ui.memory.skills")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }
    Repeater {
      model: root.skills.slice(0, root.maxSkills)
      delegate: Text {
        width: root.width
        text: modelData.name + (modelData.description ? "  " + modelData.description : "")
        elide: Text.ElideRight
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
    }
    Text {
      visible: root.skills.length > root.maxSkills
      text: root.service.ui("ui.memory.more")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
  }

  Column {
    visible: root.decisions.length > 0
    width: parent.width
    spacing: M.spacing.sm
    Text {
      text: root.service.ui("ui.memory.activity")
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.body
      font.weight: Font.DemiBold
    }
    Repeater {
      model: root.decisions.slice(0, root.maxDecisions)
      delegate: Text {
        width: root.width
        text: modelData.ts + "  " + modelData.route + "  " + modelData.text
        elide: Text.ElideRight
        color: modelData.failed ? root.tk.fail : root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
    }
  }
}
