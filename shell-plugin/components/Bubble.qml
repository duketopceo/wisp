// Answer bubble: the answer (or translated result, or the typed error with
// its hint), on canvas with a keyline; keylineStrong while it belongs to
// the live turn. While a confirm waits it is the confirm card instead: the
// needs-you keyline, what is being asked, allow and deny chips that reply
// with the card's own prompt id, and a one-line note that silence means
// deny. The label prompt and dismissal live in the host (a card ignores
// the dwell).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/cursor.js" as Cursor

Rectangle {
  id: root

  property var service: null
  signal moreClicked()
  // reply to the confirm card: the pick and the prompt id the card shows
  signal confirmChosen(string pick, string promptId)

  // cursor placement: pass the pointer and screen size (both {x,y} / {w,h})
  // and bind x, y to `place`; it flips left or above at screen edges and
  // never covers the pointer hotspot. Null when either is unset.
  property var pointer: null
  property var screen: null
  readonly property var place: (pointer && screen)
    ? Cursor.bubblePlace(pointer, { w: width, h: height }, screen) : null
  // answer width is 60 columns of the answer face
  FontMetrics { id: fm; font.family: service.fontFamily; font.pixelSize: M.font.answer }

  readonly property var tk: service ? service.tokens : ({})
  readonly property bool failed: service.status === "error"
  readonly property var card: service.confirm
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
      visible: root.card !== null
      width: parent.width
      text: root.service.ui("ui.confirm.title")
      color: root.tk.needsYou
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label
      font.weight: Font.DemiBold
    }
    Text {
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
    Row {
      visible: root.card !== null
      spacing: M.spacing.md
      Chip {
        objectName: "allow"
        service: root.service
        label: root.service.ui("ui.confirm.allow")
        onClicked: root.confirmChosen(root.service.choices[0], root.card.promptId)
      }
      Chip {
        objectName: "deny"
        service: root.service
        label: root.service.ui("ui.confirm.deny")
        onClicked: root.confirmChosen(root.service.choices[root.service.choices.length - 1], root.card.promptId)
      }
    }
    Text {
      visible: root.card !== null
      width: parent.width
      text: root.service.ui("ui.confirm.hint")
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.font.caption
    }

    Text {
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
