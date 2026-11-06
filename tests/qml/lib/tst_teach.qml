import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/teach.js" as Teach
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/lib/buddy.js" as Buddy
import "../../../shell-plugin/lib/companion.js" as Co
import "../harness"

// U10: the teaching step primitives through the REAL reducer and the REAL
// OverlayLayer. Every teach_* state fixture draws its primitive; a
// voice-confirm step shows the chip and no ring; an off-target end leaves the
// pointer alone and clears marks and chip at once; reduced motion removes
// the flight and the ring pulse; the ring lands on its point at both output
// scales; chip and counter text clear 4.5:1 on a light and a dark theme.
TestCase {
  id: tc
  name: "teach"
  when: windowShown
  width: 400
  height: 300

  property var svc: null
  property var overlay: null

  Component { id: svcC; FixtureService {} }
  Component { id: overlayC; OverlayLayer { width: 400; height: 300 } }

  function readJson(name) {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false)
    x.send()
    return JSON.parse(x.responseText)
  }

  function theme(name) {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/" + name + "/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function make(fixture, motion, w, h) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = theme("vantablack")
    svc.motionConfig = motion || "full"
    svc.load(readJson(fixture), {})
    overlay = createTemporaryObject(overlayC, tc, { service: svc, width: w || 400, height: h || 300 })
    wait(20)
  }

  // the TestCase item starts hidden; effective visibility of the chip needs
  // its ancestors shown
  function initTestCase() { tc.visible = true }

  function cleanup() {
    if (overlay) overlay.destroy()
    if (svc) svc.destroy()
    wait(0)
    overlay = null
    svc = null
  }

  function find(name) {
    function walk(item) {
      var d = item.data
      if (!d) return null
      for (var i = 0; i < d.length; i++) {
        if (d[i].objectName === name) return d[i]
        var r = walk(d[i])
        if (r) return r
      }
      return null
    }
    return walk(overlay)
  }

  function marks() { return find("drawRepeater") }

  // ---- fixtures ----

  function test_waiting_draws_a_ring_and_a_counter_but_no_chip() {
    make("teach_waiting")
    compare(marks().count, 1)
    compare(marks().itemAt(0).kind, "ring")
    compare(overlay.teachView.primitive, "ring")
    compare(overlay.teachChipItem.counterText, "2 of 5")
    compare(overlay.teachChipItem.chipText, "")
    verify(overlay.shown)
  }

  function test_voice_confirm_shows_the_chip_and_no_ring() {
    make("teach_voice_confirm")
    compare(marks().count, 0)
    compare(overlay.teachView.primitive, "none")
    compare(overlay.teachChipItem.chipText, "say continue")
    compare(overlay.teachChipItem.counterText, "3 of 5")
    var chip = find("teachChip")
    verify(chip !== null)
    verify(chip.visible)
  }

  function test_off_target_draws_nothing() {
    make("teach_off_target")
    compare(marks().count, 0)
    verify(!overlay.teachChipItem.shown)
    verify(!overlay.teachChipItem.visible)
  }

  function test_done_draws_nothing() {
    make("teach_done")
    compare(marks().count, 0)
    verify(!overlay.teachChipItem.shown)
  }

  function test_every_kind_has_its_primitive() {
    var want = { "click": "ring", "hover": "dring", "area": "region",
      "handle": "handle", "motion": "curve" }
    for (var kind in want) {
      var raw = readJson("teach_waiting")
      raw.teach.kind = kind
      raw.teach.wait = kind === "click" ? "click" : (kind === "hover" ? "rest" : "settle")
      svc = createTemporaryObject(svcC, tc)
      svc.tokens = theme("vantablack")
      svc.load(raw, {})
      overlay = createTemporaryObject(overlayC, tc, { service: svc })
      wait(20)
      compare(marks().count, 1, kind)
      compare(marks().itemAt(0).kind, want[kind], kind)
      cleanup()
    }
  }

  function test_unknown_kind_is_voice_confirm() {
    var raw = readJson("teach_waiting")
    raw.teach.kind = "levitate"
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = theme("vantablack")
    svc.load(raw, {})
    overlay = createTemporaryObject(overlayC, tc, { service: svc })
    wait(20)
    compare(overlay.teachView.kind, "voice-confirm")
    compare(marks().count, 0)
    compare(overlay.teachChipItem.chipText, "say continue")
  }

  function test_motion_without_an_end_point_still_sweeps() {
    var m = Teach.marks(Teach.normalize({ kind: "motion", radius: 20, index: 1, total: 2, wait: "settle" }), 100, 100)
    compare(m[0].kind, "curve")
    compare(m[0].x2, 100 + Teach.MOTION_SWEEP * 20)
    var to = Teach.marks(Teach.normalize({ kind: "motion", index: 1, total: 2, wait: "settle", to: { x: 5, y: 9 } }), 100, 100)
    compare(to[0].x2, 5)
    compare(to[0].y2, 9)
  }

  // ---- ending ----

  function test_off_target_clears_marks_and_chip_within_a_frame_and_leaves_the_pointer() {
    make("teach_waiting")
    var raw = readJson("teach_waiting")
    raw.teach.kind = "area"
    raw.teach.wait = "settle"
    svc.load(raw, {})
    wait(20)
    compare(marks().count, 1)
    verify(overlay.teachChipItem.shown)
    var before = JSON.stringify(Co.buddyTarget({ points: svc.points, cuaTarget: null, guide: null, status: svc.status }, { x: 0, y: 0 }, "", ""))
    svc.load(readJson("teach_off_target"), {})
    wait(20)   // one frame at 60 Hz is 16 ms
    compare(marks().count, 0)
    verify(!overlay.teachChipItem.shown)
    // the daemon stops pointing: no target to fly to, nothing moves the pointer
    compare(Co.buddyTarget({ points: svc.points, cuaTarget: null, guide: null, status: svc.status }, { x: 0, y: 0 }, "", ""), null)
    verify(before !== "null")
  }

  // ---- motion ----

  function test_ring_pulses_only_in_full_motion() {
    var modes = { "full": true, "reduced": false, "off": false }
    for (var mode in modes) {
      make("teach_waiting", mode)
      compare(marks().itemAt(0).pulsing, modes[mode], mode)
      cleanup()
    }
  }

  function test_ring_stops_pulsing_when_the_step_ends() {
    make("teach_waiting", "full")
    verify(marks().itemAt(0).pulsing)
    var done = readJson("teach_waiting")
    done.status = "done"
    svc.load(done, {})
    wait(20)
    // the ring (kept by its own list) no longer pulses once speech is over
    for (var i = 0; i < marks().count; i++) verify(!marks().itemAt(i).pulsing)
  }

  function test_flight_is_a_snap_outside_full_motion() {
    var tgt = { x: 300, y: 200, label: "", unsure: false }
    var reduced = { x: 10, y: 10, vx: 3, vy: 3 }
    Buddy.startFlight(reduced, tgt, false)
    compare(reduced.phase, "held")
    compare(reduced.x, 300)
    compare(reduced.y, 200)
    var full = { x: 10, y: 10 }
    Buddy.startFlight(full, tgt, true)
    compare(full.phase, "flying")
  }

  function test_reduced_motion_pulse_is_off_in_the_lib() {
    verify(Teach.pulses("full"))
    verify(!Teach.pulses("reduced"))
    verify(!Teach.pulses("off"))
  }

  // ---- scale ----

  function test_ring_lands_on_its_point_at_scale_1_and_2() {
    // a scale-2 output hands the layer half the pixels in logical units, and
    // the daemon's point is in that same logical space: the ring must sit on
    // the point whatever the layer's logical size is
    var sizes = [[400, 300], [200, 150]]
    var spots = [[100, 80], [50, 40]]
    for (var i = 0; i < sizes.length; i++) {
      var raw = readJson("teach_waiting")
      raw.points = [{ x: spots[i][0], y: spots[i][1], label: "t", step: 2 }]
      svc = createTemporaryObject(svcC, tc)
      svc.tokens = theme("vantablack")
      svc.load(raw, {})
      overlay = createTemporaryObject(overlayC, tc, { service: svc, width: sizes[i][0], height: sizes[i][1] })
      wait(20)
      var ring = marks().itemAt(0)
      var c = ring.mapToItem(overlay, ring.width / 2, ring.height / 2)
      verify(Math.abs(c.x - spots[i][0]) < 3, "x at " + sizes[i])
      verify(Math.abs(c.y - spots[i][1]) < 3, "y at " + sizes[i])
      cleanup()
    }
  }

  // ---- click-through, contrast ----

  function test_the_chip_takes_no_input() {
    make("teach_voice_confirm")
    var chip = overlay.teachChipItem
    verify(!chip.focus)
    verify(!chip.activeFocusOnTab)
    // no pointer handler exists in the component (test_components checks the
    // source); the host masks only the pill and the bubble
  }

  function test_chip_and_counter_text_clear_4_5_to_1_on_every_theme() {
    var names = ["vantablack", "tokyo-night", "red-accent", "partial", "white", "catppuccin-latte", "flexoki-light"]
    for (var i = 0; i < names.length; i++) {
      var tk = theme(names[i])
      var ratio = Tokens.contrast(tk.ink, tk.raised)
      verify(ratio >= 4.5, names[i] + " ink on raised " + ratio)
    }
  }
}
