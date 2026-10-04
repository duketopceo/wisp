import QtQuick
import QtTest
import "../../../shell-plugin/lib/cursor.js" as Cur
import "../../../shell-plugin/lib/companion.js" as Co
import "../../../shell-plugin/lib/motion.js" as Motion

// Ghost cursor, beacon, bubble geometry and companion surface rules.
TestCase {
  name: "cursor"

  function target(over) {
    var t = { x: 640, y: 360, window: "Settings", label: "night light", confidence: 0.9, phase: "aim" }
    for (var k in over) t[k] = over[k]
    return t
  }

  function test_absent_target_renders_nothing() {
    verify(!Cur.ghostView(null, false, true, "click", "not sure").visible)
  }

  function test_phases_map_to_states() {
    compare(Cur.ghostView(target({}), false, false, "click", "x").state, "traveling")
    compare(Cur.ghostView(target({}), false, true, "click", "x").state, "parked")
    compare(Cur.ghostView(target({}), true, false, "click", "x").state, "parked")
    compare(Cur.ghostView(target({ phase: "click" }), false, false, "click", "x").state, "clicking")
    compare(Cur.ghostView(target({ phase: "done" }), false, true, "click", "x").state, "returning")
  }

  function test_label_chip_and_low_confidence() {
    compare(Cur.ghostView(target({ label: "Settings" }), true, true, "click", "not sure").label, "click Settings")
    var u = Cur.ghostView(target({ label: "", confidence: 0.3 }), false, true, "click", "not sure")
    verify(u.unsure)
    compare(u.label, "not sure")
  }

  function test_travel_duration_scales_and_caps() {
    compare(Motion.travelMs(Cur.distance({ x: 0, y: 0 }, { x: 1000, y: 0 }), "full"), 520)
    compare(Motion.travelMs(Cur.distance({ x: 0, y: 0 }, { x: 100, y: 0 }), "full"), 345)
    compare(Motion.travelMs(1000, "reduced"), 140)
    compare(Motion.travelMs(1000, "off"), 0)
  }

  function test_path_is_curved_and_hits_endpoints() {
    var a = { x: 0, y: 500 }, b = { x: 400, y: 500 }
    var s = Cur.pathPoint(a, b, 0), e = Cur.pathPoint(a, b, 1), m = Cur.pathPoint(a, b, 0.5)
    compare(s.x, 0); compare(e.x, 400)
    verify(m.y < 500)
    var same = Cur.pathPoint(a, a, 0.5)
    compare(same.x, 0); compare(same.y, 500)
  }

  function test_breadcrumbs_keep_last_three_and_skip_repeats() {
    var l = []
    for (var i = 0; i < 5; i++) l = Cur.pushCrumb(l, { x: i, y: 0 })
    compare(l.length, 3)
    compare(l[0].x, 2)
    compare(Cur.pushCrumb(l, { x: 4, y: 0 }).length, 3)
    compare(Cur.CRUMB_FADE_MS, 2000)
  }

  function test_beacons_from_points() {
    var b = Cur.beacons([{ x: 1, y: 2, label: "a", step: 2 }, { x: 3, y: 4 }, null, { x: "z", y: 1 },
      { x: 5, y: 6, step: 3 }])
    compare(b.length, 3)
    compare(b[0].index, 2)
    compare(b[1].index, 2)
    compare(b[2].index, 3)
    compare(Cur.beacons(undefined).length, 0)
    compare(Cur.BEACON_HOLD_MS, 8000)
  }

  function test_bubble_flips_and_never_covers_pointer() {
    var size = { w: 300, h: 100 }, screen = { w: 1920, h: 1080 }
    var p = Cur.bubblePlace({ x: 500, y: 300 }, size, screen)
    compare(p.x, 518); compare(p.y, 318); compare(p.side, "right")
    var r = Cur.bubblePlace({ x: 1900, y: 300 }, size, screen)
    verify(r.x + size.w < 1900)
    verify(r.side.indexOf("left") === 0)
    var b = Cur.bubblePlace({ x: 500, y: 1070 }, size, screen)
    verify(b.y + size.h < 1070)
    var corner = Cur.bubblePlace({ x: 1915, y: 1075 }, size, screen)
    var inside = 1915 >= corner.x && 1915 <= corner.x + size.w && 1075 >= corner.y && 1075 <= corner.y + size.h
    verify(!inside)
    // tiny screen: stays on screen
    var t = Cur.bubblePlace({ x: 50, y: 50 }, size, { w: 320, h: 240 })
    verify(t.x >= 0 && t.y >= 0 && t.x + size.w <= 320 && t.y + size.h <= 240)
  }

  function test_dwell_and_answer_limits() {
    compare(Cur.dwellMs("one two three"), 9120)
    compare(Cur.dwellMs(""), 9000)
    compare(Cur.BUBBLE_COLS, 60)
    compare(Cur.BUBBLE_LINES, 12)
  }

  function test_console_opens_only_when_asked_or_choosing() {
    compare(Co.consoleOpen("listening", false, false), false)
    compare(Co.consoleOpen("deciding", false, false), false)
    compare(Co.consoleOpen("acting", false, false), false)
    compare(Co.consoleOpen("awaiting_choice", true, false), true)
    compare(Co.consoleOpen("acting", true, false), true)
    compare(Co.consoleOpen("idle", false, true), true)
    compare(Co.userToggle(true), false)
  }

  function test_corner_and_pill_visibility() {
    compare(Co.cornerVisible(false, false), true)
    compare(Co.cornerVisible(true, false), false)
    compare(Co.cornerVisible(false, true), false)
    compare(Co.pillVisible("awaiting_choice"), true)
    compare(Co.pillVisible("listening"), true)
    compare(Co.pillVisible("idle"), false)
  }

  function test_input_region_is_the_creature_only() {
    var r = Co.inputRegion(40, false, 100)
    compare(r.w, 40); compare(r.h, 40)
    compare(Co.inputRegion(20, false, 0).w, 28)
    compare(Co.inputRegion(40, true, 100).w, 140)
  }
}
