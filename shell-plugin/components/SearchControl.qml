// Search field for the settings window (U3). Emits search(text) on every
// edit; Escape clears it (and emits search("")). The host focuses it on
// Ctrl+F through focusField().
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  property alias text: input.text
  property string placeholder: service ? service.ui("ui.search.placeholder") : ""
  property bool focused: input.activeFocus
  signal search(string text)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1

  function focusField() { input.forceActiveFocus(); input.selectAll() }
  function clear() { if (input.text !== "") { input.text = ""; search("") } }

  width: M.scale.field.text
  height: M.controlHeight(false)
  radius: M.pillRadius(height, M.radius.chrome)
  color: root.tk.raised
  border.width: focused ? M.scale.focusRing : M.size.keyline
  border.color: focused ? root.tk.accent : root.tk.keyline

  TextInput {
    id: input
    objectName: "search"
    anchors.fill: parent
    anchors.leftMargin: M.scale.space.md
    anchors.rightMargin: M.scale.space.md
    verticalAlignment: TextInput.AlignVCenter
    color: root.tk.ink
    selectionColor: root.tk.selection
    selectedTextColor: root.tk.ink
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("body", root.ts)
    clip: true
    activeFocusOnTab: true
    Accessible.role: Accessible.EditableText
    Accessible.name: root.placeholder
    onTextEdited: root.search(text)
    Keys.onEscapePressed: (event) => {
      if (input.text === "") { event.accepted = false; return }
      root.clear()
      event.accepted = true
    }
  }

  Text {
    textFormat: Text.PlainText
    visible: input.text === ""
    anchors.fill: input
    verticalAlignment: Text.AlignVCenter
    elide: Text.ElideRight
    text: root.placeholder
    color: root.tk.inkMuted
    font: input.font
  }
}
