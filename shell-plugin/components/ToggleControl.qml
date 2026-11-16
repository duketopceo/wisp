// Switch for a bool setting (U3). Shows `checked` and emits
// commit("true") or commit("false") on click or Space; the host saves the
// value and passes it back. Hover, pressed and focus come from input
// unless a caller (or the snapshot harness) sets them.
import QtQuick
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  property bool checked: false
  property string label: ""
  property bool hovered: area.containsMouse
  property bool pressed: area.pressed
  property bool focused: activeFocus
  signal commit(string value)

  readonly property var tk: service ? service.tokens : ({})

  function toggle() {
    if (enabled) commit(checked ? "false" : "true")
  }

  implicitWidth: M.scale.toggle.width + 2 * M.scale.focusRing
  implicitHeight: M.controlHeight(false)
  activeFocusOnTab: true
  opacity: enabled ? 1 : 0.5

  Accessible.role: Accessible.CheckBox
  Accessible.name: label
  Accessible.checkable: true
  Accessible.checked: checked
  Accessible.onPressAction: toggle()

  Keys.onSpacePressed: (event) => { toggle(); event.accepted = true }

  Rectangle {
    id: track
    anchors.centerIn: parent
    width: M.scale.toggle.width
    height: M.scale.toggle.height
    radius: M.pillRadius(height, M.radius.chrome)
    color: root.checked ? root.tk.accent : (root.pressed ? root.tk.selection : root.tk.raised)
    border.width: M.size.keyline
    border.color: root.checked ? root.tk.accent
      : (root.hovered ? root.tk.keylineStrong : root.tk.keyline)

    Rectangle {
      id: knob
      readonly property int inset: 3
      width: track.height - 2 * inset
      height: width
      radius: M.pillRadius(height, M.radius.chrome)
      y: inset
      x: root.checked ? track.width - width - inset : inset
      color: root.checked ? root.tk.canvas : root.tk.inkMuted
    }
  }

  Rectangle {
    visible: root.focused
    anchors.centerIn: track
    width: track.width + 2 * M.scale.focusRing
    height: track.height + 2 * M.scale.focusRing
    radius: M.pillRadius(height, M.radius.chrome)
    color: "transparent"
    border.width: M.scale.focusRing
    border.color: root.tk.accent
  }

  MouseArea {
    id: area
    anchors.fill: parent
    hoverEnabled: true
    enabled: root.enabled
    onClicked: { root.forceActiveFocus(); root.toggle() }
  }
}
