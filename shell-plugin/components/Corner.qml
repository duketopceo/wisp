// Corner creature: the resting presence at 28px (40px while listening),
// no backing disc and no glyph. `actions` reveals talk and hide on hover.
// The host window owns placement and layer; this item is only the visual.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/companion.js" as Companion

Item {
  id: root

  property var service: null
  // hover reveals talk and hide; a host can pin it
  property bool actions: hover.hovered
  property real refreshHz: 60
  signal clicked()
  signal talk()
  signal hide()

  readonly property var tk: service ? service.tokens : ({})
  readonly property real box: M.size.creatureListening

  implicitWidth: box + (actions ? talkChip.width + hideChip.width + 3 * M.spacing.md : 0)
  implicitHeight: box
  opacity: service.offline ? 0.6 : 1

  HoverHandler { id: hover }

  // the input region is the creature (and its actions), nothing else
  readonly property var region: Companion.inputRegion(box, actions, talkChip.width + hideChip.width + 3 * M.spacing.md)

  Creature {
    id: creature
    x: root.actions ? root.width - width - (box - width) / 2 : (root.box - width) / 2
    y: (root.box - height) / 2
    service: root.service
    refreshHz: root.refreshHz
  }

  Row {
    visible: root.actions
    anchors.verticalCenter: parent.verticalCenter
    spacing: M.spacing.md
    Chip {
      id: talkChip
      service: root.service
      label: root.service.ui("ui.talk")
      onClicked: root.talk()
    }
    Chip {
      id: hideChip
      service: root.service
      label: root.service.ui("ui.hide")
      onClicked: root.hide()
    }
  }

  MouseArea {
    anchors.fill: creature
    onClicked: root.clicked()
  }
}
