// First-run card: the onboarding steps (microphone, local models, cua,
// notifications, keybinding) with a state dot, the daemon's one-line
// detail and the actions each state allows. todo: check and skip; skipped:
// check again; done: undo; not available: nothing. Rows come from
// lib/onboard.js (`wispd onboard --status`); the card emits run, skip,
// undo and finish and never starts a service itself.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/onboard.js" as O

Rectangle {
  id: root

  property var service: null
  // steps from `wispd onboard --status --json`
  property var steps: []
  // step ids skipped this session (a skip is never written)
  property var skipped: []
  signal run(string id)
  signal skip(string id)
  signal undo(string id)
  signal finish()

  readonly property var tk: service ? service.tokens : ({})
  readonly property var rows: O.rows(steps, skipped)
  readonly property var count: O.counts(rows)

  width: 340
  implicitHeight: col.implicitHeight + 2 * M.spacing.xxl
  radius: M.radius.chrome
  color: tk.raised
  border.width: M.size.keyline
  border.color: tk.keyline

  function dotColor(state) {
    return state === "done" ? tk.ok : state === "todo" ? tk.needsYou : tk.inkMuted
  }

  Column {
    id: col
    x: M.spacing.xxl
    y: M.spacing.xxl
    width: root.width - 2 * M.spacing.xxl
    spacing: M.spacing.xl

    Row {
      width: parent.width
      spacing: M.spacing.lg
      Text {
        width: parent.width - progress.implicitWidth - M.spacing.lg
        text: root.service.ui("ui.onboard.title")
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.body
        font.weight: Font.DemiBold
      }
      Text {
        id: progress
        text: root.count.done + "/" + root.count.total + " " + root.service.ui("ui.onboard.progress")
        color: root.tk.inkMuted
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
    }

    Repeater {
      model: root.rows
      delegate: Column {
        id: step
        width: col.width
        spacing: M.spacing.sm
        opacity: modelData.state === "na" ? 0.6 : 1

        Row {
          spacing: M.spacing.lg
          Rectangle {
            width: M.spacing.lg
            height: M.spacing.lg
            radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: root.dotColor(modelData.state)
          }
          Text {
            text: root.service.ui("ui.onboard.step." + modelData.id)
            color: root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.font.label
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            text: (modelData.optional ? root.service.ui("ui.onboard.optional") + ", " : "")
              + root.service.ui("ui.onboard.state." + modelData.state)
            color: root.tk.inkMuted
            font.family: root.service.fontFamily
            font.pixelSize: M.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        Text {
          visible: modelData.detail !== ""
          width: parent.width
          text: modelData.detail + (modelData.state === "todo" && modelData.tryText !== ""
            ? ". " + modelData.tryText : "")
          wrapMode: Text.Wrap
          color: root.tk.inkMuted
          font.family: root.service.fontFamily
          font.pixelSize: M.font.caption
        }

        Row {
          visible: modelData.state !== "na"
          spacing: M.spacing.lg
          Chip {
            visible: O.actions(modelData.state).run
            objectName: "run:" + modelData.id
            service: root.service
            label: root.service.ui(modelData.state === "skipped" ? "ui.onboard.again"
              : (modelData.id === "notifications" ? "ui.onboard.run.notifications" : "ui.onboard.run"))
            onClicked: root.run(modelData.id)
          }
          Chip {
            visible: O.actions(modelData.state).skip
            objectName: "skip:" + modelData.id
            service: root.service
            label: root.service.ui("ui.onboard.skip")
            onClicked: root.skip(modelData.id)
          }
          Chip {
            visible: O.actions(modelData.state).undo
            objectName: "undo:" + modelData.id
            service: root.service
            label: root.service.ui("ui.onboard.undo")
            onClicked: root.undo(modelData.id)
          }
        }
      }
    }

    Chip {
      objectName: "finish"
      service: root.service
      label: root.service.ui("ui.onboard.finish")
      onClicked: root.finish()
    }
  }
}
