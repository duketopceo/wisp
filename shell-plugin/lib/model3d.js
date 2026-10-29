.pragma library

// 3D parts card (B13). Pure functions, no GL: a model arrives as named
// parts with axis-aligned boxes (wisp/model3d.py), each box is rotated and
// projected to a screen rectangle in plain JS, and a click is resolved to
// the front-most part under the pointer. The card is a small orthographic
// "blocks" view of the model, enough to point at a part and ask about it.

var W = 280              // the viewing area inside the card
var H = 200
var PAD = 8
var TITLE_H = 20
var YAW0 = 0.6           // radians: a three-quarter view to start
var PITCH0 = 0.45
var PITCH_MAX = 1.2
var FILL = 0.62          // how much of the area the model's longest side takes
var MAX_NAME = 40

// First paper model that is stored, or null. The note payload's model
// objects carry {status, title, parts:[{name, box}], source, host}.
function modelOf(note) {
  var objs = note && Array.isArray(note.objects) ? note.objects : []
  for (var i = 0; i < objs.length; i++) {
    var o = objs[i]
    if (!o || o.kind !== "model" || !o.model || o.model.status !== "ready") continue
    var parts = []
    var src = Array.isArray(o.model.parts) ? o.model.parts : []
    for (var j = 0; j < src.length; j++) {
      var p = src[j]
      if (!p || typeof p.name !== "string" || !Array.isArray(p.box) || p.box.length !== 6) continue
      var ok = true
      for (var k = 0; k < 6; k++) if (typeof p.box[k] !== "number" || !isFinite(p.box[k])) ok = false
      if (ok) parts.push({ name: p.name, box: p.box })
    }
    if (parts.length === 0) continue
    var a = o.attrs || {}
    var title = typeof a.alt === "string" && a.alt !== "" ? a.alt : String(o.model.title || "")
    return { title: title, parts: parts, source: String(o.model.source || ""), host: String(o.model.host || "") }
  }
  return null
}

function cardSize() {
  return { viewW: W, viewH: H, w: W + 2 * PAD, h: H + TITLE_H + 3 * PAD }
}

function clampPitch(p) { return Math.max(-PITCH_MAX, Math.min(PITCH_MAX, p)) }

// Screen rectangles of every part for a view (yaw about the vertical axis,
// then pitch), inside a w x h area. `depth` is the part's distance towards
// the viewer (larger = nearer), used to order and to hit-test.
function project(parts, yaw, pitch, w, h) {
  var out = []
  var cy = Math.cos(yaw), sy = Math.sin(yaw)
  var cp = Math.cos(pitch), sp = Math.sin(pitch)
  var raw = []
  var lo = [Infinity, Infinity], hi = [-Infinity, -Infinity]
  for (var i = 0; i < parts.length; i++) {
    var b = parts[i].box
    var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, dz = 0
    for (var c = 0; c < 8; c++) {
      var x = c & 1 ? b[3] : b[0], y = c & 2 ? b[4] : b[1], z = c & 4 ? b[5] : b[2]
      var rx = x * cy + z * sy
      var rz = -x * sy + z * cy
      var ry = y * cp - rz * sp
      var rd = y * sp + rz * cp
      x0 = Math.min(x0, rx); x1 = Math.max(x1, rx)
      y0 = Math.min(y0, -ry); y1 = Math.max(y1, -ry)
      dz += rd / 8
    }
    raw.push({ name: parts[i].name, index: i, x0: x0, y0: y0, x1: x1, y1: y1, depth: dz })
    lo[0] = Math.min(lo[0], x0); hi[0] = Math.max(hi[0], x1)
    lo[1] = Math.min(lo[1], y0); hi[1] = Math.max(hi[1], y1)
  }
  var mx = (lo[0] + hi[0]) / 2, my = (lo[1] + hi[1]) / 2
  var span = Math.max(hi[0] - lo[0], hi[1] - lo[1]) || 1
  var k = Math.min(w, h) * FILL / Math.max(span, 1e-6)
  for (var j = 0; j < raw.length; j++) {
    var r = raw[j]
    out.push({ name: r.name, index: r.index, depth: r.depth,
      x: w / 2 + (r.x0 - mx) * k, y: h / 2 + (r.y0 - my) * k,
      w: Math.max(6, (r.x1 - r.x0) * k), h: Math.max(6, (r.y1 - r.y0) * k) })
  }
  return out
}

// The part under (px, py): the nearest to the viewer wins; "" for none.
function hit(rects, px, py) {
  var best = -1
  for (var i = 0; i < rects.length; i++) {
    var r = rects[i]
    if (px < r.x || px > r.x + r.w || py < r.y || py > r.y + r.h) continue
    if (best < 0 || r.depth > rects[best].depth) best = i
  }
  return best < 0 ? "" : rects[best].name
}

function tidy(s, max) {
  return String(s || "").replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").replace(/^\s+|\s+$/g, "").slice(0, max)
}

// The one question a click asks. Plain words, no user-supplied markup: the
// part and model names come from a file, so they are trimmed and bounded.
function question(title, part) {
  var p = tidy(part, MAX_NAME)
  if (p === "") return ""
  var t = tidy(title, MAX_NAME)
  return t === "" ? "What is the " + p + " part, and what does it do?"
    : "What is the " + p + " of the " + t + ", and what does it do?"
}
