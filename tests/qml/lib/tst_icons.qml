import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/icons.js" as Icons

// Every generated icon parses in Qt's PathSvg (svgo emits compact path
// syntax) and its painted bounds stay on the 16px grid. Checks geometry
// via Shape.boundingRect, which needs no pixel rendering (offscreen
// qmltestrunner grabs come back blank on this platform).
TestCase {
  name: "icons"
  when: windowShown

  Icon { id: probe; size: 48; color: "red" }

  function test_icon_data() {
    return Object.keys(Icons.ICONS).sort().map(function (n) { return { tag: n, name: n } })
  }

  function test_icon(data) {
    probe.name = data.name
    verify(probe.glyph !== null)
    var r = probe.children[0].boundingRect
    verify(r.width >= 4 && r.height >= 4,
           data.name + " parsed to a " + r.width + "x" + r.height + " box")
    verify(r.x >= -1 && r.y >= -1 && r.x + r.width <= 17 && r.y + r.height <= 17,
           data.name + " paints outside the grid: " + r)
  }

  function test_unknown_name_hides() {
    probe.name = "no-such-icon"
    compare(probe.glyph, null)
  }
}
