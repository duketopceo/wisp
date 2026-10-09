// Overlay layer: the Overlay half of the Companion composition: listening
// pill, answer bubble (with the good/wrong chips), beacons and the ghost
// cursor. Window-free: the host window owns the layer and the input region
// (it masks `pill` and `bubbleHost` when shown). `origin` is the output's
// position in the compositor's global layout, so cua.target (global) lands
// on the right pixel while pointer and points stay in layer coordinates.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/metrics.js" as M
import "../lib/cursor.js" as Cursor
import "../lib/companion.js" as Companion

Item {
  id: root

  property var service: null
  // real pointer {x,y} in layer coordinates, or null (bubble then floats
  // above the bottom edge)
  property var pointer: null
  property real originX: 0
  property real originY: 0
  property real gap: 5
  property real refreshHz: 60
  property bool bubbleDismissed: false
  property bool labeled: false
  signal choose(string pick, int index)
  signal confirmChosen(string pick, string promptId)
  signal moreClicked()
  signal verdict(string verdict)

  // a confirm card replaces the pill (it carries the question and the chips)
  readonly property bool pillShown: service !== null && Companion.pillVisible(service.status) && service.confirm === null
  readonly property bool bubbleShown: service !== null && bubble.has && !bubbleDismissed
  readonly property bool bubbleHovered: bubbleHover.hovered
  readonly property bool ghostShown: ghost.shown
  readonly property var beacons: service ? Cursor.beacons(service.points) : []
  readonly property bool shown: pillShown || bubbleShown || ghostShown || beacons.length > 0
  property alias pill: pill
  property alias bubbleHost: bubbleHost

  Pill {
    id: pill
    service: root.service
    visible: root.pillShown
    refreshHz: root.refreshHz
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 96
    onChoose: function (pick, index) { root.choose(pick, index); }
  }

  // answer at the pointer; before the pointer is known it floats above
  // the bottom edge, clear of the listening pill
  Item {
    id: bubbleHost
    visible: root.bubbleShown
    width: bubbleCol.implicitWidth
    height: bubbleCol.implicitHeight
    readonly property var spot: bubble.place
    x: spot ? spot.x : root.width - root.gap - width
    y: spot ? spot.y : root.height - root.gap - M.size.creatureListening - M.spacing.lg - height

    HoverHandler { id: bubbleHover }

    Column {
      id: bubbleCol
      spacing: M.spacing.md

      Bubble {
        id: bubble
        service: root.service
        pointer: root.pointer
        screen: ({ w: root.width, h: root.height })
        onMoreClicked: root.moreClicked()
        onConfirmChosen: function (pick, promptId) { root.confirmChosen(pick, promptId); }
      }

      Row {
        spacing: M.spacing.md
        visible: root.service.status === "done" && root.service.answer !== "" && !root.labeled && root.service.confirm === null
        Chip {
          service: root.service
          label: root.service.ui("ui.label.good")
          onClicked: root.verdict("correct")
        }
        Chip {
          service: root.service
          label: root.service.ui("ui.label.wrong")
          onClicked: root.verdict("incorrect")
        }
      }
    }
  }

  // beacons: state.points are in layer coordinates
  Repeater {
    model: root.beacons
    delegate: Beacon {
      required property var modelData
      service: root.service
      index: modelData.index
      x: modelData.x - width / 2
      y: modelData.y - height
    }
  }

  // cua.target is global: shift the layer origin so the ghost lands on the
  // right pixel. With no live target a guide step (state.guide, layer
  // coordinates) parks the ghost.
  Item {
    x: -root.originX
    y: -root.originY

    GhostCursor {
      id: ghost
      service: root.service
      placed: true
      refreshHz: root.refreshHz
      target: root.service.cuaTarget ? root.service.cuaTarget : guideTarget
      readonly property var guide: root.service.guide
      readonly property var guideTarget: guide ? {
        x: guide.x + root.originX, y: guide.y + root.originY,
        window: "", label: guide.label ? String(guide.label) : "",
        confidence: 1, phase: "aim"
      } : null
    }
  }
}
