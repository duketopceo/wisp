.pragma library

// Scribble to ask (B7). Pure functions behind ScribbleLayer: turning a
// pointer drag into a stroke, deciding which strokes count, and the payload
// handed to `wispd scribble`. Coordinates are layer pixels (the overlay
// covers one screen), the same space as the screenshot the model sees.

var MIN_STEP = 3          // px a pointer moves before a new point is kept
var MIN_LENGTH = 24       // a drag shorter than this is a click, not a scribble
var MAX_STROKES = 12      // per turn
var MAX_POINTS = 120      // per stroke, after thinning

function begin(x, y) { return [{ x: x, y: y }] }

// The stroke with (x, y) appended when it moved far enough; same array
// when it did not.
function extend(points, x, y) {
  var last = points[points.length - 1]
  if (!last) return begin(x, y)
  var dx = x - last.x, dy = y - last.y
  if (dx * dx + dy * dy < MIN_STEP * MIN_STEP) return points
  return points.concat([{ x: x, y: y }])
}

function length(points) {
  var n = 0
  for (var i = 1; i < points.length; i++) {
    var dx = points[i].x - points[i - 1].x, dy = points[i].y - points[i - 1].y
    n += Math.sqrt(dx * dx + dy * dy)
  }
  return n
}

// A stroke counts once it is a real drag.
function counts(points) { return points.length >= 2 && length(points) >= MIN_LENGTH }

// At most `max` points, keeping the first and the last, evenly spread.
function thin(points, max) {
  var cap = max === undefined ? MAX_POINTS : max
  if (points.length <= cap) return points
  var out = []
  for (var i = 0; i < cap; i++)
    out.push(points[Math.round(i * (points.length - 1) / (cap - 1))])
  return out
}

// Keep a finished stroke if it counts; the newest MAX_STROKES win.
function commit(strokes, points) {
  if (!counts(points)) return strokes
  var next = strokes.concat([thin(points)])
  return next.length > MAX_STROKES ? next.slice(next.length - MAX_STROKES) : next
}

// {strokes: [[[x, y], ...]], w, h}: whole pixels, ready for `wispd scribble
// set`. Empty strokes is the clear message.
function payload(strokes, w, h) {
  var out = []
  for (var i = 0; i < strokes.length; i++) {
    var s = []
    for (var j = 0; j < strokes[i].length; j++)
      s.push([Math.round(strokes[i][j].x), Math.round(strokes[i][j].y)])
    out.push(s)
  }
  return { strokes: out, w: Math.round(w), h: Math.round(h) }
}

// The box around every stroke, or null.
function bounds(strokes) {
  var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (var i = 0; i < strokes.length; i++)
    for (var j = 0; j < strokes[i].length; j++) {
      var p = strokes[i][j]
      x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y)
      x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y)
    }
  return x0 === Infinity ? null : { x: x0, y: y0, w: x1 - x0, h: y1 - y0 }
}

// Is the layer taking input? Only while the talk key is held.
function active(status) { return status === "listening" }
