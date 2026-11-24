// Home page of the settings window (one-surface U3, from the retired
// console): the live status word from the status table, a one-line
// description, the last turn, and the talk, restart and stop controls.
// Window-free; actions leave as signals and the shell runs them through
// WispService.runAction.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  signal talk()
  signal restart()
  signal stop()

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property var word: service.wordView
  readonly property string blurbKey: "ui.home." + service.status
  readonly property string blurb: service.ui(blurbKey)
  readonly property string answer: service.answer || service.resultView.text || ""
  readonly property string problem: service.errorMessage || service.error || ""

  width: 560
  spacing: M.scale.space.md

  component Line: Text {
    textFormat: Text.PlainText
    width: root.width
    wrapMode: Text.Wrap
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("body", root.ts)
  }

  Text {
    objectName: "word"
    textFormat: Text.PlainText
    width: root.width
    elide: Text.ElideRight
    text: root.word.word
    color: root.tk[M.toneToken(root.word.tone)]
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("heading", root.ts)
    font.weight: Font.DemiBold
  }
  Line {
    objectName: "blurb"
    // a status with no description falls back to its status word
    text: root.blurb !== root.blurbKey ? root.blurb : root.service.statusWord
  }

  SectionHeader {
    service: root.service
    width: root.width
    title: root.service.ui("ui.home.last")
    visible: root.service.transcript !== "" || root.answer !== "" || root.problem !== ""
  }
  Text {
    objectName: "transcript"
    textFormat: Text.PlainText
    visible: root.service.transcript !== ""
    width: root.width
    wrapMode: Text.Wrap
    text: root.service.transcript
    color: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("answer", root.ts)
  }
  Line {
    objectName: "answer"
    visible: root.answer !== ""
    text: root.answer
  }
  Line {
    objectName: "problem"
    visible: root.problem !== ""
    text: root.problem
    color: root.tk.fail
  }

  Row {
    spacing: M.scale.space.sm
    topPadding: M.scale.space.sm
    Chip {
      objectName: "talk"
      service: root.service
      selected: true
      label: root.service.ui("ui.home.talk")
      focusable: true
      onClicked: root.talk()
    }
    Chip {
      objectName: "restart"
      service: root.service
      label: root.service.ui("ui.home.restart")
      focusable: true
      onClicked: root.restart()
    }
    Chip {
      objectName: "stop"
      service: root.service
      label: root.service.ui("ui.home.stop")
      focusable: true
      onClicked: root.stop()
    }
  }
  Text {
    textFormat: Text.PlainText
    width: root.width
    wrapMode: Text.Wrap
    text: root.service.ui("ui.home.note")
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
  }
}
