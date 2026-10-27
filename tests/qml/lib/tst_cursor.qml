import QtQuick
import QtTest
import "../../../shell-plugin/lib/cursor.js" as Cur
import "../../../shell-plugin/lib/companion.js" as Co

// Cursor target, beacon, bubble geometry and companion surface rules.
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

  function test_beacon_sync_appends_an_extension() {
    var a = { x: 1, y: 2, label: "a", index: 1 }
    var b = { x: 3, y: 4, label: "b", index: 2 }
    var plan = Cur.beaconSync([a], [a, b])
    compare(plan.kind, "append")
    compare(plan.from, 1)
    compare(Cur.beaconSync([], [a]).kind, "append")
    compare(Cur.beaconSync([], [a]).from, 0)
  }

  function test_beacon_sync_resets_when_not_an_extension() {
    var a = { x: 1, y: 2, label: "a", index: 1 }
    var c = { x: 9, y: 9, label: "c", index: 1 }
    compare(Cur.beaconSync([a], [c]).kind, "reset")
    compare(Cur.beaconSync([a], [c, a]).kind, "reset")
    compare(Cur.beaconSync([a, c], [a]).kind, "reset")
  }

  function test_beacon_sync_clears_when_emptied_and_idles_when_same() {
    var a = { x: 1, y: 2, label: "a", index: 1 }
    compare(Cur.beaconSync([a], []).kind, "reset")
    compare(Cur.beaconSync([], []).kind, "none")
    compare(Cur.beaconSync([a], [{ x: 1, y: 2, label: "a", index: 1 }]).kind, "none")
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

  function test_dwell_and_answer_limits() {
    compare(Cur.dwellMs("one two three"), 9120)
    compare(Cur.dwellMs(""), 9000)
    compare(Cur.BUBBLE_COLS, 60)
    compare(Cur.BUBBLE_LINES, 12)
  }

  function test_pill_visibility() {
    compare(Co.pillVisible("awaiting_choice"), true)
    compare(Co.pillVisible("listening"), true)
    compare(Co.pillVisible("transcribing"), true)
    compare(Co.pillVisible("acting"), false)
    compare(Co.pillVisible("idle"), false)
  }

  // buddy target precedence: cua.target (global, shifted by the screen
  // origin) over a guide step (already layer coords) over the newest point
  // while speaking
  function test_buddy_target_shifts_cua_by_origin() {
    var t = Co.buddyTarget({ cuaTarget: { x: 2000, y: 500, label: "Save", confidence: 1, phase: "aim" },
      guide: { x: 10, y: 10, label: "g" }, status: "acting", points: [] },
      { x: 1728, y: 0 }, "click", "unsure")
    compare(t.x, 272)
    compare(t.y, 500)
    compare(t.visible, true)
  }

  function test_buddy_target_guide_is_not_shifted() {
    var t = Co.buddyTarget({ cuaTarget: null, guide: { x: 40, y: 60, label: "next" },
      status: "awaiting_choice", points: [] }, { x: 1728, y: 0 }, "click", "unsure")
    compare(t.x, 40)
    compare(t.y, 60)
  }

  function test_buddy_target_newest_point_only_while_speaking() {
    var pts = [{ x: 1, y: 2, label: "a", step: 1 }, { x: 30, y: 40, label: "b", step: 2 }]
    var t = Co.buddyTarget({ cuaTarget: null, guide: null, status: "speaking", points: pts },
      { x: 0, y: 0 }, "click", "unsure")
    compare(t.x, 30)
    compare(t.label, "b")
    compare(Co.buddyTarget({ cuaTarget: null, guide: null, status: "deciding", points: pts },
      { x: 0, y: 0 }, "click", "unsure"), null)
    compare(Co.buddyTarget(null, { x: 0, y: 0 }, "click", "unsure"), null)
  }

  // a following buddy hides while the pointer is on another screen; flight,
  // hold and the tail do not depend on the pointer
  function test_buddy_hidden_off_screen_only_while_following() {
    compare(Co.buddyOffScreen("follow", null), true)
    compare(Co.buddyOffScreen("follow", { x: 1, y: 1 }), false)
    compare(Co.buddyOffScreen("held", null), false)
  }
}
