// Tasks page of the settings window (one-surface U3, from the retired
// console's Agents view; keyed `tasks` because `agents` is a config
// category): a field to start a background agent, then one AgentRow per
// task in the state `tasks` map with Cancel on running ones. start(text)
// and cancel(name) leave as signals for the shell to run.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/manage.js" as Manage

Column {
  id: root

  property var service: null
  signal start(string text)
  signal cancel(string name)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property var names: Object.keys(service.tasks || {})

  function send() {
    var t = input.text.trim()
    if (t === "") return
    root.start(t)
    input.text = ""
  }

  width: 560
  spacing: M.scale.space.md

  Row {
    width: root.width
    spacing: M.scale.space.sm
    Rectangle {
      width: parent.width - go.width - parent.spacing
      height: M.controlHeight(false)
      radius: Math.min(M.radius.chrome, M.radius.chip)
      color: root.tk.raised
      border.width: input.activeFocus ? M.scale.focusRing : M.size.keyline
      border.color: input.activeFocus ? root.tk.accent : root.tk.keyline
      TextInput {
        id: input
        objectName: "taskInput"
        anchors.fill: parent
        anchors.leftMargin: M.scale.space.md
        anchors.rightMargin: M.scale.space.md
        verticalAlignment: TextInput.AlignVCenter
        clip: true
        selectByMouse: true
        activeFocusOnTab: true
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
        Accessible.name: root.service.ui("ui.tasks.placeholder")
        onAccepted: root.send()
        Text {
          textFormat: Text.PlainText
          anchors.verticalCenter: parent.verticalCenter
          visible: input.text === ""
          text: root.service.ui("ui.tasks.placeholder")
          color: root.tk.inkMuted
          font: input.font
        }
      }
    }
    Chip {
      id: go
      objectName: "start"
      height: M.controlHeight(false)
      service: root.service
      selected: true
      label: root.service.ui("ui.tasks.start")
      focusable: true
      onClicked: root.send()
    }
  }

  EmptyState {
    objectName: "empty"
    visible: root.names.length === 0
    service: root.service
    tab: "agents"
    width: root.width
  }

  Repeater {
    model: root.names
    delegate: Item {
      id: task
      required property string modelData
      readonly property var t: Manage.taskOf(root.service.tasks[modelData])
      objectName: "task:" + modelData
      width: root.width
      height: Math.max(row.height, stop.height)
      AgentRow {
        id: row
        width: parent.width - (stop.visible ? stop.width + M.scale.space.sm : 0)
        service: root.service
        name: task.modelData
        state: task.t.status || "queued"
        line: Manage.taskHintKey(task.t) !== "" ? root.service.ui(Manage.taskHintKey(task.t))
          : (task.t.line || task.t.task || "")
        seconds: Number(task.t.seconds) || 0
        unread: Boolean(task.t.unread)
      }
      Chip {
        id: stop
        objectName: "cancel"
        visible: task.t.status === "running"
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        service: root.service
        label: root.service.ui("ui.tasks.cancel")
        focusable: true
        Accessible.name: label + " " + task.modelData
        onClicked: root.cancel(task.modelData)
      }
    }
  }
}
