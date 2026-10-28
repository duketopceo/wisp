import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../harness"

// The real DrawLayer's pen: only full motion animates, and a turn that stops
// speaking finishes every mark at once.
TestCase {
  id: tc
  name: "drawPen"
  when: windowShown
  width: 400
  height: 300

  property var svc: null
  property var pen: null

  Component { id: svcC; FixtureService {} }
  Component { id: layerC; DrawLayer { width: 400; height: 300 } }

  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function make(motion, ms) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.status = "speaking"
    svc.drawings = [{ kind: "ring", x: 60, y: 60, r: 20, ms: ms || 1500 },
      { kind: "arrow", x1: 10, y1: 10, x2: 200, y2: 100, ms: 1500 }]
    pen = createTemporaryObject(layerC, tc, { service: svc, motion: motion })
    wait(30)
  }

  function cleanup() {
    if (pen) pen.destroy()
    if (svc) svc.destroy()
    wait(0)
    pen = null
    svc = null
  }

  function repeater() {
    for (var i = 0; i < pen.data.length; i++)
      if (pen.data[i].objectName === "drawRepeater") return pen.data[i]
    return null
  }

  function test_full_motion_draws_with_the_pen() {
    make("full")
    compare(repeater().count, 2)
    compare(pen.animating, 2)
    verify(repeater().itemAt(0).p < 1)
  }

  function test_reduced_motion_has_zero_animation_frames() {
    make("reduced")
    compare(repeater().count, 2)
    compare(pen.animating, 0)
    compare(repeater().itemAt(0).p, 1)
    compare(repeater().itemAt(1).p, 1)
  }

  function test_off_motion_is_static_too() {
    make("off")
    compare(pen.animating, 0)
    compare(repeater().itemAt(0).p, 1)
  }

  function test_stopping_speech_finishes_every_mark_in_one_frame() {
    make("full", 60000)
    verify(repeater().itemAt(0).p < 1)
    svc.status = "done"
    wait(20)
    compare(repeater().itemAt(0).p, 1)
    compare(repeater().itemAt(1).p, 1)
    compare(pen.animating, 0)
  }

  function test_an_unknown_mark_draws_nothing() {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.drawings = [{ kind: "squiggle", x: 5, y: 5 }]
    pen = createTemporaryObject(layerC, tc, { service: svc, motion: "off" })
    wait(20)
    compare(repeater().count, 0)
  }
}
