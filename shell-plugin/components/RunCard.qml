// Run card (plan U8): the "what is wisp doing right now" surface — the
// intent echo, a step cursor with the in-flight step, an interrupt that
// stays reachable while any run entry is non-terminal, and a one-line
// terminal summary (outcome, steps, duration, mutation count with undo
// hints) that persists until the next run or a hide click. A live
// ask_user question renders inside the card: the question, its offered
// picks verbatim, or a typed answer when none were offered. Everything
// reads from service.run (lib/run.js), so a dead or restarted daemon
// can never leave a ghost "running" card.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  signal choose(string pick)
  signal answer(string text)
  signal stopClicked()
  signal dismissed()

  readonly property var tk: service ? service.tokens : ({})
  readonly property var run: service ? service.run : ({
    present: false, active: false, intent: "", key: "", steps: 0,
    stepAt: 0, current: "", outcome: "", durationS: 0, mutations: 0,
    undoRefs: [], question: null })
  readonly property bool active: run.active === true
  readonly property var question: run.question ? run.question : null
  readonly property string summary: {
    if (active || run.outcome === "") return ""
    var parts = [root.service.ui("ui.agent." + run.outcome)]
    parts.push(run.steps + " " + root.service.ui(run.steps === 1 ? "ui.run.step" : "ui.run.steps"))
    if (run.durationS > 0) parts.push(M.elapsed(run.durationS))
    if (run.mutations > 0)
      parts.push(run.mutations + " " + root.service.ui(run.mutations === 1 ? "ui.run.change" : "ui.run.changes"))
    return parts.join(" · ")
  }
  readonly property var outcomeLook: ({
    done: "ok", failed: "fail", cancelled: "inkMuted" })

  implicitWidth: 340
  implicitHeight: col.implicitHeight + 2 * M.spacing.xl
  radius: Math.min(M.radius.chrome, M.radius.chip * 2)
  color: tk.canvas
  border.width: M.size.keyline
  border.color: question !== null ? tk.needsYou : tk.keyline

  Column {
    id: col
    x: M.spacing.xl
    y: M.spacing.xl
    width: root.width - 2 * M.spacing.xl
    spacing: M.spacing.md

    // intent echo — the parsed task, not raw ASR
    Row {
      width: parent.width
      spacing: M.spacing.md
      Icon {
        anchors.verticalCenter: parent.verticalCenter
        name: "act"
        size: M.font.icon
        color: root.active ? root.tk.ember : root.tk.inkMuted
      }
      Text {
        textFormat: Text.PlainText
        width: parent.width - x
        anchors.verticalCenter: parent.verticalCenter
        text: root.run.intent
        elide: Text.ElideRight
        maximumLineCount: 2
        wrapMode: Text.Wrap
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
        font.weight: Font.DemiBold
      }
    }

    // step cursor + in-flight step while the run is live — "step 3/8 ·
    // click Save" — or just the step's name when no tool ran yet
    Text {
      textFormat: Text.PlainText
      visible: root.active
      width: parent.width
      text: {
        var t = ""
        if (root.run.stepAt > 0)
          t = root.service.ui("ui.run.step") + " " + root.run.stepAt + "/" + root.run.steps
        if (root.run.current !== "") t += (t !== "" ? " · " : "") + root.run.current
        return t
      }
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }

    // live ask_user question — same shape as the clarify choices
    Column {
      visible: root.question !== null
      width: parent.width
      spacing: M.spacing.md
      Text {
        textFormat: Text.PlainText
        text: root.service.ui("ui.now.asks")
        color: root.tk.needsYou
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
        font.weight: Font.DemiBold
      }
      Text {
        textFormat: Text.PlainText
        width: parent.width
        text: root.question ? root.question.text : ""
        wrapMode: Text.Wrap
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
      }
      Flow {
        visible: root.question !== null && root.question.options.length > 0
        width: parent.width
        spacing: M.spacing.md
        Repeater {
          model: root.question ? root.question.options : []
          delegate: Chip {
            required property var modelData
            required property int index
            service: root.service
            label: modelData
            hint: index < 3 ? String(index + 1) : ""
            onClicked: root.choose(modelData)
          }
        }
      }
      // free-text answer when the model offered no picks
      Row {
        visible: root.question !== null && root.question.options.length === 0
        width: parent.width
        spacing: M.spacing.md
        Rectangle {
          width: parent.width - sendChip.implicitWidth - parent.spacing
          height: M.size.control
          radius: Math.min(M.radius.chrome, M.radius.chip)
          color: root.tk.raised
          border.width: M.size.keyline
          border.color: input.activeFocus ? root.tk.accent : root.tk.keyline
          TextInput {
            id: input
            anchors.fill: parent
            anchors.margins: M.spacing.lg
            verticalAlignment: TextInput.AlignVCenter
            color: root.tk.ink
            selectionColor: root.tk.selection
            font.family: root.service.fontFamily
            font.pixelSize: M.font.body
            clip: true
            onAccepted: if (sendChip.enabled) sendChip.clicked()
            Text {
              textFormat: Text.PlainText
              visible: input.text === ""
              anchors.verticalCenter: parent.verticalCenter
              text: root.service.ui("ui.question.answer")
              color: root.tk.inkMuted
              font.family: root.service.fontFamily
              font.pixelSize: M.font.body
            }
          }
        }
        Chip {
          id: sendChip
          service: root.service
          label: root.service.ui("ui.question.send")
          enabled: input.text.replace(/^\s+|\s+$/g, "") !== ""
          onClicked: {
            root.answer(input.text)
            input.text = ""
          }
        }
      }
    }

    // terminal summary — persists until the next run or a hide click
    Row {
      visible: !root.active && root.summary !== ""
      width: parent.width
      spacing: M.spacing.md
      Text {
        textFormat: Text.PlainText
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width
          - (undoText.visible ? undoText.implicitWidth + M.spacing.md : 0)
          - hideText.implicitWidth - M.spacing.md
        text: root.summary
        elide: Text.ElideRight
        color: root.tk[root.outcomeLook[root.run.outcome] || "inkMuted"]
        font.family: root.service.fontFamily
        font.pixelSize: M.font.label
      }
      Text {
        textFormat: Text.PlainText
        id: undoText
        visible: root.run.undoRefs.length > 0
        anchors.verticalCenter: parent.verticalCenter
        text: "(" + root.service.ui("ui.undo") + ": " + root.run.undoRefs.join(", ") + ")"
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
      Text {
        textFormat: Text.PlainText
        id: hideText
        anchors.verticalCenter: parent.verticalCenter
        text: root.service.ui("ui.hide")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
        MouseArea {
          anchors.fill: parent
          onClicked: root.dismissed()
        }
      }
    }

    // interrupt — always reachable while any run entry is non-terminal;
    // positioners skip it once the run resolves
    StopControl {
      service: root.service
      visible: root.active
      onClicked: root.stopClicked()
    }
  }
}
