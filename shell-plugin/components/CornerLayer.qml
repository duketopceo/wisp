// Corner layer: the Top-layer half of the Companion composition. The
// corner creature rests at the bottom-right corner; the console opens
// above it on a click, a pending choice or a confirm. Window-free: the
// host window owns the layer, the visibility rules inputs (`hidden`,
// `fullscreen`, `capped`) and the input region (it masks `corner` and
// `consoleCard` when shown).
import QtQuick
import "../lib/metrics.js" as M
import "../lib/companion.js" as Companion

Item {
  id: root

  property var service: null
  // user hid the creature; a fullscreen window has focus; the console
  // safety net fired
  property bool hidden: false
  property bool fullscreen: false
  property bool capped: false
  property bool userOpen: false
  // distance from the screen edge (the shell's gapsOut)
  property real gap: 5
  property real refreshHz: 60
  signal cornerClicked()
  signal talk()
  signal hide()
  signal stopClicked()

  readonly property bool cornerShown: service !== null && Companion.cornerVisible(hidden, fullscreen)
  readonly property bool consoleShown: service !== null && !fullscreen && !capped && consoleCard.wants
  // width the open console takes, 0 when closed (the bubble steps aside)
  readonly property real consoleExtent: consoleShown ? consoleCard.width + M.spacing.lg : 0
  readonly property bool shown: cornerShown || consoleShown
  property alias corner: corner
  property alias consoleCard: consoleCard

  Corner {
    id: corner
    service: root.service
    visible: root.cornerShown
    refreshHz: root.refreshHz
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.rightMargin: root.gap
    anchors.bottomMargin: root.gap
    onClicked: root.cornerClicked()
    onTalk: root.talk()
    onHide: root.hide()
  }

  Console {
    id: consoleCard
    service: root.service
    userOpen: root.userOpen
    visible: root.consoleShown
    anchors.right: corner.right
    anchors.bottom: corner.top
    anchors.bottomMargin: M.spacing.lg
    onStopClicked: root.stopClicked()
  }
}
