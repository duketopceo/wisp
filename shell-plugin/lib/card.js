.pragma library

// Image cards (B5). Pure functions: which picture of the paper to show, how
// big the card is, and where it goes. A card sits on calm screen space and
// never over the thing being named: placement avoids every mark, beacon and
// target rectangle (and the answer bubble) and picks the free corner or
// edge farthest from them.

var MAX_W = 280          // picture box inside the card
var MAX_H = 200
var PAD = 8              // card padding
var SOURCE_H = 20        // the source line under the picture
var MARGIN = 24          // distance from the layer's edge
var CLEAR = 24           // breathing room around what is avoided

// First paper image that is stored locally, or null. The note payload's
// image objects carry {status, local, source, host, w, h} (wisp/note.py).
function imageOf(note) {
  var objs = note && Array.isArray(note.objects) ? note.objects : []
  for (var i = 0; i < objs.length; i++) {
    var o = objs[i]
    if (!o || o.kind !== "image" || !o.image || o.image.status !== "ready") continue
    if (typeof o.image.local !== "string" || o.image.local === "") continue
    var a = o.attrs || {}
    return { local: o.image.local, source: String(o.image.source || ""), host: String(o.image.host || ""),
      w: Number(o.image.w) || 0, h: Number(o.image.h) || 0,
      alt: typeof a.alt === "string" ? a.alt : "", caption: typeof o.body === "string" ? o.body : "" }
  }
  return null
}

function fileUrl(path) {
  return "file://" + encodeURI(String(path)).replace(/#/g, "%23").replace(/\?/g, "%3F")
}

// "upload.wikimedia.org/wikipedia/.../Cat.png" for the source line: the
// address without its scheme, middle elided when long.
function sourceLine(source, max) {
  var s = String(source || "").replace(/^https?:\/\//, "")
  var n = max === undefined ? 44 : max
  if (s.length <= n) return s
  var keep = Math.floor((n - 3) / 2)
  return s.slice(0, keep) + "..." + s.slice(s.length - keep)
}

// Card size for a picture: fit inside MAX_W x MAX_H keeping the aspect; an
// unknown size gets the full box.
function cardSize(img) {
  var w = img && img.w > 0 ? img.w : MAX_W
  var h = img && img.h > 0 ? img.h : MAX_H
  var k = Math.min(MAX_W / w, MAX_H / h, 1)
  var pw = Math.max(1, Math.round(w * k)), ph = Math.max(1, Math.round(h * k))
  return { picW: pw, picH: ph, w: pw + 2 * PAD, h: ph + SOURCE_H + 3 * PAD }
}

function rect(x, y, w, h) { return { x: x, y: y, w: w, h: h } }

// Rectangles the card must stay off: beacons (x,y is the pin's tip), the
// drawings' boxes, the buddy's click target and the bubble.
function avoidRects(beacons, drawings, target, bubble) {
  var out = []
  var b = Array.isArray(beacons) ? beacons : []
  for (var i = 0; i < b.length; i++) out.push(rect(b[i].x - 24, b[i].y - 44, 48, 52))
  var d = Array.isArray(drawings) ? drawings : []
  for (var j = 0; j < d.length; j++) {
    var s = d[j]
    if (s.kind === "ring") out.push(rect(s.x - s.r, s.y - s.r, 2 * s.r, 2 * s.r))
    else if (s.kind === "hl") out.push(rect(s.x, s.y, s.w, s.h))
    else if (s.kind === "arrow") {
      out.push(rect(Math.min(s.x1, s.x2), Math.min(s.y1, s.y2), Math.abs(s.x2 - s.x1), Math.abs(s.y2 - s.y1)))
    }
  }
  if (target && typeof target.x === "number" && typeof target.y === "number") out.push(rect(target.x - 32, target.y - 32, 64, 64))
  if (bubble && bubble.w > 0 && bubble.h > 0) out.push(rect(bubble.x, bubble.y, bubble.w, bubble.h))
  return out
}

function overlap(a, b) {
  var w = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)
  var h = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y)
  return w > 0 && h > 0 ? w * h : 0
}

function gap(a, b) {
  var dx = Math.max(b.x - (a.x + a.w), a.x - (b.x + b.w), 0)
  var dy = Math.max(b.y - (a.y + a.h), a.y - (b.y + b.h), 0)
  return Math.sqrt(dx * dx + dy * dy)
}

// Candidate spots: four corners, then the middle of each side.
function spots(layerW, layerH, size) {
  var l = MARGIN, t = MARGIN
  var r = layerW - size.w - MARGIN, b = layerH - size.h - MARGIN
  var cx = Math.round((layerW - size.w) / 2), cy = Math.round((layerH - size.h) / 2)
  return [
    { side: "top-right", x: r, y: t }, { side: "bottom-right", x: r, y: b },
    { side: "bottom-left", x: l, y: b }, { side: "top-left", x: l, y: t },
    { side: "right", x: r, y: cy }, { side: "left", x: l, y: cy },
    { side: "bottom", x: cx, y: b }, { side: "top", x: cx, y: t }
  ]
}

// Where the card goes: the spot that overlaps nothing in `avoid` (grown by
// CLEAR) and is farthest from it; if every spot overlaps something, the one
// that overlaps least. Always inside the layer.
function place(layerW, layerH, size, avoid) {
  var cand = spots(layerW, layerH, size), best = null
  var grown = (avoid || []).map(function (a) { return rect(a.x - CLEAR, a.y - CLEAR, a.w + 2 * CLEAR, a.h + 2 * CLEAR) })
  for (var i = 0; i < cand.length; i++) {
    var c = cand[i]
    c.x = Math.max(0, Math.min(c.x, layerW - size.w))
    c.y = Math.max(0, Math.min(c.y, layerH - size.h))
    var box = rect(c.x, c.y, size.w, size.h)
    var over = 0, near = Infinity
    for (var j = 0; j < grown.length; j++) {
      over += overlap(box, grown[j])
      near = Math.min(near, gap(box, grown[j]))
    }
    c.over = over
    c.near = near
    if (best === null || c.over < best.over || (c.over === best.over && c.near > best.near)) best = c
  }
  return { x: best.x, y: best.y, side: best.side, clear: best.over === 0 }
}
