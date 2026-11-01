import QtQuick
import QtQuick.Controls

// QtTest helper (settings overhaul U1): finds content that is taller than
// its viewport with no way to reach it. audit(viewport) returns a list of
// problem strings, empty when every overflow is scrollable:
//   "flickable-no-bar:<name>"  a Flickable whose content is taller than it
//                              is, with no vertical ScrollBar that can show
//   "clipped:<name>"           a child outside any Flickable that runs past
//                              the bottom of the viewport
// Not a TestCase, so qmltestrunner does not pick it up on its own.
QtObject {
  function isFlickable(item) {
    return typeof item.contentHeight === "number"
      && typeof item.contentY === "number"
      && typeof item.flickableDirection === "number"
  }

  function hasBar(flick) {
    var bar = flick.ScrollBar.vertical
    return bar !== null && bar !== undefined
      && bar.policy !== ScrollBar.AlwaysOff && bar.size < 1
  }

  function label(item) {
    return item.objectName !== "" ? item.objectName : String(item)
  }

  function walk(item, viewport, out) {
    for (var i = 0; i < item.children.length; i++) {
      var c = item.children[i]
      if (isFlickable(c)) {
        if (c.contentHeight > c.height + 0.5 && !hasBar(c))
          out.push("flickable-no-bar:" + label(c))
        // what a Flickable holds is its own business; scrolling reaches it
        continue
      }
      if (c.visible && c.height > 0
          && c.mapToItem(viewport, 0, c.height).y > viewport.height + 0.5)
        out.push("clipped:" + label(c))
      walk(c, viewport, out)
    }
  }

  function audit(viewport) {
    var out = []
    walk(viewport, viewport, out)
    return out
  }
}
