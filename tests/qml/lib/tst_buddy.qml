import QtQuick
import QtTest
import "../../../shell-plugin/lib/buddy.js" as Buddy

// Buddy model: follow spring, flight, dwell/return tail, status modes,
// entry delay, label edge flip, waveform and spinner. Expected values come
// from the plan's Clacky constants table (offset +35,+25, flight
// 0.35 + d/700 clamped to 0.7 s, dwell 4 s, return 1.4 s), not from the lib.
TestCase {
  name: "buddy"

  readonly property var screen: ({ w: 1920, h: 1080 })

  function aim(x, y, label) {
    return { visible: true, state: "parked", x: x, y: y, label: label === undefined ? "" : label, unsure: false }
  }
  function inp(status, ptr, target, over) {
    var i = { pointer: ptr === undefined ? { x: 100, y: 100 } : ptr, status: status,
      level: 0, target: target === undefined ? null : target, motion: "full" }
    for (var k in over) i[k] = over[k]
    return i
  }
  // step `seconds` of wall time at `hz`; returns { m, frames:[view...] }
  function run(m, i, seconds, hz) {
    var n = Math.round(seconds * hz), frames = []
    for (var k = 0; k < n; k++) {
      m = Buddy.step(m, i, 1 / hz)
      frames.push(Buddy.view(m, { screen: screen, motion: i.motion }))
    }
    return { m: m, frames: frames }
  }
  function near(a, b, tol, msg) { verify(Math.abs(a - b) <= tol, (msg || "") + " " + a + " vs " + b) }

  // follow from rest at (0,0) toward pointer (100,100)
  function resting() { return Buddy.init({ phase: "follow", live: true, placed: true, entryT: 5, x: 0, y: 0 }) }

  function test_follow_converges_and_overshoots() {
    var m = resting(), i = inp("listening"), over = false
    for (var k = 0; k < 30; k++) {
      m = Buddy.step(m, i, 1 / 60)
      if (m.x > 135.5) over = true
    }
    near(m.x, 135, 1); near(m.y, 125, 1)
    verify(over, "underdamped spring overshoots the target")
  }

  function test_follow_is_rate_independent() {
    var a = run(resting(), inp("listening"), 0.5, 60).m
    var b = run(resting(), inp("listening"), 0.5, 120).m
    near(a.x, b.x, 1); near(a.y, b.y, 1)
  }

  function test_reduced_motion_snaps_follow() {
    var m = Buddy.step(resting(), inp("listening", undefined, null, { motion: "reduced" }), 1 / 60)
    compare(m.x, 135); compare(m.y, 125)
  }

  // a buddy parked at the pointer offset, shown, ready to fly
  function atPointer() {
    var m = Buddy.step(Buddy.init(), inp("listening"), 1 / 60)
    return run(m, inp("listening"), 1, 60).m
  }

  function flightSeconds(dist) {
    var m = atPointer()
    var i = inp("speaking", undefined, aim(135 + dist, 125, "t"))
    var t = 0
    m = Buddy.step(m, i, 1 / 1000)
    t += 1 / 1000
    compare(m.phase, "flying")
    while (m.phase === "flying" && t < 2) { m = Buddy.step(m, i, 1 / 1000); t += 1 / 1000 }
    return t
  }

  function test_flight_duration_clamps() {
    near(flightSeconds(100), 0.4929, 0.003)
    near(flightSeconds(1000), 0.7, 0.003)
    near(flightSeconds(0), 0.35, 0.003)
  }

  function test_flight_arcs_up_and_grows() {
    var m = atPointer()
    var tgt = aim(135 + 400, 125, "t")
    var i = inp("speaking", undefined, tgt)
    m = Buddy.step(m, i, 1 / 1000)
    var dur = 0.7   // 0.35 + 400/700 clamps to 0.7
    // advance to half the flight
    m = Buddy.step(m, i, dur / 2 - 1 / 1000)
    near(m.x, 135 + 200, 1)
    near(m.y, 125 - Math.min(0.22 * 400, 90) / 2, 1)
    near(m.scale, 1.25, 0.01)
  }

  function test_holds_while_target_live() {
    var m = atPointer()
    var i = inp("speaking", undefined, aim(800, 500, "Save"))
    var r = run(m, i, 10, 60)
    compare(r.m.phase, "held")
    near(r.m.x, 800, 0.01); near(r.m.y, 500, 0.01)
  }

  function heldAt(x, y) {
    return run(atPointer(), inp("speaking", undefined, aim(x, y, "Save")), 2, 60).m
  }

  function test_release_dwells_four_seconds_then_returns() {
    var m = heldAt(800, 500)
    var i = inp("speaking", undefined, null)
    var r = run(m, i, 3.9, 60)
    compare(r.m.phase, "dwelling")
    r = run(r.m, i, 0.2, 60)
    compare(r.m.phase, "returning")
    r = run(r.m, i, 1.5, 60)
    compare(r.m.phase, "follow")
  }

  function test_new_target_during_dwell_flies_straight_there() {
    var m = run(heldAt(800, 500), inp("speaking"), 1, 60).m
    compare(m.phase, "dwelling")
    m = Buddy.step(m, inp("speaking", undefined, aim(300, 300, "B")), 1 / 60)
    compare(m.phase, "flying")
  }

  function test_turn_ends_on_a_target_tail_then_hides() {
    var m = heldAt(800, 500)
    var i = inp("done", undefined, null)
    var r = run(m, i, 4 + 1.4 - 0.05, 60)
    for (var k = 0; k < r.frames.length; k++) verify(r.frames[k].visible, "frame " + k + " hidden early")
    compare(r.m.phase, "returning")
    r = run(r.m, i, 0.2, 60)
    compare(r.m.phase, "hidden")
    verify(!Buddy.view(r.m, { screen: screen, motion: "full" }).visible)
  }

  function test_new_turn_cancels_the_tail() {
    var m = run(heldAt(800, 500), inp("done"), 1.5, 60).m
    compare(m.phase, "dwelling")
    m = Buddy.step(m, inp("listening"), 1 / 60)
    compare(m.phase, "follow")
    verify(Buddy.view(m, { screen: screen, motion: "full" }).visible)
  }

  function test_second_point_while_speaking_retargets_the_flight() {
    var m = heldAt(800, 500)
    var i = inp("speaking", undefined, aim(300, 200, "Second"))
    m = Buddy.step(m, i, 1 / 60)
    compare(m.phase, "flying")
    near(m.tx, 300, 0.01); near(m.ty, 200, 0.01)
    m = run(m, i, 1, 60).m
    compare(m.phase, "held")
    near(m.x, 300, 0.01); near(m.y, 200, 0.01)
    compare(Buddy.view(m, { screen: screen, motion: "full" }).label.text, "Second")
  }

  function test_new_turn_mid_flight_follows_and_drops_the_label() {
    var m = atPointer()
    var fly = inp("speaking", undefined, aim(900, 600, "Old"))
    m = run(m, fly, 0.2, 60).m
    compare(m.phase, "flying")
    // the turn ends while airborne, then a new turn starts
    m = Buddy.step(m, inp("done", undefined, null), 1 / 60)
    m = Buddy.step(m, inp("listening", { x: 50, y: 60 }), 1 / 60)
    compare(m.phase, "follow")
    var v = Buddy.view(m, { screen: screen, motion: "full" })
    verify(!v.label.visible, "old label is gone")
    var r = run(m, inp("listening", { x: 50, y: 60 }), 2, 60)
    near(r.m.x, 85, 1); near(r.m.y, 85, 1)
  }

  function test_idle_hides_immediately_when_following() {
    var m = Buddy.step(atPointer(), inp("idle"), 1 / 60)
    compare(m.phase, "hidden")
    verify(!Buddy.view(m, { screen: screen, motion: "full" }).visible)
  }


  function test_label_flips_at_right_and_bottom_edges() {
    var inner = run(heldAt(500, 500), inp("speaking", undefined, aim(500, 500, "Save")), 1, 60).m
    var l0 = Buddy.view(inner, { screen: screen, pill: { w: 120, h: 24 }, motion: "full" }).label
    near(l0.x, 510, 0.01)                 // left edge at +10 px
    verify(l0.y > 500, "below the target")
    var l1 = Buddy.view(run(heldAt(1910, 500), inp("speaking", undefined, aim(1910, 500, "Save")), 1, 60).m,
      { screen: screen, pill: { w: 120, h: 24 }, motion: "full" }).label
    verify(l1.x + 120 <= 1910, "right edge flips left of the target")
    verify(l1.x >= 0)
    var l2 = Buddy.view(run(heldAt(500, 1070), inp("speaking", undefined, aim(500, 1070, "Save")), 1, 60).m,
      { screen: screen, pill: { w: 120, h: 24 }, motion: "full" }).label
    verify(l2.y + 24 <= 1070, "bottom edge flips above the target")
  }

  function test_mode_map() {
    function mode(s) {
      var m = Buddy.step(Buddy.init(), inp(s), 1 / 60)
      return Buddy.view(m, { screen: screen, motion: "full" }).mode
    }
    compare(mode("listening"), "waveform")
    compare(mode("transcribing"), "spinner")
    compare(mode("deciding"), "spinner")
    compare(mode("acting"), "spinner")
    compare(mode("speaking"), "triangle")
    compare(mode("awaiting_choice"), "triangleNeedsYou")
    compare(mode("idle"), "hidden")
    compare(mode("bogus"), "hidden")
  }

  function test_entry_delay_hides_the_press_time_screenshot() {
    var m = Buddy.init()
    var r = run(m, inp("listening"), 0.2, 60)
    compare(Buddy.view(r.m, { screen: screen, motion: "full" }).opacity, 0)
    r = run(r.m, inp("listening"), 0.15, 60)
    var o = Buddy.view(r.m, { screen: screen, motion: "full" }).opacity
    verify(o > 0 && o < 1, "fading in at 0.35 s: " + o)
    r = run(r.m, inp("listening"), 0.5, 60)
    compare(Buddy.view(r.m, { screen: screen, motion: "full" }).opacity, 1)
  }

  function test_no_pointer_stays_hidden() {
    var r = run(Buddy.init(), inp("listening", null), 1, 60)
    verify(!Buddy.view(r.m, { screen: screen, motion: "full" }).visible)
    r = run(r.m, inp("listening", { x: 10, y: 10 }), 1, 60)
    verify(Buddy.view(r.m, { screen: screen, motion: "full" }).visible)
  }

  function test_waveform_heights() {
    var low = Buddy.waveHeights(0, 0, "full")
    compare(low.length, 5)
    for (var k = 0; k < 5; k++) verify(low[k] >= 3 && low[k] <= 4.5, "bar " + k + " " + low[k])
    var hi = Buddy.waveHeights(1, 0, "full")
    for (k = 0; k < 5; k++) { verify(hi[k] <= 14.5); verify(hi[2] >= hi[k]) }
    near(Buddy.waveHeights(1, 0, "reduced")[2], 13, 0.0001)   // no wobble
  }

  function test_spinner_revolution() {
    near(Buddy.spinnerAngle(0.2, "full"), 90, 0.001)
    near(Buddy.spinnerAngle(0.8, "full"), 0, 0.001)
    compare(Buddy.spinnerAngle(0.3, "reduced"), 0)
    compare(Buddy.spinnerAngle(0.3, "off"), 0)
  }

  function test_parse_pointer() {
    var p = Buddy.parsePointer('{"x":505,"y":863}')
    compare(p.x, 505)
    compare(p.y, 863)
    p = Buddy.parsePointer('{\n    "x": -12,\n    "y": 40\n}\n')
    compare(p.x, -12)
    compare(p.y, 40)
  }

  function test_parse_pointer_garbage_is_null() {
    compare(Buddy.parsePointer(""), null)
    compare(Buddy.parsePointer("not json"), null)
    compare(Buddy.parsePointer('{"x":5}'), null)
    compare(Buddy.parsePointer('{"x":"a","y":1}'), null)
    compare(Buddy.parsePointer("null"), null)
    compare(Buddy.parsePointer(undefined), null)
  }

  function test_layer_pointer_on_and_off_screen() {
    var a = { x: 0, y: 0, w: 1728, h: 1080 }
    compare(Buddy.layerPointer({ x: 2000, y: 500 }, a), null)
    var b = { x: 1728, y: 0, w: 3440, h: 1440 }
    var p = Buddy.layerPointer({ x: 2000, y: 500 }, b)
    compare(p.x, 272)
    compare(p.y, 500)
    compare(Buddy.layerPointer({ x: 1727, y: 500 }, b), null)
    compare(Buddy.layerPointer({ x: 1728 + 3440, y: 500 }, b), null)
    compare(Buddy.layerPointer(null, b), null)
  }

  // no pointer sample yet (pointer on another output, socket failing):
  // a live target still gets the buddy, placed straight on it
  function test_live_target_without_pointer_places_on_target() {
    var r = run(Buddy.init(), inp("acting", null, aim(400, 300, "Save")), 0.6, 60)
    var v = r.frames[r.frames.length - 1]
    compare(r.m.phase, "held")
    compare(v.visible, true)
    near(v.x, 400, 0.01)
    near(v.y, 300, 0.01)
    compare(v.label.text, "Save")
  }

  // ...and with still no pointer to return to, the tail ends in place
  // rather than flying back to a made-up spot
  function test_release_without_pointer_hides_without_return_flight() {
    var r = run(Buddy.init(), inp("acting", null, aim(400, 300, "Save")), 0.6, 60)
    r = run(r.m, inp("done", null, null), 4.2, 60)
    var flew = r.frames.some(function (v) { return v.phase === "returning" })
    compare(flew, false)
    compare(r.m.phase, "hidden")
  }
}
