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
}
