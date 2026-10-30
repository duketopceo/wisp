// Panel Agents tab: one AgentRow per task from the state `tasks` map, or
// the empty state. Task fields: status (queued, running, done, failed,
// cancelled, interrupted), task (the request text) and optional seconds,
// line and waiting (an ask from the agent is pending). An interrupted
// agent gets a say-"continue" hint.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  readonly property var names: Object.keys(service.tasks)

  width: 340

  function stateOf(t) {
    return t.status || "queued"
  }

  function lineOf(t) {
    if (t.status === "interrupted") return "say continue to resume"
    if (t.waiting) return "waiting for your answer"
    return t.line || t.task || ""
  }

  EmptyState {
    visible: root.names.length === 0
    service: root.service
    tab: "agents"
    width: parent.width
  }

  Repeater {
    model: root.names
    delegate: AgentRow {
      width: root.width
      service: root.service
      name: modelData
      state: root.stateOf(root.service.tasks[modelData])
      seconds: Number(root.service.tasks[modelData].seconds) || 0
      line: root.lineOf(root.service.tasks[modelData])
      unread: Boolean(root.service.tasks[modelData].unread)
    }
  }
}
