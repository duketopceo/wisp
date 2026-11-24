// Memory page of the settings window (one-surface U3, from the retired
// console): MEMORY.md and USER.md, the notes Wisp reads at the start of
// every turn, each in an editor with Save. The shell reads the files and
// writes through `wispd memory write`; save(which, text) carries the edit.
import QtQuick
import "../lib/metrics.js" as M

Column {
  id: root

  property var service: null
  property string memoryText: ""
  property string userText: ""
  signal save(string which, string text)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1

  width: 560
  spacing: M.scale.space.lg

  EmptyState {
    objectName: "empty"
    visible: root.memoryText.trim() === "" && root.userText.trim() === ""
    service: root.service
    tab: "memory"
    width: root.width
  }

  Repeater {
    model: [["memory", "MEMORY.md", "ui.memory.facts"], ["user", "USER.md", "ui.memory.user"]]
    delegate: Column {
      id: note
      required property var modelData
      required property int index
      objectName: "note:" + modelData[0]
      width: root.width
      spacing: M.scale.space.sm

      SectionHeader {
        service: root.service
        width: parent.width
        first: note.index === 0
        title: note.modelData[1]
        note: root.service.ui(note.modelData[2])
      }
      Rectangle {
        width: parent.width
        height: 180
        radius: Math.min(M.radius.chrome, M.radius.chip)
        color: root.tk.raised
        border.width: edit.activeFocus ? M.scale.focusRing : M.size.keyline
        border.color: edit.activeFocus ? root.tk.accent : root.tk.keyline
        Flickable {
          anchors.fill: parent
          anchors.margins: M.scale.space.sm
          contentWidth: width
          contentHeight: edit.height
          clip: true
          TextEdit {
            id: edit
            objectName: "edit"
            width: parent.width
            wrapMode: TextEdit.Wrap
            textFormat: TextEdit.PlainText
            selectByMouse: true
            activeFocusOnTab: true
            text: note.index === 0 ? root.memoryText : root.userText
            color: root.tk.ink
            font.family: root.service.fontFamily
            font.pixelSize: M.fontSize("body", root.ts)
            Accessible.name: note.modelData[1]
          }
        }
      }
      Chip {
        objectName: "save"
        service: root.service
        label: root.service.ui("ui.memory.save")
        focusable: true
        Accessible.name: label + " " + note.modelData[1]
        onClicked: root.save(note.modelData[0], edit.text)
      }
    }
  }
}
