.pragma library

// Ghost cursor, beacon and bubble geometry (Ember U12, U13). Pure
// functions over the reducer's `cuaTarget` and `points`: nothing here
// reads the pointer, spawns a process or owns a timer. The ghost shows
// where a CUA click will land while the real pointer stays put.

// cua.target view for GhostCursor. `arrived` is set by the component when
// its travel animation ends; `guideMode` parks the ghost (the label chip
// stays, no loop runs). Returns { visible:false } when there is no target.
function ghostView(target, guideMode, arrived, clickLabel, unsureLabel) {
  if (!target) return { visible: false, state: "parked", x: 0, y: 0, label: "", unsure: false }
  var state
  if (target.phase === "click") state = "clicking"
  else if (target.phase === "done") state = "returning"
  else state = (guideMode || arrived) ? "parked" : "traveling"
  var unsure = target.confidence < 0.5
  var label = target.label !== "" ? (clickLabel + " " + target.label) : ""
  if (unsure && label === "") label = unsureLabel
  return { visible: true, state: state, x: target.x, y: target.y, label: label, unsure: unsure }
}

function distance(a, b) {
  var dx = b.x - a.x, dy = b.y - a.y
  return Math.sqrt(dx * dx + dy * dy)
}

// Travel time for a hop is Motion.travelMs(distance(from, to), mode)
// (lib/motion.js: 320ms + 0.25ms/px capped at 520; reduced 140ms fade).

// Point on the curved path at t in 0..1: a quadratic Bezier whose control
// point sits 15% of the distance off the straight line, so the ghost
// arcs instead of sliding. The bow always leans up (screen y smaller).
function pathPoint(from, to, t) {
  var d = distance(from, to)
  var mx = (from.x + to.x) / 2, my = (from.y + to.y) / 2
  var dx = to.x - from.x, dy = to.y - from.y
  var nx = d === 0 ? 0 : -dy / d, ny = d === 0 ? 0 : dx / d
  if (ny > 0) { nx = -nx; ny = -ny }
  var cx = mx + nx * 0.15 * d, cy = my + ny * 0.15 * d
  var u = 1 - t
  return { x: u * u * from.x + 2 * u * t * cx + t * t * to.x,
           y: u * u * from.y + 2 * u * t * cy + t * t * to.y }
}

// Last `max` breadcrumbs (newest last) fading over fadeMs: returns the new
// list with an `age`-free shape; the component animates opacity.
var CRUMBS = 3
var CRUMB_FADE_MS = 2000
function pushCrumb(list, pt, max) {
  var out = (list || []).slice()
  var last = out.length ? out[out.length - 1] : null
  if (last && last.x === pt.x && last.y === pt.y) return out
  out.push({ x: pt.x, y: pt.y })
  var m = max === undefined ? CRUMBS : max
  while (out.length > m) out.shift()
  return out
}

// Beacons from state.points: [{x,y,label,step}] -> [{x,y,label,index}],
// numbered by step (or by order), at most `max`, malformed points dropped.
function beacons(points, max) {
  var out = []
  var list = Array.isArray(points) ? points : []
  for (var i = 0; i < list.length; i++) {
    var p = list[i]
    if (!p || typeof p !== "object" || typeof p.x !== "number" || typeof p.y !== "number"
        || !isFinite(p.x) || !isFinite(p.y)) continue
    var s = Number(p.step)
    out.push({ x: p.x, y: p.y, label: typeof p.label === "string" ? p.label : "",
      index: isFinite(s) && s >= 1 ? Math.floor(s) : out.length + 1 })
  }
  return out.slice(0, max === undefined ? 8 : max)
}

// Beacons hold, then fade after 8 s or on the next turn.
var BEACON_HOLD_MS = 8000
var BEACON_LAND_MS = 280

// Bubble placement: right and below the pointer (the rider offset), flip
// left or above at screen edges, never covering the pointer hotspot.
// pointer {x,y}, size {w,h}, screen {w,h}. Returns { x, y, side }.
var RIDER = 18
function bubblePlace(pointer, size, screen, margin) {
  var m = margin === undefined ? 8 : margin
  var x = pointer.x + RIDER, y = pointer.y + RIDER, side = "right"
  if (x + size.w > screen.w - m) { x = pointer.x - RIDER - size.w; side = "left" }
  if (y + size.h > screen.h - m) { y = pointer.y - RIDER - size.h; side = side === "left" ? "left-above" : "above" }
  x = Math.max(m, Math.min(x, screen.w - m - size.w))
  y = Math.max(m, Math.min(y, screen.h - m - size.h))
  // clamping may slide the box back over the pointer: push it off
  if (pointer.x >= x && pointer.x <= x + size.w && pointer.y >= y && pointer.y <= y + size.h) {
    if (pointer.y + RIDER + size.h <= screen.h - m) y = pointer.y + RIDER
    else y = Math.max(m, pointer.y - RIDER - size.h)
    side = side + "+"
  }
  return { x: x, y: y, side: side }
}

// Bubble dwell after the answer finishes: 9 s plus 40 ms per word.
function dwellMs(text) {
  var words = String(text || "").split(/\s+/).filter(function (w) { return w !== "" }).length
  return 9000 + 40 * words
}

// Answer limits: 60 columns, 12 lines, then "more" opens the console.
var BUBBLE_COLS = 60
var BUBBLE_LINES = 12
