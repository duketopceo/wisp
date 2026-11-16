// Choice setting as a row of options (U3). Labels show underscores as
// spaces; commit(value) carries the raw option. Click picks an option;
// with focus, Left/Right/Home/End move the choice and commit it at once
// (selects save on change). Wraps onto more lines when narrow.
import QtQuick
import "../lib/metrics.js" as M

Flow {
  id: root

  property var service: null
  property var options: []
  property string value: ""
  property string label: ""
  // option under the pointer, -1 for none; the harness may set it
  property int hoveredIndex: -1
  property bool focused: activeFocus
  signal commit(string value)

  readonly property var tk: service ? service.tokens : ({})
  readonly property real ts: service ? service.textScale : 1
  readonly property int current: {
    for (var i = 0; i < options.length; i++)
      if (String(options[i]) === value) return i
    return -1
  }

  // width that fits every option on one line, for the row layout
  readonly property real naturalWidth: {
    var w = 0, n = 0
    for (var i = 0; i < children.length; i++) {
      var c = children[i]
      if (String(c.objectName).indexOf("opt:") !== 0) continue
      w += c.implicitWidth
      n += 1
    }
    return w + Math.max(0, n - 1) * spacing
  }

  function display(opt) { return String(opt).replace(/_/g, " ") }
  function pick(i) {
    if (!enabled || i < 0 || i >= options.length) return
    var v = String(options[i])
    if (v !== value) commit(v)
  }

  // lay out now, not at the next polish, so a host that reads the
  // height right after setting the width (the row, the harness) sees it
  onWidthChanged: forceLayout()
  onOptionsChanged: forceLayout()
  Component.onCompleted: forceLayout()

  width: 480
  spacing: M.scale.space.sm
  activeFocusOnTab: true
  opacity: enabled ? 1 : 0.5

  Accessible.role: Accessible.RadioButton
  Accessible.name: label
  Accessible.description: current >= 0 ? display(options[current]) : ""

  Keys.onPressed: (event) => {
    // a held arrow would send a write per repeat from a stale value
    if (event.isAutoRepeat) { event.accepted = true; return }
    var i = root.current
    if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) i = Math.min(root.options.length - 1, i + 1)
    else if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) i = Math.max(0, i - 1)
    else if (event.key === Qt.Key_Home) i = 0
    else if (event.key === Qt.Key_End) i = root.options.length - 1
    else return
    root.pick(i)
    event.accepted = true
  }

  Repeater {
    model: root.options
    delegate: Rectangle {
      id: opt
      required property var modelData
      required property int index
      readonly property bool chosen: index === root.current
      readonly property bool hot: index === root.hoveredIndex
      objectName: "opt:" + String(modelData)
      implicitWidth: optText.implicitWidth + 2 * M.scale.space.md
      width: implicitWidth
      height: M.controlHeight(false)
      radius: Math.min(M.radius.chrome, M.radius.chip)
      color: chosen ? root.tk.selection : root.tk.raised
      border.width: M.size.keyline
      border.color: chosen ? root.tk.accent : (hot ? root.tk.keylineStrong : root.tk.keyline)

      Text {
        id: optText
        textFormat: Text.PlainText
        anchors.centerIn: parent
        text: root.display(opt.modelData)
        color: opt.chosen ? root.tk.accent : root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.fontSize("label", root.ts)
      }

      Rectangle {
        visible: root.focused && (opt.chosen || (root.current < 0 && opt.index === 0))
        anchors.fill: parent
        anchors.margins: -M.scale.focusRing
        radius: parent.radius + M.scale.focusRing
        color: "transparent"
        border.width: M.scale.focusRing
        border.color: root.tk.accent
      }

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        onContainsMouseChanged: root.hoveredIndex = containsMouse ? opt.index
          : (root.hoveredIndex === opt.index ? -1 : root.hoveredIndex)
        onClicked: { root.forceActiveFocus(); root.pick(opt.index) }
      }
    }
  }
}
