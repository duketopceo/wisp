// DrawLayer: the marks Wisp draws while it speaks: a ring around a spot, an
// arrow between two spots, a dashed highlight frame. A renderer of
// state.drawings (layer coordinates, like the beacons): no sockets, no
// clamping; the overlay window clips what falls outside. Marks live exactly
// as long as the state list does, so they vanish at once when speech ends.
// The model follows the list by prefix (Cursor.drawSync), so a mark that is
// already shown never replays its pen when the list grows.
//
// Marks look drawn by a person (lib/ink.js): a wobbly tapered pen stroke in
// the ember ink with a soft glow that flips light or dark with the screen
// under the mark (`tone`, sampled from the press-time screenshot), a dashed
// tinted frame for a region. The pen's pace comes from the spoken time of the
// mark's sentence (`ms`); when speech stops early every mark is finished at
// once. Only full motion animates: reduced and off draw the finished mark
// with no animation frames. An unknown mark kind has no strokes and draws
// nothing.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/cursor.js" as Cursor
import "../lib/ink.js" as Ink

Item {
  id: root

  property var service: null
  // "" follows the service; fixtures pin a mode
  property string motion: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")
  readonly property var shapes: service ? Cursor.drawings(service.drawings) : []
  readonly property int count: shapeModel.count
  // speech is over (or stopped): every mark completes this frame
  readonly property bool finishing: service !== null && service.status !== "speaking"
  // marks still being drawn; zero in reduced and off motion
  property int animating: 0

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
        ax1: d.x1, ay1: d.y1, ax2: d.x2, ay2: d.y2, ms: d.ms, tone: d.tone });
    }
    synced = shapes;
  }
  onShapesChanged: syncShapes()
  Component.onCompleted: syncShapes()

  Repeater {
    objectName: "drawRepeater"
    model: shapeModel
    delegate: Canvas {
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
      required property real ms
      required property string tone

      readonly property var ink: Ink.strokesFor({ kind: kind, x: cx, y: cy, r: r, w: w, h: h,
        x1: ax1, y1: ay1, x2: ax2, y2: ay2 })
      readonly property var box: Ink.bounds(ink, Cursor.DRAW_STROKE * 4)
      readonly property bool pen: Ink.animates(root.motionMode) && !root.finishing
      readonly property bool drawing: penAnim.running
      // 0 -> 1 pen progress; a mark that is not animated starts (and stays) done
      property real p: Ink.animates(root.motionMode) ? 0 : 1
      readonly property color inkColor: root.tk.ember
      readonly property color glowColor: tone === "light"
        ? Qt.alpha(Qt.darker(root.tk.ember, 2.4), 0.30)
        : (tone === "dark" ? Qt.alpha(Qt.lighter(root.tk.ember, 1.7), 0.34)
                           : Qt.alpha(root.tk.emberHalo, 0.30))

      x: box.x
      y: box.y
      width: Math.max(1, box.w)
      height: Math.max(1, box.h)
      visible: ink.strokes.length > 0
      antialiasing: true
      renderTarget: Canvas.Image
      renderStrategy: Canvas.Immediate

      NumberAnimation {
        id: penAnim
        target: sh
        property: "p"
        from: 0
        to: 1
        duration: Ink.revealMs(sh.ms)
        easing.type: Easing.OutCubic
        running: sh.pen
      }
      onPenChanged: if (!pen && p < 1) { penAnim.stop(); p = 1 }
      onDrawingChanged: root.animating += drawing ? 1 : -1
      onPChanged: requestPaint()
      onInkColorChanged: requestPaint()
      onGlowColorChanged: requestPaint()

      onPaint: {
        var ctx = getContext("2d");
        ctx.reset();
        ctx.translate(-box.x, -box.y);
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        if (ink.fill) {
          ctx.globalAlpha = p;
          ctx.fillStyle = Qt.alpha(root.tk.ember, Cursor.DRAW_HL_ALPHA);
          ctx.fillRect(ink.fill.x, ink.fill.y, ink.fill.w, ink.fill.h);
          ctx.globalAlpha = 1;
        }
        // glow first, then the pen on top
        for (var pass = 0; pass < 2; pass++) {
          for (var i = 0; i < ink.strokes.length; i++) {
            var poly = Ink.partial(ink.strokes[i], ink.fill ? 1 : p);
            ctx.strokeStyle = pass === 0 ? glowColor : inkColor;
            for (var j = 1; j < poly.length; j++) {
              ctx.lineWidth = ((poly[j - 1].w + poly[j].w) / 2) * (pass === 0 ? 2.6 : 1);
              ctx.beginPath();
              ctx.moveTo(poly[j - 1].x, poly[j - 1].y);
              ctx.lineTo(poly[j].x, poly[j].y);
              ctx.stroke();
            }
          }
        }
      }
    }
  }
}
