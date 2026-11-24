// Status line: mark, status word in its tone, the one-line notice
// (offline, newer contract) when there is one, and a quick talk/stop
// action chip on the right so the user can trigger or stop a turn from
// the top of the panel. A host that caps the row sets maxWidth; the
// notice then elides first.
import QtQuick
import "../lib/metrics.js" as M

Row {
  id: root

  property var service: null
  readonly property var tk: service ? service.tokens : ({})
  readonly property var wv: service.wordView
  readonly property bool active: service && (service.busy || service.status === "speaking")
  // 0 means no cap
  property real maxWidth: 0

  spacing: M.spacing.md

  Mark {
    id: mark
    anchors.verticalCenter: parent.verticalCenter
    service: root.service
  }

  Text {
    id: word
    textFormat: Text.PlainText
    anchors.verticalCenter: parent.verticalCenter
    text: root.wv.word
    color: root.tk[M.toneToken(root.wv.tone)]
    font.family: root.service.fontFamily
    font.pixelSize: M.font.body
    font.weight: Font.DemiBold
  }

  Text {
    textFormat: Text.PlainText
    anchors.verticalCenter: parent.verticalCenter
    visible: root.service.notice !== ""
    text: root.service.notice
    width: root.maxWidth > 0
      ? Math.max(0, Math.min(implicitWidth, root.maxWidth - mark.width - word.width
          - (action.visible ? action.width + root.spacing : 0) - 2 * root.spacing))
      : implicitWidth
    elide: Text.ElideRight
    color: root.tk.inkMuted
    font.family: root.service.fontFamily
    font.pixelSize: M.font.caption
  }

  Chip {
    id: action
    objectName: "headerAction"
    visible: root.service !== null && !root.service.offline
    anchors.verticalCenter: parent.verticalCenter
    service: root.service
    label: root.active ? root.service.ui("ui.stop") : root.service.ui("ui.talk")
    onClicked: {
      if (root.active) root.service.interrupt()
      else root.service.trigger()
    }
  }
}
