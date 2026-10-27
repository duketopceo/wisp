// Buddy: the Wisp's on-screen form beside the owner's pointer, drawn from
// the view object lib/buddy.js hands in (Clacky 0.2.0 look from
// clacky/shell/ui/overlay.py, MIT, Raynan Wuyep; see
// THIRD_PARTY_NOTICES.md). A pure renderer: the host computes
// the view once per frame and nothing in here loops or animates on its
// own. Modes: five-bar waveform (listening), arc spinner (transcribing,
// deciding, acting), triangle (speaking) and triangle in the needsYou
// color (awaiting_choice). Flights and follow are positions in the view.
// While the buddy sits on a target a label pill sits beside it (raised
// fill, ink text, ember keyline) and a click plays one 220ms ripple, full
// motion only. The host reads pillWidth and pillHeight back into the
// view() context so the pill can flip at the screen edge. Coordinates are
// the item's own: the host stretches it over the overlay window.
import QtQuick
import QtQuick.Shapes
import "../lib/metrics.js" as M

Item {
  id: root

  property var service: null
  // lib/buddy.js view(): { visible, phase, x, y, rotation, scale, opacity,
  // mode, clicking, label {visible, text, x, y, scale}, spinAngle, bars }
  property var view: ({
    visible: false, phase: "hidden", x: 0, y: 0, rotation: -35, scale: 1,
    opacity: 0, mode: "hidden", clicking: false,
    label: { visible: false, text: "", x: 0, y: 0, scale: 1 },
    spinAngle: 0, bars: [3, 3, 3, 3, 3]
  })
  property string motion: ""

  readonly property var tk: service ? service.tokens : ({})
  readonly property string motionMode: motion !== "" ? motion : (service ? service.motionMode : "off")
  readonly property string mode: view.mode
  readonly property color glyph: mode === "triangleNeedsYou" ? tk.needsYou : tk.ember
  readonly property real pillWidth: labelText.implicitWidth + 2 * M.spacing.lg
  readonly property real pillHeight: labelText.implicitHeight + 2 * M.spacing.sm

  implicitWidth: 160
  implicitHeight: 100

  // the buddy and its glow, centered on view.x, view.y
  Item {
    id: body
    visible: root.view.visible
    opacity: root.view.opacity
    x: root.view.x
    y: root.view.y

    // one ripple at the target, 220ms
    Rectangle {
      visible: root.view.clicking
      x: -width / 2
      y: -height / 2
      width: M.size.cursorHeight
      height: width
      radius: width / 2
      color: Qt.alpha(root.tk.ember, 0.18)
      border.width: M.size.keyline
      border.color: root.tk.ember
      NumberAnimation on scale {
        from: 0.4
        to: 1
        duration: 220
        easing.type: Easing.OutCubic
        running: root.view.clicking && root.motionMode === "full"
      }
    }

    // glow discs, outermost first
    Repeater {
      model: [{ r: 17.6, a: 35 }, { r: 12.8, a: 55 }, { r: 9.2, a: 85 }]
      delegate: Rectangle {
        required property var modelData
        visible: root.mode === "triangle" || root.mode === "triangleNeedsYou"
        x: -width / 2
        y: -height / 2
        width: modelData.r * 2
        height: width
        radius: modelData.r
        color: Qt.alpha(root.tk.emberHalo, modelData.a / 255)
        scale: root.view.scale
      }
    }

    // triangle, side 16, rotated to the flight heading
    Shape {
      visible: root.mode === "triangle" || root.mode === "triangleNeedsYou"
      rotation: root.view.rotation
      scale: root.view.scale
      preferredRendererType: Shape.CurveRenderer
      antialiasing: true
      ShapePath {
        fillColor: root.glyph
        strokeColor: "transparent"
        startX: 0
        startY: -9.24
        PathLine { x: -8; y: 4.62 }
        PathLine { x: 8; y: 4.62 }
        PathLine { x: 0; y: -9.24 }
      }
    }

    // five bars, width 2, gap 2, centered on the pointer offset
    Repeater {
      model: root.mode === "waveform" ? 5 : 0
      delegate: Rectangle {
        required property int index
        x: (index - 2) * 4 - 1
        y: -height / 2
        width: 2
        height: root.view.bars[index]
        radius: 1
        color: root.tk.ember
      }
    }

    // arc spinner, diameter 14, 252 degree sweep
    Shape {
      visible: root.mode === "spinner"
      preferredRendererType: Shape.CurveRenderer
      antialiasing: true
      ShapePath {
        fillColor: "transparent"
        strokeColor: root.tk.ember
        strokeWidth: 2.5
        capStyle: ShapePath.RoundCap
        PathAngleArc {
          centerX: 0
          centerY: 0
          radiusX: 7
          radiusY: 7
          startAngle: root.view.spinAngle - 90
          sweepAngle: 252
        }
      }
    }
  }

  // label pill beside the target
  Rectangle {
    id: pill
    visible: root.view.label.visible && root.view.label.text !== ""
    x: root.view.label.x
    y: root.view.label.y
    width: root.pillWidth
    height: root.pillHeight
    radius: 6
    color: root.tk.raised
    border.width: M.size.keyline
    border.color: root.tk.ember
    scale: root.view.label.scale

    Text {
      id: labelText
      anchors.centerIn: parent
      text: root.view.label.text
      color: root.tk.ink
      font.family: root.service ? root.service.fontFamily : ""
      font.pixelSize: M.font.caption
    }
  }
}
