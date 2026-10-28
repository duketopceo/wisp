.pragma library

// Hand-drawn ink (B4). Pure functions: nothing here reads the pointer, owns
// a timer or draws. They turn a declarative mark ({kind, x, y, ...} from
// lib/cursor.js drawings()) into pen strokes with a little wobble and a
// tapered width, say how far a stroke has been drawn at a moment, and pick
// light or dark from the luminance under a mark. DrawLayer.qml paints what
// these return. An unknown mark kind returns no strokes: it is dropped, never
// executed.

var WOBBLE_PX = 1.4        // pen wander, in layer pixels
var BASE_WIDTH = 3         // stroke width at its fattest
var MIN_WIDTH = 1          // pen tip at the ends
var DEFAULT_REVEAL_MS = 300
var REVEAL_FRACTION = 0.6  // of the sentence's spoken time
var REVEAL_MIN_MS = 250
var REVEAL_MAX_MS = 1800
var DASH_PX = 14
var GAP_PX = 8
var LIGHT_BELOW = 0.179    // WCAG crossover: white and black text contrast equally

// ---- determinism: the same mark always wobbles the same way ----

function seedOf(d) {
  var s = String(d.kind)
  var keys = ["x", "y", "r", "w", "h", "x1", "y1", "x2", "y2"]
  for (var i = 0; i < keys.length; i++) s += "|" + Math.round(Number(d[keys[i]]) || 0)
  var h = 2166136261
  for (var j = 0; j < s.length; j++) {
    h ^= s.charCodeAt(j)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function rng(seed) {
  var a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) >>> 0
    var t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// ---- geometry ----

function lerp(a, b, t) { return a + (b - a) * t }

// A pen path wanders: smooth low-frequency drift, not per-point jitter.
function wander(rand, n, amp) {
  var out = [], v = 0, target = (rand() - 0.5) * 2 * amp
  for (var i = 0; i < n; i++) {
    if (i % 6 === 0) target = (rand() - 0.5) * 2 * amp
    v += (target - v) * 0.35
    out.push(v)
  }
  return out
}

function ringStroke(d, rand) {
  var n = 64
  var wob = wander(rand, n + 1, Math.min(WOBBLE_PX, d.r * 0.08))
  var a0 = rand() * Math.PI * 2
  var turns = 1.07 + rand() * 0.05          // closes, then overshoots a little
  var grow = (rand() - 0.5) * 0.06
  var out = []
  for (var i = 0; i <= n; i++) {
    var t = i / n
    var a = a0 + t * turns * Math.PI * 2
    var rr = d.r * (1 + grow * t) + wob[i]
    out.push({ x: d.x + Math.cos(a) * rr, y: d.y + Math.sin(a) * rr })
  }
  return out
}

function line(x1, y1, x2, y2, rand, bend) {
  var dx = x2 - x1, dy = y2 - y1
  var len = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
  var nx = -dy / len, ny = dx / len
  var n = Math.max(6, Math.min(40, Math.ceil(len / 10)))
  var wob = wander(rand, n + 1, WOBBLE_PX)
  var out = []
  for (var i = 0; i <= n; i++) {
    var t = i / n
    var off = Math.sin(t * Math.PI) * bend + wob[i] * Math.pow(Math.sin(t * Math.PI), 0.5)
    out.push({ x: lerp(x1, x2, t) + nx * off, y: lerp(y1, y2, t) + ny * off })
  }
  return out
}

function arrowStrokes(d, rand) {
  var dx = d.x2 - d.x1, dy = d.y2 - d.y1
  var len = Math.sqrt(dx * dx + dy * dy)
  var bend = (rand() - 0.5) * Math.min(len * 0.08, 14)
  var shaft = line(d.x1, d.y1, d.x2, d.y2, rand, bend)
  var tip = shaft[shaft.length - 1]
  var ang = Math.atan2(tip.y - shaft[shaft.length - 4 < 0 ? 0 : shaft.length - 4].y,
                       tip.x - shaft[shaft.length - 4 < 0 ? 0 : shaft.length - 4].x)
  var head = Math.min(14, Math.max(6, len * 0.35))
  var strokes = [shaft]
  var sides = [-1, 1]
  for (var i = 0; i < sides.length; i++) {
    var back = ang + Math.PI + sides[i] * (Math.PI / 6 + (rand() - 0.5) * 0.12)
    var hl = head * (0.9 + rand() * 0.2)
    strokes.push([{ x: tip.x, y: tip.y },
      { x: tip.x + Math.cos(back) * hl, y: tip.y + Math.sin(back) * hl }])
  }
  return strokes
}

// Cut a polyline into dashes of DASH_PX with GAP_PX between.
function dashed(poly) {
  var out = [], cur = [], on = true, left = DASH_PX
  for (var i = 1; i < poly.length; i++) {
    var a = poly[i - 1], b = poly[i]
    var seg = Math.sqrt((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y))
    var at = 0
    if (on && cur.length === 0) cur.push({ x: a.x, y: a.y })
    while (seg - at > left) {
      at += left
      var t = at / seg
      var p = { x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t) }
      if (on) { cur.push(p); out.push(cur); cur = [] ; on = false; left = GAP_PX }
      else { cur = [p]; on = true; left = DASH_PX }
    }
    left -= seg - at
    if (on) cur.push({ x: b.x, y: b.y })
  }
  if (on && cur.length > 1) out.push(cur)
  return out
}

function frameStrokes(d, rand) {
  var x = d.x, y = d.y, w = d.w, h = d.h
  var corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]
  var path = []
  for (var i = 0; i < 4; i++) {
    var seg = line(corners[i][0], corners[i][1], corners[i + 1][0], corners[i + 1][1], rand, 0)
    path = path.concat(i === 0 ? seg : seg.slice(1))
  }
  return dashed(path)
}

// Tapered width for each point of an n-point stroke: pen down, full, lift.
function widths(n, base) {
  var b = base === undefined ? BASE_WIDTH : base
  var out = []
  for (var i = 0; i < n; i++) {
    var t = n > 1 ? i / (n - 1) : 1
    var k = Math.min(1, t / 0.15, (1 - t) / 0.25 + 0.25)
    out.push(MIN_WIDTH + (b - MIN_WIDTH) * Math.max(0, Math.min(1, k)))
  }
  return out
}

// Strokes for one mark: { strokes: [[{x,y,w}...]...], fill: {x,y,w,h}|null }.
// An unknown kind has no strokes.
function strokesFor(d) {
  var rand = rng(seedOf(d))
  var raw = [], fill = null
  if (d.kind === "ring") raw = [ringStroke(d, rand)]
  else if (d.kind === "arrow") raw = arrowStrokes(d, rand)
  else if (d.kind === "hl") { raw = frameStrokes(d, rand); fill = { x: d.x, y: d.y, w: d.w, h: d.h } }
  var strokes = []
  for (var i = 0; i < raw.length; i++) {
    var w = widths(raw[i].length)
    var s = []
    for (var j = 0; j < raw[i].length; j++) s.push({ x: raw[i][j].x, y: raw[i][j].y, w: w[j] })
    strokes.push(s)
  }
  return { strokes: strokes, fill: fill }
}

// Bounding box of a mark's strokes and fill, grown by `pad`: the canvas it
// is painted on.
function bounds(ink, pad) {
  var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  function add(x, y) {
    if (x < x0) x0 = x
    if (y < y0) y0 = y
    if (x > x1) x1 = x
    if (y > y1) y1 = y
  }
  for (var i = 0; i < ink.strokes.length; i++) {
    for (var j = 0; j < ink.strokes[i].length; j++) add(ink.strokes[i][j].x, ink.strokes[i][j].y)
  }
  if (ink.fill) { add(ink.fill.x, ink.fill.y); add(ink.fill.x + ink.fill.w, ink.fill.y + ink.fill.h) }
  if (x0 === Infinity) return { x: 0, y: 0, w: 0, h: 0 }
  return { x: x0 - pad, y: y0 - pad, w: x1 - x0 + 2 * pad, h: y1 - y0 + 2 * pad }
}

function pathLength(poly) {
  var n = 0
  for (var i = 1; i < poly.length; i++) {
    n += Math.sqrt((poly[i].x - poly[i - 1].x) * (poly[i].x - poly[i - 1].x)
      + (poly[i].y - poly[i - 1].y) * (poly[i].y - poly[i - 1].y))
  }
  return n
}

// The first fraction p (0..1) of a stroke, cut at the exact length.
function partial(poly, p) {
  if (p >= 1) return poly
  if (p <= 0 || poly.length < 2) return poly.slice(0, 1)
  var want = pathLength(poly) * p, out = [poly[0]], run = 0
  for (var i = 1; i < poly.length; i++) {
    var a = poly[i - 1], b = poly[i]
    var seg = Math.sqrt((b.x - a.x) * (b.x - a.x) + (b.y - a.y) * (b.y - a.y))
    if (run + seg >= want) {
      var t = seg > 0 ? (want - run) / seg : 0
      out.push({ x: lerp(a.x, b.x, t), y: lerp(a.y, b.y, t), w: lerp(a.w, b.w, t) })
      return out
    }
    out.push(b)
    run += seg
  }
  return out
}

// ---- timing ----

// How long the pen takes: a share of the sentence's spoken time, bounded.
// No spoken time known (a voice-off turn) keeps the plain draw-on.
function revealMs(sentenceMs) {
  var s = Number(sentenceMs)
  if (!isFinite(s) || s <= 0) return DEFAULT_REVEAL_MS
  return Math.round(Math.max(REVEAL_MIN_MS, Math.min(REVEAL_MAX_MS, s * REVEAL_FRACTION)))
}

// Only full motion animates; reduced and off draw the finished mark at once
// (zero animation frames).
function animates(mode) { return mode === "full" }

// Draw progress 0..1 of a mark that started at startMs and takes ms. Never
// above 0 before its start: a mark does not appear ahead of its sentence.
function progress(startMs, ms, nowMs, mode) {
  if (!animates(mode)) return 1
  if (nowMs < startMs) return 0
  var d = ms > 0 ? ms : DEFAULT_REVEAL_MS
  var t = Math.min(1, (nowMs - startMs) / d)
  return 1 - Math.pow(1 - t, 3)
}

// Speech ended early (or was stopped): every mark is complete this frame.
function finishNow(count) {
  var out = []
  for (var i = 0; i < count; i++) out.push(1)
  return out
}

// ---- luminance ----

function channel(v) {
  var c = Math.max(0, Math.min(255, v)) / 255
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

// WCAG relative luminance of an sRGB colour given 0..255 channels.
function luminance(r, g, b) {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
}

// Mean luminance of a rect of an RGBA byte array (width w).
function meanLuminance(rgba, w, h, rx, ry, rw, rh) {
  var x0 = Math.max(0, Math.floor(rx)), y0 = Math.max(0, Math.floor(ry))
  var x1 = Math.min(w, Math.ceil(rx + rw)), y1 = Math.min(h, Math.ceil(ry + rh))
  var sum = 0, n = 0
  for (var y = y0; y < y1; y++) {
    for (var x = x0; x < x1; x++) {
      var i = (y * w + x) * 4
      sum += luminance(rgba[i], rgba[i + 1], rgba[i + 2])
      n++
    }
  }
  return n ? sum / n : 0.5
}

// Region tone from its luminance.
function tone(lum) { return lum < LIGHT_BELOW ? "dark" : "light" }

// Text colour that reads on a region of that luminance: light on dark, dark
// on light.
function textOn(lum) { return lum < LIGHT_BELOW ? "light" : "dark" }
