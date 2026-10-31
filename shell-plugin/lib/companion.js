.pragma library
.import "cursor.js" as Cursor

// Companion surface rules (Ember U11, U12): which transient overlays show.
// Pure; the host window feeds it the reducer view and applies the result.
// The corner creature and console were dropped 2026-10-07 — the live
// surface is the bar pill; these rules govern only wisp-points.

var PILL_STATUSES = ["listening", "transcribing", "deciding", "acting", "awaiting_choice"]

// The listening pill owns live progress and choices.
function pillVisible(status) { return PILL_STATUSES.indexOf(status) >= 0 }

// Where the cursor buddy points, in layer coordinates: a cua.target (global,
// shifted by the window's screen origin), else a guide step (already layer
// coordinates), else the newest point while speaking. `s` is the reducer
// view ({cuaTarget, guide, status, points}); null when nothing is live.
function buddyTarget(s, origin, clickLabel, unsureLabel) {
  if (!s) return null
  if (s.cuaTarget) {
    var v = Cursor.ghostView(s.cuaTarget, false, false, clickLabel, unsureLabel)
    v.x -= origin.x
    v.y -= origin.y
    return v
  }
  var g = s.guide
  if (g) {
    return Cursor.ghostView({ x: g.x, y: g.y, label: g.label ? String(g.label) : "",
      confidence: 1, phase: "aim" }, true, false, clickLabel, unsureLabel)
  }
  if (s.status === "speaking") {
    var pts = Cursor.beacons(s.points)
    if (pts.length > 0) {
      var p = pts[pts.length - 1]
      return { visible: true, state: "parked", x: p.x, y: p.y, label: p.label, unsure: false }
    }
  }
  return null
}

// A following buddy hides while the pointer is on another screen (no layer
// position); flight, hold and the post-turn tail do not need the pointer.
function buddyOffScreen(phase, pointer) { return phase === "follow" && pointer === null }
