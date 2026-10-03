import QtQuick
import QtQuick.Shapes
import "../lib/icons.js" as Icons

// One owned icon from lib/icons.js (generated from assets/icons/src).
// Drawn on the 16px grid and scaled to `size`, so the 1.5px stroke scales
// with it (DESIGN-v2 5.6). Callers pass size: Style.font.icon (or
// Style.bar.iconCanvas in the bar) and a token color.
Item {
  id: root

  property string name: ""
  property color color: "transparent"
  property real size: 16

  readonly property var glyph: Icons.get(name)

  implicitWidth: size
  implicitHeight: size
  width: size
  height: size
  visible: glyph !== null

  Shape {
    width: 16
    height: 16
    scale: root.size / 16
    transformOrigin: Item.TopLeft
    preferredRendererType: Shape.CurveRenderer
    antialiasing: true

    ShapePath {
      fillColor: root.glyph && root.glyph.fill ? root.color : "transparent"
      strokeColor: root.glyph && root.glyph.stroke ? root.color : "transparent"
      strokeWidth: root.glyph && root.glyph.stroke ? root.glyph.width : 0
      capStyle: root.glyph && root.glyph.cap === "round" ? ShapePath.RoundCap
              : root.glyph && root.glyph.cap === "square" ? ShapePath.SquareCap
              : ShapePath.FlatCap
      joinStyle: root.glyph && root.glyph.join === "round" ? ShapePath.RoundJoin
               : ShapePath.MiterJoin
      strokeStyle: root.glyph && root.glyph.dash.length ? ShapePath.DashLine
                 : ShapePath.SolidLine
      // ShapePath dash lengths are in stroke widths; sources give px.
      dashPattern: root.glyph && root.glyph.dash.length
                   ? root.glyph.dash.map(function (v) { return v / root.glyph.width })
                   : [4, 2]
      PathSvg { path: root.glyph ? root.glyph.d : "" }
    }
  }
}
