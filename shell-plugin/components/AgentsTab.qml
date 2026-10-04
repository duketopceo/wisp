// Panel Agents tab: one AgentRow per task from the state `tasks` map, or
// the empty state. Task fields: status (queued, running, done, failed,
// cancelled), task (the request text) and optional seconds and line.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  readonly property var names: Object.keys(service.tasks)

  width: 340

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
      state: root.service.tasks[modelData].status || "queued"
      seconds: Number(root.service.tasks[modelData].seconds) || 0
      line: root.service.tasks[modelData].line || root.service.tasks[modelData].task || ""
    }
  }
}
