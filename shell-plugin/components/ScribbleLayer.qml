// ScribbleLayer: hold the talk key, drag on the screen to circle the thing,
// and say "what is this". While `active` (the service is listening) it takes
// the pointer, draws each drag as a loud pen stroke, and hands the finished
// strokes up (`scribbled`) for the daemon to composite into the screenshot
// the model sees. The moment `active` goes false the strokes are gone and
// the layer takes no input, so no persistent surface sits over user content.
// A drag shorter than a click is ignored, so a stray press draws nothing.
// The host window masks input to this item only while `active`.
pragma ComponentBehavior: Bound
import QtQuick
import "../lib/scribble.js" as S

Item {
  id: root

  property var service: null
  property bool active: false
  // finished strokes in layer pixels, [[{x, y}, ...], ...]; fixtures set it
  property var strokes: []
  // the drag in progress
  property var live: []
  // the daemon may hold strokes from this layer; a clear is owed
  property bool sent: false

  readonly property var tk: service ? service.tokens : ({})
  readonly property color inkColor: tk.ember !== undefined ? tk.ember : "transparent"
  readonly property color edgeColor: tk.ink !== undefined ? tk.ink : "transparent"

  // strokes (finished and in progress) as the pen sees them
  readonly property var all: live.length > 1 ? strokes.concat([live]) : strokes

  signal scribbled(var payload)

  function report() {
    var p = S.payload(strokes, width, height)
    if (p.strokes.length === 0 && !sent) return;
    sent = p.strokes.length > 0;
    root.scribbled(p);
  }

  // a fixture builds the layer with strokes already set: only a change
  // after creation is a new listening turn
  property bool ready: false
  Component.onCompleted: ready = true

  onActiveChanged: {
    if (!ready) return;
    if (active) {
      // a fresh listening turn starts clean; clear what an earlier turn sent
      strokes = [];
      live = [];
      if (sent) report();
    } else {
      // gone this frame; the daemon already has what it will use
      strokes = [];
      live = [];
    }
  }
  onAllChanged: canvas.requestPaint()
  onInkColorChanged: canvas.requestPaint()

  Canvas {
    id: canvas
    anchors.fill: parent
    visible: root.active
    renderTarget: Canvas.Image
    renderStrategy: Canvas.Immediate

    onPaint: {
      var c = getContext("2d");
      c.reset();
      c.lineCap = "round";
      c.lineJoin = "round";
      var all = root.all;
      for (var pass = 0; pass < 2; pass++) {
        // the edge first, the stroke on it: reads on light and dark screens
        c.strokeStyle = pass === 0 ? root.edgeColor : root.inkColor;
        c.lineWidth = pass === 0 ? 8 : 4;
        for (var i = 0; i < all.length; i++) {
          var s = all[i];
          if (s.length === 0) continue;
          c.beginPath();
          c.moveTo(s[0].x, s[0].y);
          for (var j = 1; j < s.length; j++) c.lineTo(s[j].x, s[j].y);
          if (s.length === 1) c.lineTo(s[0].x + 0.1, s[0].y);
          c.stroke();
        }
      }
    }
  }

  MouseArea {
    id: pad
    objectName: "scribblePad"
    anchors.fill: parent
    enabled: root.active
    acceptedButtons: Qt.LeftButton
    cursorShape: Qt.CrossCursor
    onPressed: function (m) { root.live = S.begin(m.x, m.y); }
    onPositionChanged: function (m) {
      if (pressed) root.live = S.extend(root.live, m.x, m.y);
    }
    onReleased: {
      var next = S.commit(root.strokes, root.live);
      root.live = [];
      if (next === root.strokes) return;
      root.strokes = next;
      root.report();
    }
    onCanceled: root.live = []
  }
}
