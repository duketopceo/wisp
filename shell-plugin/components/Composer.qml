// Composer: the one-line typed question a double tap of Control opens next
// to the companion. The host sets `open` when the daemon's `composer` stream
// event arrives. It takes the keyboard while open; Enter sends the text as an
// ordinary `ask` (service.askAbout), the same turn path and conversation as a
// spoken question, then closes. Esc or an empty Enter closes without sending.
import QtQuick
import "../lib/metrics.js" as M

Rectangle {
  id: root

  property var service: null
  property bool open: false
  property alias text: field.text
  // emitted with the trimmed text just before it is sent
  signal submitted(string text)
  signal dismissed()

  readonly property var tk: service ? service.tokens : ({})

  implicitWidth: 360
  implicitHeight: M.size.control
  visible: open
  radius: Math.min(M.radius.chrome, M.radius.chip)
  color: tk.raised
  border.width: M.size.keyline
  border.color: field.activeFocus ? tk.accent : tk.keyline

  // a fresh open never inherits the last question's text
  onOpenChanged: {
    if (open) { field.text = ""; field.forceActiveFocus() }
  }

  TextInput {
    id: field
    anchors.fill: parent
    anchors.leftMargin: M.spacing.xl
    anchors.rightMargin: M.spacing.xl
    verticalAlignment: TextInput.AlignVCenter
    clip: true
    maximumLength: 300
    color: root.tk.ink
    selectionColor: root.tk.selection
    font.family: root.service ? root.service.fontFamily : ""
    font.pixelSize: M.font.label
    Accessible.name: root.service ? root.service.ui("ui.question.send") : ""
    Keys.onReturnPressed: root.finish()
    Keys.onEnterPressed: root.finish()
    Keys.onEscapePressed: root.close()
  }

  function close() {
    field.text = "";
    root.open = false;
    root.dismissed();
  }

  // state settles before the signal: the host may unload this window
  function finish() {
    var t = field.text.replace(/^\s+|\s+$/g, "");
    if (t === "") { root.close(); return; }
    field.text = "";
    root.open = false;
    if (root.service) root.service.askAbout(t);
    root.submitted(t);
  }
}
