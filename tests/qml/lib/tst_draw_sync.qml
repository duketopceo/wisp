import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/companion.js" as Co
import "../harness"

// The REAL OverlayLayer's draw wiring: the DrawLayer repeater is fed by a
// ListModel so a grown drawings list appends one delegate instead of
// rebuilding them all (the pure plan lives in tst_cursor.qml), a cleared list
// removes every shape, and drawings never touch beacons or the buddy target.
TestCase {
  id: tc
  name: "drawSync"
  when: windowShown
  width: 400
  height: 300

  property var svc: null
  property var overlay: null

  Component {
    id: svcC
    FixtureService {}
  }
  Component {
    id: overlayC
    OverlayLayer { width: 400; height: 300 }
  }

  function ring(x) { return { kind: "ring", x: x, y: 40, r: 12 } }
  function arrow() { return { kind: "arrow", x1: 10, y1: 10, x2: 90, y2: 60 } }
  function hl() { return { kind: "hl", x: 20, y: 20, w: 50, h: 30 } }

  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function make(drawings, points) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    // assigned in JS: a property map would hand over a non-Array list
    svc.drawings = drawings
    svc.points = points || []
    overlay = createTemporaryObject(overlayC, tc, { service: svc })
    wait(20)
  }

  function cleanup() {
    if (overlay) overlay.destroy()
    if (svc) svc.destroy()
    wait(0)
    overlay = null
    svc = null
  }

  function repeater(name) {
    function find(item) {
      var d = item.data
      if (!d) return null
      for (var i = 0; i < d.length; i++) {
        if (d[i].objectName === name) return d[i]
        var r = find(d[i])
        if (r) return r
      }
      return null
    }
    return find(overlay)
  }

  function test_created_with_drawings_seeds_once() {
    make([ring(10), arrow(), hl()])
    compare(repeater("drawRepeater").count, 3)
    verify(overlay.shown)
  }

  function test_growth_appends_one_delegate_and_keeps_earlier() {
    make([ring(10)])
    var first = repeater("drawRepeater").itemAt(0)
    svc.drawings = [ring(10), arrow()]
    wait(20)
    compare(repeater("drawRepeater").count, 2)
    verify(repeater("drawRepeater").itemAt(0) === first)
  }

  function test_emptied_clears_everything() {
    make([ring(10), arrow()])
    svc.drawings = []
    wait(20)
    compare(repeater("drawRepeater").count, 0)
    verify(!overlay.shown)
  }

  function test_drawings_do_not_touch_beacons_or_buddy_target() {
    var pts = [{ x: 30, y: 30, label: "a", step: 1 }]
    make([], pts)
    var before = JSON.stringify([overlay.beacons, Co.buddyTarget({ points: svc.points, cuaTarget: null, guide: null }, { x: 0, y: 0 }, "", "")])
    svc.drawings = [ring(10), arrow(), hl()]
    wait(20)
    var after = JSON.stringify([overlay.beacons, Co.buddyTarget({ points: svc.points, cuaTarget: null, guide: null }, { x: 0, y: 0 }, "", "")])
    compare(after, before)
    compare(repeater("beaconRepeater").count, 1)
  }
}
