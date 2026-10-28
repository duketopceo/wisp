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

// Drawings from state.drawings: [{kind:"ring"|"arrow"|"hl", ...}] ->
// full records {kind,x,y,r,w,h,x1,y1,x2,y2,ms,tone} (unused fields 0 or "",
// so a ListModel sees one role set), at most `max` (16 = the daemon's
// per-turn cap), malformed shapes dropped. `ms` is the spoken time of the
// sentence the mark belongs to (the pen's pace, lib/ink.js), `tone` is
// "light" or "dark" for the screen under it; both optional.
function drawings(list, max) {
  var out = []
  var src = Array.isArray(list) ? list : []
  function nums(o, keys) {
    for (var i = 0; i < keys.length; i++) {
      if (typeof o[keys[i]] !== "number" || !isFinite(o[keys[i]])) return false
    }
    return true
  }
  for (var i = 0; i < src.length; i++) {
    var d = src[i]
    if (!d || typeof d !== "object") continue
    var r = { kind: d.kind, x: 0, y: 0, r: 0, w: 0, h: 0, x1: 0, y1: 0, x2: 0, y2: 0,
      ms: (typeof d.ms === "number" && isFinite(d.ms) && d.ms > 0) ? d.ms : 0,
      tone: (d.tone === "light" || d.tone === "dark") ? d.tone : "" }
    if (d.kind === "ring" && nums(d, ["x", "y", "r"]) && d.r > 0) {
      r.x = d.x; r.y = d.y; r.r = d.r
    } else if (d.kind === "hl" && nums(d, ["x", "y", "w", "h"]) && d.w > 0 && d.h > 0) {
      r.x = d.x; r.y = d.y; r.w = d.w; r.h = d.h
    } else if (d.kind === "arrow" && nums(d, ["x1", "y1", "x2", "y2"])) {
      r.x1 = d.x1; r.y1 = d.y1; r.x2 = d.x2; r.y2 = d.y2
    } else continue
    out.push(r)
  }
  return out.slice(0, max === undefined ? 16 : max)
}

// How the draw layer's ListModel follows a new drawings() list; same
// contract as beaconSync: "append" from `from` when `next` extends `prev`
// (a sentence's shape landed, earlier shapes never replay their draw-on),
// "reset" when it does not, "none" when nothing changed.
function drawSync(prev, next) {
  var keys = ["kind", "x", "y", "r", "w", "h", "x1", "y1", "x2", "y2", "ms", "tone"]
  var same = next.length >= prev.length
  for (var i = 0; same && i < prev.length; i++) {
    for (var k = 0; same && k < keys.length; k++) same = prev[i][keys[k]] === next[i][keys[k]]
  }
  if (!same) return { kind: "reset", from: 0 }
  if (next.length === prev.length) return { kind: "none", from: next.length }
  return { kind: "append", from: prev.length }
}

// Draw-layer look (Clacky's overlay): ~3 px strokes, a 14 px arrowhead at
// 30 degrees, a highlight fill at alpha 0.18; strokes draw on over 300 ms.
var DRAW_STROKE = 3
var DRAW_HL_STROKE = 2
var DRAW_HEAD = 14
var DRAW_HEAD_DEG = 30
var DRAW_HL_ALPHA = 0.18
var DRAW_ON_MS = 300

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
