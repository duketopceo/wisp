.pragma library

// Cursor target, beacon and bubble geometry (Ember U12, U13). Pure
// functions over the reducer's `cuaTarget` and `points`: nothing here
// reads the pointer, spawns a process or owns a timer. The target shows
// where a CUA click will land while the real pointer stays put; the buddy
// (lib/buddy.js) flies there.

// cua.target view for the buddy's target. `arrived` and `guideMode` pick
// parked over traveling (the label chip stays). Returns { visible:false }
// when there is no target.
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

// How a beacon ListModel follows a new beacons() list: "append" the entries
// from `from` on when `next` extends `prev` (a point landed mid-answer, the
// earlier beacons keep their delegates), "reset" when it does not (a new
// turn, or an emptied list), "none" when nothing changed.
function beaconSync(prev, next) {
  var same = next.length >= prev.length
  for (var i = 0; same && i < prev.length; i++) {
    same = prev[i].x === next[i].x && prev[i].y === next[i].y
      && prev[i].label === next[i].label && prev[i].index === next[i].index
  }
  if (!same) return { kind: "reset", from: 0 }
  if (next.length === prev.length) return { kind: "none", from: next.length }
  return { kind: "append", from: prev.length }
}

// Beacons hold, then fade after 8 s or on the next turn.
var BEACON_HOLD_MS = 8000
var BEACON_LAND_MS = 280

// The bubble's spot is fixed (OverlayLayer: top-center under the bar) —
// no pointer-follow placement anymore.

// Bubble dwell after the answer finishes: 9 s plus 40 ms per word.
function dwellMs(text) {
  var words = String(text || "").split(/\s+/).filter(function (w) { return w !== "" }).length
  return 9000 + 40 * words
}

// Answer limits: 60 columns, 12 lines, then "more" opens the console.
var BUBBLE_COLS = 60
var BUBBLE_LINES = 12
