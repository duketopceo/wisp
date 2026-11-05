// Rate note: the one-line note a wrong rating offers, typed in the panel's
// Now tab (the overlay takes no keyboard focus). Takes the keyboard when it
// appears. Enter saves the typed text, Esc skips; an empty Enter skips too.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  property alias text: field.text
  signal saved(string text)
  signal skipped()

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: 340
  implicitHeight: M.size.control
  radius: Math.min(M.radius.chrome, M.radius.chip)
  color: tk.raised
  border.width: M.size.keyline
  border.color: field.activeFocus ? tk.accent : tk.keyline

  // a fresh prompt never inherits the last note's text
  onVisibleChanged: if (visible) { field.text = ""; field.forceActiveFocus() }
  Component.onCompleted: if (visible) field.forceActiveFocus()

  TextInput {
    id: field
    anchors.fill: parent
    anchors.leftMargin: M.spacing.xl
    anchors.rightMargin: M.spacing.xl
    verticalAlignment: TextInput.AlignVCenter
    clip: true
    color: root.tk.ink
    selectionColor: root.tk.selection
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
    Accessible.name: root.service ? root.service.ui("ui.rate.note") : ""
    Keys.onReturnPressed: root.finish()
    Keys.onEnterPressed: root.finish()
    Keys.onEscapePressed: { field.text = ""; root.skipped() }
  }

  Text {
    textFormat: Text.PlainText
    anchors.fill: field
    anchors.leftMargin: 0
    verticalAlignment: Text.AlignVCenter
    visible: field.text === ""
    text: root.service ? root.service.ui("ui.rate.note") : ""
    color: root.tk.inkMuted
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
  }

  function finish() {
    var t = field.text.replace(/^\s+|\s+$/g, "");
    field.text = "";
    if (t === "") root.skipped();
    else root.saved(t);
  }
}
