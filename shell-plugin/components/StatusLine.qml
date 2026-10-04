// Status line: mark, status word in its tone, and the one-line notice
// (offline, stale, newer contract) when there is one. Errors show the
// typed message from the copy table instead of the generic word.
import QtQuick
import "../lib/metrics.js" as M

Row {
  id: root

  property var service: null
  readonly property var tk: service ? service.tokens : ({})
  readonly property string word: service.status === "error" && service.errorCode !== ""
    ? service.errorMessage : service.statusWord

  spacing: M.spacing.md

  Mark {
    anchors.verticalCenter: parent.verticalCenter
    service: root.service
  }

  Text {
    anchors.verticalCenter: parent.verticalCenter
    text: root.word
    color: root.tk[M.toneToken(root.service.statusTone)]
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: Font.DemiBold
  }

  Text {
    anchors.verticalCenter: parent.verticalCenter
    visible: root.service.notice !== ""
    text: root.service.notice
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
  }
}
