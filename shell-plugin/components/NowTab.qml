// Panel Now tab: goal, what was heard, the answer, the step list, choice
// chips, stop, and the yes/no label row. Reads everything from `service`;
// actions leave as signals (the Panel wires them to the service).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/steps.js" as Steps

Column {
  id: root

  property var service: null
  signal choose(string pick)
  signal stopClicked()
  signal labelClicked(string verdict)

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool asking: service.result.indexOf("ASK_USER") === 0
  readonly property bool idle: service.transcript === "" && service.answer === ""
    && service.result === "" && service.steps.length === 0
    && service.choices.length === 0 && service.error === ""
  readonly property bool judgeable: !service.busy && service.status !== "offline"
    && (service.result !== "" || service.transcript !== "")

  spacing: M.spacing.xl
  width: 340

  EmptyState {
    visible: root.idle
    service: root.service
    tab: "now"
    width: parent.width
  }

  Text {
    visible: root.service.goal !== ""
    width: parent.width
    text: root.service.ui("ui.goal") + ": " + root.service.goal
    wrapMode: Text.Wrap
    color: root.tk.ember
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
  }

  Transcript {
    service: root.service
    width: parent.width
    maxLines: 3
  }

  Answer {
    service: root.service
    width: parent.width
    maxLines: 8
  }

  Text {
    visible: root.asking
    width: parent.width
    text: root.service.ui("ui.now.asks") + ": " + root.service.result.slice(9).replace(/^[:\s]+/, "")
    wrapMode: Text.Wrap
    color: root.tk.needsYou
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: Font.DemiBold
  }

  Column {
    visible: root.service.steps.length > 0
    width: parent.width
    Repeater {
      model: Steps.rows(root.service.steps, root.service.busy)
      delegate: StepRow {
        width: root.width
        service: root.service
        text: modelData.text
        state: modelData.state
        raw: modelData.raw
      }
    }
  }

  Flow {
    visible: root.service.choices.length > 0
    width: parent.width
    spacing: M.spacing.lg
    Repeater {
      model: root.service.choices
      delegate: Chip {
        service: root.service
        label: root.service.pickLabel(modelData)
        hint: String(index + 1)
        onClicked: root.choose(modelData)
      }
    }
  }

  Text {
    visible: root.service.error !== "" || root.service.status === "error"
    width: parent.width
    text: root.service.errorMessage + (root.service.errorHint !== "" ? ". " + root.service.errorHint : "")
    wrapMode: Text.Wrap
    color: root.tk.fail
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }

  StopControl {
    service: root.service
    onClicked: root.stopClicked()
  }

  Row {
    visible: root.judgeable
    spacing: M.spacing.lg
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: root.service.ui("ui.now.right")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }
    Chip {
      service: root.service
      label: root.service.ui("ui.now.yes")
      onClicked: root.labelClicked("correct")
    }
    Chip {
      service: root.service
      label: root.service.ui("ui.now.no")
      onClicked: root.labelClicked("incorrect")
    }
  }
}
