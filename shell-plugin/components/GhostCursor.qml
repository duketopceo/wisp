// Ghost cursor: shows where a CUA click will land while the real pointer
// stays put. Input is service.cuaTarget (the cua.target stream event, see
// docs/IPC_CONTRACT.md) and renders nothing when it is absent. States:
// traveling (curved hop, distance-scaled), clicking (one 220ms ripple at
// the tip), parked (guide or arrived, with its label chip), returning
// (dimmed). The creature rides on the silhouette. Reduced motion turns the
// hop into a 140ms cross-fade, off is instant. The host sets `placed` so
// the tip sits at the target in its own coordinates; unplaced (the
// snapshot harness) the tip is at the item origin.
import QtQuick
import "../lib/metrics.js" as M
import "../lib/motion.js" as Motion
import "../lib/cursor.js" as Cursor

Item {
  id: root

  property var service: null
  // "" derives from service.cuaTarget; fixtures pin a state and label
  property string forceState: ""
  property string forceLabel: ""
  property bool placed: false
  property string motion: ""
  // guide mode parks the ghost on arrival and keeps it still
  property bool guideMode: service && service.guide !== null && service.guide !== undefined

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")
  readonly property var target: service ? service.cuaTarget : null

  property bool arrived: true
  property real progress: 1
  property var fromPt: null
  property var lastPt: null
  property var crumbs: []

  readonly property var view: Cursor.ghostView(target, guideMode, arrived,
    service.ui("ui.target.click"), service.ui("ui.target.unsure"))
  readonly property string cstate: forceState !== "" ? forceState : view.state
  readonly property string tagText: forceLabel !== "" ? forceLabel : view.label
  readonly property bool shown: forceState !== "" || view.visible
  readonly property var tip: (fromPt && view.visible)
    ? Cursor.pathPoint(fromPt, { x: view.x, y: view.y }, progress)
    : { x: view.x, y: view.y }

  visible: shown
  implicitWidth: Math.max(M.size.cursorHeight, tag.visible ? tag.width : 0) + M.spacing.huge
  implicitHeight: M.size.cursorHeight + (tag.visible ? tag.height + M.spacing.md : 0)
  opacity: cstate === "returning" ? 0.55 : 1

  Behavior on opacity {
    enabled: root.motionMode !== "off"
    NumberAnimation { duration: Motion.duration.quick; easing.type: Easing.OutCubic }
  }

  onTargetChanged: {
    if (!target) { fromPt = null; lastPt = null; arrived = true; progress = 1; crumbs = []; return }
    if (target.phase !== "aim") return
    var to = { x: target.x, y: target.y }
    if (lastPt && motionMode === "full") {
      fromPt = lastPt
      crumbs = Cursor.pushCrumb(crumbs, lastPt)
      arrived = false
      progress = 0
      hop.duration = Motion.travelMs(Cursor.distance(lastPt, to), motionMode)
      hop.restart()
    } else {
      fromPt = null
      arrived = true
      progress = 1
      if (lastPt && motionMode === "reduced") fade.restart()
    }
    lastPt = to
  }

  NumberAnimation {
    id: hop
    target: root
    property: "progress"
    from: 0
    to: 1
    easing.type: Easing.OutCubic
    onFinished: root.arrived = true
  }
  // reduced motion: the ghost fades in at the target instead of moving
  NumberAnimation {
    id: fade
    target: body
    property: "opacity"
    from: 0
    to: 1
    duration: Motion.duration.quick
  }

  // breadcrumbs: the last three stops, fading over two seconds
  Repeater {
    model: root.placed ? root.crumbs : []
    delegate: Rectangle {
      required property var modelData
      x: modelData.x - width / 2
      y: modelData.y - height / 2
      width: M.spacing.lg
      height: width
      radius: width / 2
      color: "transparent"
      border.width: M.size.keyline
      border.color: root.tk.ember
      opacity: 0
      NumberAnimation on opacity {
        from: 0.5
        to: 0
        duration: 2000
        running: root.motionMode !== "off"
      }
    }
  }

  Item {
    id: body
    x: root.placed ? root.tip.x : 0
    y: root.placed ? root.tip.y : 0

    // one ripple at the tip, 220ms
    Rectangle {
      id: ripple
      visible: root.cstate === "clicking"
      x: 1
      y: 1
      width: M.size.cursorHeight
      height: width
      radius: width / 2
      color: Qt.alpha(root.tk.ember, 0.18)
      border.width: M.size.keyline
      border.color: root.tk.ember
      transformOrigin: Item.TopLeft
      NumberAnimation on scale {
        from: 0.4
        to: 1
        duration: 220
        easing.type: Easing.OutCubic
        running: root.cstate === "clicking" && root.motionMode === "full"
      }
    }

    Icon {
      id: arrow
      name: "ghost-cursor"
      size: M.size.cursorHeight
      color: root.cstate === "traveling" ? root.tk.emberCore : root.tk.ember
    }

    // the Wisp rides on the silhouette
    Creature {
      x: M.size.cursorHeight * 0.55
      y: M.size.cursorHeight * 0.55
      service: root.service
      size: M.size.creaturePill
      forceState: root.cstate === "returning" ? "idle" : "acting"
      motion: root.motionMode
    }

    Rectangle {
      id: tag
      visible: root.cstate === "parked" && root.tagText !== ""
      x: M.spacing.lg
      y: M.size.cursorHeight + M.spacing.sm
      width: txt.implicitWidth + 2 * M.spacing.lg
      height: txt.implicitHeight + 2 * M.spacing.sm
      radius: M.radius.chip
      color: root.tk.canvas
      border.width: M.size.keyline
      border.color: root.view.unsure ? root.tk.needsYou : root.tk.keyline

      Text {
        id: txt
        anchors.centerIn: parent
        text: root.tagText
        color: root.tk.ink
        font.family: root.service.fontFamily
        font.pixelSize: M.font.caption
      }
    }
  }
}
