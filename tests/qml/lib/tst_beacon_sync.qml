import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../harness"

// The REAL OverlayLayer's beacon wiring: the Repeater is fed by a ListModel
// so a grown points list appends one delegate instead of rebuilding them all
// (the pure plan lives in tst_cursor.qml). Also guards init seeding: created
// with points, the model must hold each beacon once.
TestCase {
  id: tc
  name: "beaconSync"
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

  function pt(x, y, step) { return { x: x, y: y, label: "", step: step } }

  // theme tokens from the dark theme fixture, so the components resolve colors
  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function make(points) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    // assigned in JS: a property map would hand over a non-Array list
    svc.points = points
    overlay = createTemporaryObject(overlayC, tc, { service: svc })
    wait(20)
  }

  // overlay first: it must not outlive the service its bindings read
  function cleanup() {
    if (overlay) overlay.destroy()
    if (svc) svc.destroy()
    wait(0)
    overlay = null
    svc = null
  }

  function repeater() {
    var d = overlay.data
    for (var i = 0; i < d.length; i++)
      if (d[i].objectName === "beaconRepeater") return d[i]
    return null
  }

  function test_created_with_points_seeds_once() {
    make([pt(10, 10, 1), pt(20, 20, 2)])
    compare(repeater().count, 2)
  }

  function test_growth_appends_one_delegate() {
    make([pt(10, 10, 1)])
    compare(repeater().count, 1)
    var first = repeater().itemAt(0)
    svc.points = [pt(10, 10, 1), pt(20, 20, 2)]
    wait(20)
    compare(repeater().count, 2)
    verify(repeater().itemAt(0) === first)
  }

  function test_non_extension_rebuilds() {
    make([pt(10, 10, 1)])
    var first = repeater().itemAt(0)
    svc.points = [pt(90, 90, 1)]
    wait(20)
    compare(repeater().count, 1)
    verify(repeater().itemAt(0) !== first)
  }

  function test_emptied_clears() {
    make([pt(10, 10, 1), pt(20, 20, 2)])
    svc.points = []
    wait(20)
    compare(repeater().count, 0)
  }
}
