// Text or number field for a setting (U3). `key` names the schema field
// (lib/settings.js validate). The draft is checked as it is typed; the
// error shows under the field and nothing is sent while it is invalid.
// Enter or leaving the field commits a valid, changed draft through
// commit(value); Escape puts the saved value back.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/settings.js" as S

Column {
  id: root

  property var service: null
  property string key: ""
  property string kind: "text"
  property string value: ""
  property string unit: ""
  property string label: ""
  property string placeholder: ""
  property bool focused: input.activeFocus
  property alias text: input.text
  // starting draft instead of the saved value (restored drafts, harness)
  property string draft: ""
  // the host's room for the control; the field shrinks to fit, never
  // below the number-field width
  property real maxWidth: M.scale.field.text
  signal commit(string value)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property bool numeric: kind === "int" || kind === "usd"
  // copy key of the current problem, "" when the draft may be sent
  readonly property string problem: key !== "" ? S.validate(key, input.text) : ""
  readonly property bool dirty: S.trim(input.text) !== S.trim(value)
  // width wanted on one line, for the row layout
  readonly property real naturalWidth: (numeric ? M.scale.field.number : M.scale.field.text)
    + (unitText.visible ? M.scale.space.sm + unitText.implicitWidth : 0)

  // the draft last sent, so Enter followed by leaving the field (or a
  // second Enter before the host saves) sends it once
  property string sentDraft: ""

  function tryCommit() {
    var v = S.trim(input.text)
    if (!enabled || problem !== "" || !dirty || v === sentDraft) return false
    sentDraft = v
    commit(v)
    return true
  }
  function revert() { input.text = value }

  onValueChanged: {
    sentDraft = ""
    if (!input.activeFocus) input.text = value
  }
  Component.onCompleted: {
    input.text = draft !== "" ? draft : value
    line.forceLayout()
    forceLayout()
  }

  spacing: M.scale.space.xs
  opacity: enabled ? 1 : 0.5

  Row {
    id: line
    spacing: M.scale.space.sm

    Rectangle {
      id: box
      width: Math.min(root.numeric ? M.scale.field.number : M.scale.field.text,
                      Math.max(M.scale.field.number, root.maxWidth - (unitText.visible ? M.scale.space.sm + unitText.implicitWidth : 0)))
      height: M.controlHeight(false)
      radius: Math.min(M.radius.chrome, M.radius.chip)
      color: root.tk.raised
      border.width: root.focused ? M.scale.focusRing : M.size.keyline
      border.color: root.problem !== "" ? root.tk.fail
        : (root.focused ? root.tk.accent : root.tk.keyline)

      TextInput {
        id: input
        objectName: "input:" + root.key
        anchors.fill: parent
        anchors.leftMargin: M.scale.space.sm
        anchors.rightMargin: M.scale.space.sm
        verticalAlignment: TextInput.AlignVCenter
        horizontalAlignment: root.numeric ? TextInput.AlignRight : TextInput.AlignLeft
        color: root.tk.ink
        selectionColor: root.tk.selection
        selectedTextColor: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("body", root.ts)
        inputMethodHints: root.numeric ? Qt.ImhFormattedNumbersOnly : Qt.ImhNone
        clip: true
        activeFocusOnTab: true
        enabled: root.enabled
        Accessible.role: Accessible.EditableText
        Accessible.name: root.label
        Accessible.description: root.problem !== "" ? root.service.ui(root.problem) : ""
        onTextEdited: root.sentDraft = ""
        onAccepted: root.tryCommit()
        onEditingFinished: root.tryCommit()
        Keys.onEscapePressed: (event) => { root.revert(); event.accepted = true }
      }

      Text {
        textFormat: Text.PlainText
        visible: input.text === "" && root.placeholder !== ""
        anchors.fill: input
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: input.horizontalAlignment
        elide: Text.ElideRight
        text: root.placeholder
        color: root.tk.inkMuted
        font: input.font
      }
    }

    Text {
      id: unitText
      textFormat: Text.PlainText
      visible: root.unit !== ""
      anchors.verticalCenter: box.verticalCenter
      text: root.unit
      color: root.tk.inkMuted
      font.family: root.service.fontFamily
      font.pixelSize: M.fontSize("label", root.ts)
    }
  }

  Text {
    objectName: "problem:" + root.key
    textFormat: Text.PlainText
    visible: root.problem !== ""
    width: line.width
    wrapMode: Text.Wrap
    text: root.problem !== "" ? root.service.ui(root.problem) : ""
    color: root.tk.fail
    font.family: root.service.fontFamily
    font.pixelSize: M.fontSize("caption", root.ts)
  }
}
