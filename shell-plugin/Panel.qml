import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Popup panel for io.github.duketopceo.wisp — opened from the bar glyph.
// Shows daemon status, last transcript, answer, pending choices, and
// running agents. State polling lives in BarWidget.qml; this renders
// hostWidget's properties.
Panel {
  id: wisp
  moduleName: "io.github.duketopceo.wisp"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null

  function open() { wisp.controller.show() }
  function close() { wisp.controller.hide() }
  function toggle() { wisp.opened ? close() : open() }

  readonly property string status: hostWidget ? hostWidget.status : "offline"
  readonly property string transcript: hostWidget ? hostWidget.transcript : ""
  readonly property string answer: hostWidget ? hostWidget.answer : ""
  readonly property string result: hostWidget ? hostWidget.result : ""
  readonly property var choices: hostWidget ? hostWidget.choices : []
  readonly property var tasks: hostWidget ? hostWidget.tasks : ({})
  readonly property string error: hostWidget ? hostWidget.error : ""

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property color accent: Color.accent
  readonly property color urgent: Color.urgent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property color stateColor: status === "listening" ? accent
    : status === "awaiting_choice" || status === "suggestion" ? urgent
    : status === "error" || status === "offline" ? dim
    : fg

  KeyboardPanel {
    id: panel
    anchorItem: wisp.anchorItem
    owner: wisp.hostWidget || wisp
    bar: wisp.bar
    open: wisp.opened
    contentWidth: panel.fittedContentWidth(Style.space(520))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      anchors.fill: parent
      onCloseRequested: wisp.close()
    }

    Column {
      id: content
      width: parent.width
      padding: Style.space(14)
      spacing: Style.space(10)

      Row {
        spacing: Style.space(8)
        Text {
          text: "✦"
          color: wisp.stateColor
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
        Text {
          text: "Wisp — " + wisp.status
          color: wisp.stateColor
          font.family: wisp.fontFamily
          font.pixelSize: Style.font.title
          font.bold: true
        }
      }

      Text {
        visible: wisp.transcript.length > 0
        text: "heard: " + wisp.transcript
        color: wisp.fg
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
        width: parent.width - parent.padding * 2
      }

      Text {
        visible: wisp.answer.length > 0
        text: wisp.answer
        color: wisp.accent
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
        width: parent.width - parent.padding * 2
      }

      Text {
        visible: wisp.result.length > 0
        text: wisp.result
        color: wisp.dim
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
        width: parent.width - parent.padding * 2
      }

      Text {
        visible: wisp.error.length > 0
        text: wisp.error
        color: wisp.urgent
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
        width: parent.width - parent.padding * 2
      }

      Flow {
        visible: wisp.choices.length > 0
        width: parent.width - parent.padding * 2
        spacing: Style.spacing.sm

        Repeater {
          model: wisp.choices
          delegate: Button {
            text: String(modelData).replace(/^suggestion:/, "")
            onClicked: {
              if (wisp.hostWidget) wisp.hostWidget.sendChoice(modelData)
              wisp.close()
            }
          }
        }
      }

      Text {
        visible: Object.keys(wisp.tasks).length > 0
        text: {
          var lines = [];
          for (var k in wisp.tasks)
            lines.push(k + " [" + wisp.tasks[k].status + "]");
          return "agents: " + lines.join("  ");
        }
        color: wisp.dim
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
        width: parent.width - parent.padding * 2
      }

      Text {
        text: "SUPER+D toggles the mic · right-click the glyph to record"
        color: wisp.dim
        font.family: wisp.fontFamily
        font.pixelSize: Style.font.bodySmall
        opacity: 0.7
      }
    }
  }
}
