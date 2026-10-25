// Panel Now tab: the run card first (U8 — intent, live step, interrupt,
// terminal summary), then goal, what was heard, the answer, the step
// list, choice chips, stop, and the yes/no label row. Reads everything
// from `service`; actions leave as signals (the Panel wires them to the
// service).
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
  readonly property var run: service ? service.run : ({
    present: false, active: false, question: null, key: "" })
  // a terminal card hides on its own "hide"; a new run (new key) shows
  // again — the dismissal dies with the run it was for
  property string dismissedRun: ""
  readonly property bool runShown: run.present
    && (run.active || dismissedRun !== run.key)
  readonly property bool asking: service.result.indexOf("ASK_USER") === 0
  readonly property bool idle: service.transcript === "" && service.answer === ""
    && service.result === "" && service.steps.length === 0
    && service.choices.length === 0 && service.error === ""
    && !(service.note && service.note.rendered)
    && !runShown
  readonly property string noteBody: service.note && service.note.rendered
    ? service.note.rendered : ""
  // the step/action display is the lifecycle stream when a v2 daemon
  // feeds it; `steps` is the same list on older cores
  readonly property var stepRows: service.actions.length > 0
    ? Steps.actionRows(service.actions, service.status, service.promptId)
    : Steps.rows(service.steps, service.busy)
  readonly property bool judgeable: !service.busy && service.status !== "offline"
    && (service.result !== "" || service.transcript !== "")
  // The label verdict's ack: service.lastAction while a label click is
  // the newest event (a state change after it ends the row's moment).
  readonly property var labelAck: service.lastAction
    && service.lastAction.verb === "label"
    && service.lastAction.at >= service.view.changedAtMs
    ? service.lastAction : null
  // a refused choice/interrupt/trigger needs its own nudge — without it
  // a stale pick closes the panel looking like it went through
  readonly property var actionNack: service.lastAction
    && service.lastAction.pending === false
    && service.lastAction.ok === false
    && service.lastAction.verb !== "label"
    && service.lastAction.at >= service.view.changedAtMs
    ? service.lastAction : null

  spacing: M.spacing.xl
  width: 340

  EmptyState {
    visible: root.idle
    service: root.service
    tab: "now"
    width: parent.width
  }

  RunCard {
    visible: root.runShown
    width: parent.width
    service: root.service
    onChoose: function (pick) { root.choose(pick) }
    onAnswer: function (text) { root.choose(text) }
    onStopClicked: root.stopClicked()
    onDismissed: root.dismissedRun = root.run.key
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

  // paper surface (gap-closure U2): rendered note (plan strip + tiles /
  // letter). Plan markers clear from `rendered` when the note closes.
  Text {
    visible: root.noteBody !== ""
    width: parent.width
    text: root.noteBody
    wrapMode: Text.Wrap
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
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
    visible: root.stepRows.length > 0
    width: parent.width
    Repeater {
      model: root.stepRows
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
    // a live question carries its picks inside the run card
    visible: root.service.choices.length > 0 && root.run.question === null
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
    visible: root.actionNack !== null
    width: parent.width
    text: root.actionNack !== null && root.actionNack.message !== ""
      ? root.actionNack.message : root.service.ui("ui.err.unknown")
    wrapMode: Text.Wrap
    color: root.tk.fail
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
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

  // the run card owns its interrupt while a run is non-terminal; this
  // stop stays for busy turns that have no run yet (listening through
  // deciding) and for speaking
  Item {
    width: parent.width
    visible: !root.run.active
    implicitHeight: stop.visible ? stop.implicitHeight : 0
    StopControl {
      id: stop
      service: root.service
      onClicked: root.stopClicked()
    }
  }

  Row {
    visible: root.judgeable && root.labelAck === null
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

  Text {
    visible: root.labelAck !== null
    width: parent.width
    text: root.labelAck !== null && !root.labelAck.pending && root.labelAck.message !== ""
      ? root.labelAck.message : root.service.ui("ui.noted")
    wrapMode: Text.Wrap
    color: root.labelAck !== null && root.labelAck.ok === false ? root.tk.fail : root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.label
  }
}
