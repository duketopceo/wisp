.pragma library
.import "cursor.js" as Cursor

// Teaching step primitives (U10). Pure functions over state.teach (what
// the walkthrough lane is waiting for) and state.points (where): they say
// which mark each step kind is drawn as, build the draw records DrawLayer
// paints through the ink layer, and decide when the "say continue" chip and
// the step counter show. Nothing here reads the pointer, owns a timer or
// draws. An unknown kind is drawn as voice-confirm (no mark, caption chip),
// the one kind that never claims Wisp can see the learner act.

var KINDS = ["click", "hover", "area", "handle", "motion", "voice-confirm"]

// Fixed by the plan's step-kind table.
var PRIMITIVE = {
  "click": "ring", "hover": "dashed-ring", "area": "region",
  "handle": "handle", "motion": "arrow", "voice-confirm": "none"
}

// Wait reasons that end the step on screen: marks and chip clear at once.
// "off-target" is a click outside the radius (the pointer stays where the
// learner left it, nothing is drawn); "done" is the last step finished.
var ENDED = ["off-target", "done"]

// Logical px. No fixture or harness number yet: click_watch's default
// radius (U4) and the grounding bake-off (U8) own the measured value.
// Until then a click ring is as wide as the minimum hit target
// (metrics.js size.control = 28) and an area covers three of them.
var RING_R = 28
var AREA_R = 84
var HANDLE_R = 7
// With no end point in the state a motion arrow sweeps this many radii
// to the right of its start.
var MOTION_SWEEP = 3

function isObj(v) { return v !== null && typeof v === "object" && !Array.isArray(v) }

function num(v, fallback) {
  var n = Number(v)
  return typeof v === "number" && isFinite(n) ? n : fallback
}

// state.teach -> { kind, radius, index, total, wait, to } or null. `radius`
// is 0 when the daemon sent none; `to` is {x,y} or null.
function normalize(raw) {
  if (!isObj(raw)) return null
  var kind = KINDS.indexOf(raw.kind) >= 0 ? raw.kind : "voice-confirm"
  var index = Math.max(1, Math.floor(num(raw.index, 1)))
  var total = Math.max(index, Math.floor(num(raw.total, index)))
  var to = isObj(raw.to) && typeof raw.to.x === "number" && typeof raw.to.y === "number"
    && isFinite(raw.to.x) && isFinite(raw.to.y) ? { x: raw.to.x, y: raw.to.y } : null
  return { kind: kind, radius: Math.max(0, num(raw.radius, 0)),
    index: index, total: total,
    wait: typeof raw.wait === "string" ? raw.wait : "", to: to }
}

function primitive(kind) {
  return PRIMITIVE.hasOwnProperty(kind) ? PRIMITIVE[kind] : "none"
}

// Draw records (lib/cursor.js drawings() shapes) for one step at the point
// (px, py). `pulse` marks the click ring that breathes in full motion.
function marks(t, px, py) {
  var r = t.radius > 0 ? t.radius : RING_R
  var a = t.radius > 0 ? t.radius : AREA_R
  if (t.kind === "click") return [{ kind: "ring", x: px, y: py, r: r, pulse: true }]
  if (t.kind === "hover") return [{ kind: "dring", x: px, y: py, r: r }]
  if (t.kind === "area") return [{ kind: "region", x: px - a, y: py - a, w: 2 * a, h: 2 * a }]
  if (t.kind === "handle") return [{ kind: "handle", x: px, y: py, r: HANDLE_R }]
  if (t.kind === "motion") {
    var ex = t.to ? t.to.x : px + MOTION_SWEEP * r
    var ey = t.to ? t.to.y : py
    return [{ kind: "curve", x1: px, y1: py, x2: ex, y2: ey }]
  }
  return []
}

// Everything the overlay needs for the step: { visible, kind, primitive,
// marks, chip, counter }. `ui` maps a copy key to its string. `points` is
// state.points; the step's mark sits on the newest one.
function view(teach, points, ui) {
  var none = { visible: false, kind: "", primitive: "none", marks: [], chip: "", counter: "" }
  var t = normalize(teach)
  if (!t || ENDED.indexOf(t.wait) >= 0) return none
  var pts = Cursor.beacons(points)
  var p = pts.length > 0 ? pts[pts.length - 1] : null
  // the chip says how to move on when Wisp is not watching for a click
  var chip = (t.kind === "voice-confirm" || t.wait === "voice" || t.wait === "settle")
    ? ui("ui.teach.say_continue") : ""
  return {
    visible: true, kind: t.kind, primitive: primitive(t.kind),
    marks: p ? marks(t, p.x, p.y) : [], chip: chip,
    counter: t.total > 1 ? t.index + " " + ui("ui.teach.of") + " " + t.total : ""
  }
}

// The ring pulse (and any other loop on a step mark) runs only in full
// motion; reduced and off draw the mark still.
function pulses(mode) { return mode === "full" }
// One breath (dim and back) and how many: three, then still. DESIGN-v2 5.5
// forbids infinite loops on chrome. 900 ms is the 'state' (220) to 'travel'
// (520) range doubled for a calm rhythm; no harness measurement.
var PULSE_MS = 900
var PULSE_COUNT = 3
var PULSE_MIN = 0.55
