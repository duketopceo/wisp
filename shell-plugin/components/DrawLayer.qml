// DrawLayer: the shapes Wisp draws while it speaks: a ring around a spot, an
// arrow between two spots, a highlight box. A pure renderer of state.drawings
// (layer coordinates, like the beacons): no timers, no sockets, no clamping;
// the overlay window clips what falls outside. Shapes live exactly as long as
// the state list does, so they vanish at once when speech ends. The model
// follows the list by prefix (Cursor.drawSync), so a shape that is already
// shown never replays its draw-on when the list grows. Look after Clacky's
// overlay (ui/overlay.py, MIT): ~3 px ember strokes, an open arrowhead,
// highlight fill at low alpha; rebuilt in QML for the Quickshell layer.
// motionMode: full draws the stroke on over ~300 ms, reduced fades it in,
// off is static.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/cursor.js" as Cursor

Item {
  id: root

  property var service: null
  // "" follows the service; fixtures pin a mode
  property string motion: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")
  readonly property var shapes: service ? Cursor.drawings(service.drawings) : []
  readonly property int count: shapeModel.count

  // a plain array model would rebuild every delegate when it grows; the
  // ListModel only appends the new ones (and rebuilds on a new turn)
  ListModel { id: shapeModel }
  property var synced: []
  function syncShapes() {
    var plan = Cursor.drawSync(synced, shapes);
    if (plan.kind === "none") return;
    if (plan.kind === "reset") shapeModel.clear();
    for (var i = plan.from; i < shapes.length; i++) {
      var d = shapes[i];
      shapeModel.append({ kind: d.kind, cx: d.x, cy: d.y, r: d.r, w: d.w, h: d.h,
        ax1: d.x1, ay1: d.y1, ax2: d.x2, ay2: d.y2 });
    }
    synced = shapes;
  }
  onShapesChanged: syncShapes()
  Component.onCompleted: syncShapes()

  Repeater {
    objectName: "drawRepeater"
    model: shapeModel
    delegate: Item {
      id: sh
      required property string kind
      required property real cx
      required property real cy
      required property real r
      required property real w
      required property real h
      required property real ax1
      required property real ay1
      required property real ax2
      required property real ay2

      // 0 -> 1 draw-on progress; motion off starts (and stays) done
      property real p: root.motionMode === "off" ? 1 : 0
      NumberAnimation on p {
        running: root.motionMode !== "off"
        from: 0
        to: 1
        duration: Cursor.DRAW_ON_MS
        easing.type: Easing.OutCubic
      }
      readonly property bool full: root.motionMode === "full"

      // arrow geometry: the shaft grows from the start to the tip
      readonly property real dx: ax2 - ax1
      readonly property real dy: ay2 - ay1
      readonly property real len: Math.sqrt(dx * dx + dy * dy)
      readonly property real ang: Math.atan2(dy, dx) * 180 / Math.PI
      readonly property real tipX: ax1 + dx * (full ? p : 1)
      readonly property real tipY: ay1 + dy * (full ? p : 1)

      Rectangle {
        visible: sh.kind === "ring"
        x: sh.cx - sh.r
        y: sh.cy - sh.r
        width: sh.r * 2
        height: sh.r * 2
        radius: sh.r
        color: "transparent"
        border.width: Cursor.DRAW_STROKE
        border.color: root.tk.ember
        opacity: sh.p
        scale: sh.full ? 0.7 + 0.3 * sh.p : 1
      }

      Rectangle {
        visible: sh.kind === "hl"
        x: sh.cx
        y: sh.cy
        width: sh.w
        height: sh.h
        color: Qt.alpha(root.tk.ember, Cursor.DRAW_HL_ALPHA)
        border.width: Cursor.DRAW_HL_STROKE
        border.color: root.tk.ember
        opacity: sh.p
      }

      Item {
        visible: sh.kind === "arrow"
        // shaft
        Rectangle {
          x: sh.ax1
          y: sh.ay1 - height / 2
          width: Math.hypot(sh.tipX - sh.ax1, sh.tipY - sh.ay1)
          height: Cursor.DRAW_STROKE
          radius: height / 2
          color: root.tk.ember
          transformOrigin: Item.Left
          rotation: sh.ang
          opacity: sh.full ? 1 : sh.p
        }
        // open head: two strokes back from the tip at +/-30 degrees
        Repeater {
          model: [-1, 1]
          delegate: Rectangle {
            id: head
            required property int modelData
            x: sh.tipX
            y: sh.tipY - height / 2
            width: Cursor.DRAW_HEAD
            height: Cursor.DRAW_STROKE
            radius: height / 2
            color: root.tk.ember
            transformOrigin: Item.Left
            rotation: sh.ang + 180 + head.modelData * Cursor.DRAW_HEAD_DEG
            opacity: sh.full ? (sh.p > 0.9 ? 1 : 0) : sh.p
          }
        }
      }
    }
  }
}
