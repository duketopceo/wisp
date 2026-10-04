// Answer text: wrapped at the component width, ember block caret while it
// is streaming, and a "more" link when it is cut at maxLines. Shows the
// translated result text when the turn produced no spoken answer.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property int maxLines: 6
  property bool streaming: service ? service.status === "speaking" : false
  signal moreClicked()

  readonly property var tk: service ? service.tokens : ({})
  readonly property string body: service.answer !== "" ? service.answer : service.resultView.text
  readonly property bool truncated: text.truncated
  readonly property bool has: body !== ""

  implicitWidth: 320
  implicitHeight: has ? col.implicitHeight : 0
  visible: has

  property real lastX: 0
  property real lastY: 0
  property real lastH: M.font.answer

  Column {
    id: col
    width: root.width
    spacing: M.spacing.sm

    Text {
      id: text
      width: parent.width
      text: root.body
      color: root.tk.ink
      font.family: root.service.fontFamily
      font.pixelSize: M.font.answer
      lineHeight: M.lineHeight
      wrapMode: Text.Wrap
      maximumLineCount: root.maxLines
      elide: Text.ElideRight
      onLineLaidOut: function (line) {
        root.lastX = line.x + line.implicitWidth;
        root.lastY = line.y;
        root.lastH = line.height;
      }

      Rectangle {
        visible: root.streaming
        x: root.lastX + M.spacing.xs
        y: root.lastY + (root.lastH - height) / 2
        width: Math.round(M.font.answer * 0.55)
        height: Math.round(M.font.answer * 1.0)
        color: root.tk.ember
      }
    }

    Text {
      visible: root.truncated
      text: root.service.ui("ui.more")
      color: root.tk.accent
      font.family: root.service.fontFamily
      font.pixelSize: M.font.label

      MouseArea {
        anchors.fill: parent
        onClicked: root.moreClicked()
      }
    }
  }
}
