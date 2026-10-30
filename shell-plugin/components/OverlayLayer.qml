// Overlay layer: the Overlay half of the Companion composition: listening
// pill, answer bubble (with the good/wrong rate row), beacons and the cursor
// buddy. Window-free: the host window owns the layer and the input region
// (it masks `pill` and `bubbleHost` when shown; the buddy is click-through).
// The host hands the buddy's view in layer coordinates, so pointer, targets
// and points all land on the right pixel here.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/metrics.js" as M
import "../lib/cursor.js" as Cursor
import "../lib/companion.js" as Companion
import "../lib/card.js" as CardLib
import "../lib/model3d.js" as ModelLib
import "../lib/scribble.js" as Scribble
import "../lib/chips.js" as ChipsLib

Item {
  id: root

  property var service: null
  readonly property var tk: service ? service.tokens : ({})
  // height of the top bar the bubble parks under (Style.bar.sizeVertical)
  property real barHeight: 28
  property real gap: 5
  property real refreshHz: 60
  property bool bubbleDismissed: false
  // lib/buddy.js view(), computed by the host once per frame (null keeps
  // Buddy's own hidden view); wanted keeps the window mapped through the
  // live turn and the dwell-and-return tail
  property var buddyView: null
  property bool buddyWanted: false
  signal choose(string pick, int index)
  signal confirmChosen(string pick, string promptId)
  signal moreClicked()
  signal verdict(string verdict, string turn)
  // strokes drawn while listening, for the daemon (see ScribbleLayer)
  signal scribbled(var payload)

  // a confirm card replaces the pill (it carries the question and the
  // chips); on a v2 daemon the card is the stream's awaiting confirm
  // entry, normalized into service.confirm
  readonly property bool pillShown: service !== null && Companion.pillVisible(service.status) && service.confirm === null
  readonly property bool bubbleShown: service !== null && bubble.has && !bubbleDismissed
  readonly property bool bubbleHovered: bubbleHover.hovered
  readonly property bool buddyShown: buddyWanted || (buddyView !== null && buddyView.visible)
  // the label pill's size, read back so the host can flip it at screen edges
  readonly property real buddyPillWidth: buddy.pillWidth
  readonly property real buddyPillHeight: buddy.pillHeight
  readonly property var beacons: service ? Cursor.beacons(service.points) : []
  // a picture from the paper rides along with the answer (lib/card.js)
  readonly property var cardImage: service ? CardLib.imageOf(service.note) : null
  readonly property bool cardShown: cardImage !== null && bubbleShown
  readonly property var cardSpot: CardLib.place(width, height, CardLib.cardSize(cardImage),
    CardLib.avoidRects(beacons, draw.shapes, service ? service.cuaTarget : null,
      bubbleShown ? { x: bubbleHost.x, y: bubbleHost.y, w: bubbleHost.width, h: bubbleHost.height } : null))
  // a 3D model from the paper (lib/model3d.js): clickable, so the window
  // takes the pointer on its rectangle only while it shows
  readonly property var cardModel: service ? ModelLib.modelOf(service.note) : null
  readonly property bool modelShown: cardModel !== null && bubbleShown
  readonly property bool modelHovered: modelCard.hovered
  property alias modelItem: modelCard
  readonly property var modelSpot: CardLib.place(width, height, ModelLib.cardSize(),
    CardLib.avoidRects(beacons, draw.shapes, service ? service.cuaTarget : null,
      bubbleShown ? { x: bubbleHost.x, y: bubbleHost.y, w: bubbleHost.width, h: bubbleHost.height } : null)
      .concat(cardShown ? [CardLib.rect(cardSpot.x, cardSpot.y, CardLib.cardSize(cardImage).w, CardLib.cardSize(cardImage).h)] : []))
  // the talk key is held: the layer takes the pointer for a scribble
  readonly property bool scribbleActive: service !== null && Scribble.active(service.status)
  property alias scribbleItem: scribble
  // "what can I ask here" after a quick tap: text only, never over a live turn
  readonly property bool chipsShown: service !== null && ChipsLib.quiet(service.status) && askChips.shown
  property alias askChipsItem: askChips
  readonly property bool shown: scribbleActive || pillShown || bubbleShown || buddyShown || beacons.length > 0 || draw.count > 0 || cardShown || modelShown || chipsShown
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

  // the bubble's own spot: top-center, parked just under the bar — one
  // fixed place for asks/answers instead of chasing the pointer
  Item {
    id: bubbleHost
    visible: root.bubbleShown
    width: bubbleCol.implicitWidth
    height: bubbleCol.implicitHeight
    x: Math.round((root.width - width) / 2)
    y: root.gap + root.barHeight + M.spacing.lg

    HoverHandler { id: bubbleHover }

    Column {
      id: bubbleCol
      spacing: M.spacing.md

      Bubble {
        id: bubble
        service: root.service
        onMoreClicked: root.moreClicked()
        onConfirmChosen: function (pick, promptId) { root.confirmChosen(pick, promptId); }
      }

      // good / wrong on a finished answer; folds into its own receipt
      RateRow {
        service: root.service
        allowed: root.service.confirm === null
        onRate: function (verdict, turn) { root.verdict(verdict, turn); }
      }
    }
  }

  // under everything else, so the pill and the bubble keep their own input
  ScribbleLayer {
    id: scribble
    objectName: "scribbleLayer"
    anchors.fill: parent
    service: root.service
    active: root.scribbleActive
    onScribbled: function (payload) { root.scribbled(payload); }
  }

  // drawings (ring, arrow, highlight) sit under the beacons and the buddy;
  // the buddy and beacons read state.points only
  DrawLayer {
    id: draw
    objectName: "drawLayer"
    anchors.fill: parent
    service: root.service
  }

  // ask chips: bottom centre, where the listening pill was
  AskChips {
    id: askChips
    objectName: "askChips"
    service: root.service
    chips: root.service ? root.service.chips : null
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 96
    visible: root.chipsShown
  }

  // the picture card sits on calm space, never over a mark or the bubble
  Card {
    id: card
    objectName: "imageCard"
    service: root.service
    img: root.cardImage
    visible: root.cardShown
    x: root.cardSpot.x
    y: root.cardSpot.y
  }

  // the 3D card: the one clickable card, kept clear of the picture card
  ModelCard {
    id: modelCard
    objectName: "modelCard"
    service: root.service
    model: root.cardModel
    visible: root.modelShown
    x: root.modelSpot.x
    y: root.modelSpot.y
  }

  // beacons: state.points are in layer coordinates. A plain array model
  // rebuilds every delegate when it grows, replaying the landed beacons;
  // the ListModel only appends the new ones (rebuilds on a new turn).
  ListModel { id: beaconModel }
  property var beaconsSynced: []
  // one path for every change, init included: Component.onCompleted runs it
  // too, a no-op when the initial beacons were already synced
  function syncBeacons() {
    var plan = Cursor.beaconSync(beaconsSynced, beacons);
    if (plan.kind === "none") return;
    if (plan.kind === "reset") beaconModel.clear();
    for (var i = plan.from; i < beacons.length; i++) beaconModel.append({ bx: beacons[i].x, by: beacons[i].y, step: beacons[i].index });
    beaconsSynced = beacons;
  }
  onBeaconsChanged: syncBeacons()
  Component.onCompleted: syncBeacons()

  Repeater {
    objectName: "beaconRepeater"
    model: beaconModel
    delegate: Beacon {
      required property real bx
      required property real by
      required property int step
      service: root.service
      index: step
      x: bx - width / 2
      y: by - height
    }
  }

  Buddy {
    id: buddy
    anchors.fill: parent
    service: root.service
  }

  Binding {
    target: buddy
    property: "view"
    value: root.buddyView
    when: root.buddyView !== null
  }
}
