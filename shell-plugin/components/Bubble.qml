// Answer bubble: the answer (or translated result, or the typed error with
// its hint), on canvas with a keyline; keylineStrong while it belongs to
// the live turn. While a confirm waits it is the confirm card instead: the
// needs-you keyline, what is being asked, allow and deny chips that reply
// with the card's own prompt id and the picks snapshotted at publish time
// (an in-flight diff can't turn a click into undefined), and a one-line
// note that silence means deny. A `question` card (the act loop's ask_user)
// keeps the same shape: "wisp asks" plus the question, its offered picks
// as verbatim chips, or the say-it hint when the model offered none.
// The label prompt and dismissal live in
// the host (a card ignores the dwell).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/cursor.js" as Cursor

Rectangle {
  id: root

  property var service: null
  signal moreClicked()
  // reply to the confirm card: the pick and the prompt id the card shows
  signal confirmChosen(string pick, string promptId)

  // the bubble's spot lives on the host (OverlayLayer pins it
  // top-center under the bar) — the card itself just sizes and draws
  // answer width is 60 columns of the answer face
  FontMetrics { id: fm; font.family: service.fontFamily; font.pixelSize: M.font.answer }

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool failed: service.status === "error"
  readonly property var card: service.confirm
  readonly property bool question: card !== null && card.kind === "question"
  readonly property bool has: card !== null || failed || service.answer !== "" || service.resultView.text !== ""
  readonly property bool attached: service.busy || service.status === "speaking"

  visible: has
  implicitWidth: Math.round(fm.averageCharacterWidth * Cursor.BUBBLE_COLS) + 2 * M.spacing.xxl
  implicitHeight: has ? col.implicitHeight + 2 * M.spacing.xxl : 0
  radius: M.radius.chrome
  color: tk.canvas
  border.width: M.size.keyline
  border.color: card !== null ? tk.needsYou : (attached ? tk.keylineStrong : tk.keyline)

  Column {
    id: col
    x: M.spacing.xxl
    y: M.spacing.xxl
    width: root.width - 2 * M.spacing.xxl
    spacing: M.spacing.md

    Text {
      textFormat: Text.PlainText
      visible: root.card !== null
      width: parent.width
      text: root.question ? root.service.ui("ui.now.asks") : root.service.ui("ui.confirm.title")
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
      font.weight: Font.DemiBold
    }
    Text {
      textFormat: Text.PlainText
      visible: root.card !== null
      width: parent.width
      text: root.card ? root.card.prompt : ""
      wrapMode: Text.Wrap
      maximumLineCount: Cursor.BUBBLE_LINES
      elide: Text.ElideRight
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.answer
    }
    Text {
      textFormat: Text.PlainText
      // the thing being approved (e.g. the dictation about to send) —
      // approving blind is no approval; daemon caps detail at 4k
      visible: root.card !== null && root.card.detail !== ""
      width: parent.width
      text: root.card ? root.card.detail : ""
      wrapMode: Text.Wrap
      maximumLineCount: Cursor.BUBBLE_LINES - 4
      elide: Text.ElideRight
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }
    Row {
      visible: root.card !== null && !root.question
      spacing: M.spacing.md
      Chip {
        objectName: "allow"
        service: root.service
        // a handoff card (T3) is done/cancel, not allow/deny
        label: root.card && root.card.kind === "handoff"
               ? root.service.ui("ui.confirm.done")
               : root.service.ui("ui.confirm.allow")
        onClicked: root.confirmChosen(root.card.allow, root.card.promptId)
      }
      Repeater {
        // extra picks between allow and deny — the "always" session
        // grant; the chip label is the option itself
        model: root.card ? root.card.middle : []
        delegate: Chip {
          service: root.service
          label: modelData
          onClicked: root.confirmChosen(modelData, root.card.promptId)
        }
      }
      Chip {
        objectName: "deny"
        service: root.service
        label: root.card && root.card.kind === "handoff"
               ? root.service.ui("ui.confirm.cancel")
               : root.service.ui("ui.confirm.deny")
        onClicked: root.confirmChosen(root.card.deny, root.card.promptId)
      }
    }
    // a question's picks answer it verbatim — no allow/deny wording
    Flow {
      visible: root.question && root.card.options.length > 0
      width: parent.width
      spacing: M.spacing.md
      Repeater {
        model: root.question ? root.card.options : []
        delegate: Chip {
          required property var modelData
          service: root.service
          label: modelData
          onClicked: root.confirmChosen(modelData, root.card.promptId)
        }
      }
    }
    Text {
      textFormat: Text.PlainText
      visible: root.card !== null && (!root.question || root.card.options.length === 0)
      width: parent.width
      text: root.question ? root.service.ui("ui.question.hint") : root.service.ui("ui.confirm.hint")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }

    Text {
      textFormat: Text.PlainText
      visible: root.failed && root.card === null
      width: parent.width
      text: root.service.errorMessage !== "" ? root.service.errorMessage : root.service.statusWord
      wrapMode: Text.Wrap
      color: root.tk.fail
      font.family: root.service.fontFamily
      font.pixelSize: M.font.answer
      font.weight: Font.DemiBold
    }
    Text {
      textFormat: Text.PlainText
      visible: root.failed && root.card === null && root.service.errorHint !== ""
      width: parent.width
      text: root.service.errorHint
      wrapMode: Text.Wrap
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
    }

    Answer {
      visible: !root.failed && root.card === null && has
      width: parent.width
      service: root.service
      maxLines: Cursor.BUBBLE_LINES
      onMoreClicked: root.moreClicked()
    }
  }
}
