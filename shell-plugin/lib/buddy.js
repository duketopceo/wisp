.pragma library

// Cursor buddy model. The geometry, spring and timing constants follow
// Clacky 0.2.0 (clacky/shell/ui/overlay.py, MIT, Raynan Wuyep; see
// THIRD_PARTY_NOTICES.md), reimplemented here and converted from its
// per-16ms ticks to seconds against a 60 Hz reference. Pure: no colors,
// no Quickshell, no timers. Buddy.qml draws what view() returns; the
// plugin root feeds step() the pointer and a frame delta.
//
// step(model, input, dt) -> model. input = { pointer:{x,y}|null, status,
// level 0..1, target, motion }. `target` is a lib/cursor.js ghostView
// result (or the same shape for a spoken point); it is live while visible
// and not "returning". view(model, { screen:{w,h}, pill:{w,h}?, motion })
// -> what to draw.

var LIVE = ["listening", "transcribing", "deciding", "acting", "awaiting_choice", "speaking"]

var OFFSET = { x: 35, y: 25 }
var REST_DEG = -35
var ENTRY_DELAY_S = 0.3        // KTD6: clears the press-time screenshot
var ENTRY_FADE_S = 0.16
var DWELL_S = 4
var RETURN_S = 1.4
var LABEL_POP_S = 0.2
var TICK = 1 / 60

function init(over) {
  var m = { phase: "hidden", live: false, placed: false, entryT: 0,
    x: 0, y: 0, vx: 0, vy: 0, rot: REST_DEG, scale: 1,
    ox: 0, oy: 0, hasPtr: false,
    fx: 0, fy: 0, tx: 0, ty: 0, t: 0, dur: 0,
    label: "", labelT: 0, clicking: false,
    level: 0, wavePhase: 0, spinT: 0, status: "idle" }
  for (var k in over) m[k] = over[k]
  return m
}

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)) }

function flightSeconds(d) { return clamp(0.35 + d / 700, 0.35, 0.7) }

// Quadratic Bezier whose control point is the midpoint raised by
// min(0.22 d, 90) px. Returns position and tangent heading (0 = up,
// clockwise, degrees) at t.
function arc(fx, fy, tx, ty, t) {
  var dx = tx - fx, dy = ty - fy
  var d = Math.sqrt(dx * dx + dy * dy)
  var cx = (fx + tx) / 2, cy = (fy + ty) / 2 - Math.min(0.22 * d, 90)
  var u = 1 - t
  var px = u * u * fx + 2 * u * t * cx + t * t * tx
  var py = u * u * fy + 2 * u * t * cy + t * t * ty
  var vx = 2 * u * (cx - fx) + 2 * t * (tx - cx)
  var vy = 2 * u * (cy - fy) + 2 * t * (ty - cy)
  var heading = (vx === 0 && vy === 0) ? REST_DEG : Math.atan2(vx, -vy) * 180 / Math.PI
  return { x: px, y: py, heading: heading }
}

function wrap180(a) {
  while (a > 180) a -= 360
  while (a < -180) a += 360
  return a
}

function targetLive(t) { return !!(t && t.visible && t.state !== "returning") }

function startFlight(n, tgt, full) {
  n.tx = tgt.x; n.ty = tgt.y
  n.label = tgt.label || ""
  n.labelT = 0
  if (!full) {
    n.phase = "held"; n.x = tgt.x; n.y = tgt.y; n.vx = 0; n.vy = 0
    n.rot = REST_DEG; n.scale = 1
    return
  }
  var dx = tgt.x - n.x, dy = tgt.y - n.y
  n.fx = n.x; n.fy = n.y
  n.dur = flightSeconds(Math.sqrt(dx * dx + dy * dy))
  n.t = 0
  n.phase = "flying"
}

function startReturn(n) {
  n.fx = n.x; n.fy = n.y; n.t = 0; n.dur = RETURN_S
  n.phase = "returning"
}

// Spring toward the pointer offset: vel = vel*0.62 + (target-pos)*0.28 per
// 60 Hz tick, split into sub-steps no larger than one tick so a 120 Hz
// output and a stalled frame both land where 60 Hz would.
function spring(n, dt) {
  var s = dt / TICK
  var steps = Math.max(1, Math.ceil(s - 1e-9))
  var h = s / steps
  var k = Math.pow(0.62, h)
  for (var i = 0; i < steps; i++) {
    n.vx = n.vx * k + (n.ox - n.x) * 0.28 * h
    n.vy = n.vy * k + (n.oy - n.y) * 0.28 * h
    n.x += n.vx * h
    n.y += n.vy * h
  }
}

function fly(n, toX, toY, dt) {
  n.t += dt
  var p = clamp(n.t / n.dur, 0, 1)
  var s = p * p * (3 - 2 * p)                    // smoothstep
  var a = arc(n.fx, n.fy, toX, toY, s)
  n.x = a.x; n.y = a.y
  var sw = Math.sin(Math.PI * p)
  n.rot = REST_DEG + wrap180(a.heading - REST_DEG) * sw
  n.scale = 1 + 0.25 * sw
  return p >= 1
}

function settle(n) { n.rot = REST_DEG; n.scale = 1 }

function step(m, input, dt) {
  var n = init(m)
  var full = input.motion === "full"
  var live = LIVE.indexOf(input.status) >= 0
  var rising = live && !m.live
  var tgt = input.target
  var tlive = targetLive(tgt)
  n.live = live
  n.status = input.status

  var ptr = input.pointer
  if (ptr && isFinite(ptr.x) && isFinite(ptr.y)) {
    n.ox = ptr.x + OFFSET.x; n.oy = ptr.y + OFFSET.y; n.hasPtr = true
  }

  // waveform level eased 0.55/0.45 per tick; phases run only in full motion
  var lv = clamp(Number(input.level) || 0, 0, 1)
  var keep = Math.pow(0.55, dt / TICK)
  n.level = n.level * keep + lv * (1 - keep)
  if (full) { n.wavePhase += dt * 6; n.spinT += dt }

  if (n.phase === "hidden") {
    if (!live) return n
    n.phase = "follow"; n.entryT = 0; n.placed = false; n.vx = 0; n.vy = 0
    settle(n)
  } else if (rising && n.phase !== "follow") {
    // a new turn cancels the tail; spring back from where it is
    n.phase = "follow"; n.vx = 0; n.vy = 0; n.placed = true; settle(n)
  }
  n.entryT += dt

  if (n.phase === "follow") {
    if (!live) { n.phase = "hidden"; n.clicking = false; return n }
    if (n.hasPtr) {
      if (!n.placed || !full) { n.x = n.ox; n.y = n.oy; n.vx = 0; n.vy = 0; n.placed = true }
      else spring(n, dt)
    }
    if (tlive && n.placed) startFlight(n, tgt, full)
  }

  if (n.phase === "flying") {
    if (tlive && (Math.abs(tgt.x - n.tx) > 0.5 || Math.abs(tgt.y - n.ty) > 0.5)) {
      startFlight(n, tgt, full)
    }
    if (n.phase === "flying" && fly(n, n.tx, n.ty, dt)) {
      n.phase = "held"; n.x = n.tx; n.y = n.ty; settle(n); n.labelT = 0
    }
  } else if (n.phase === "held") {
    n.labelT += dt
    if (live && tlive) {
      if (Math.abs(tgt.x - n.tx) > 0.5 || Math.abs(tgt.y - n.ty) > 0.5) startFlight(n, tgt, full)
    } else { n.phase = "dwelling"; n.t = 0 }
  } else if (n.phase === "dwelling" || n.phase === "returning") {
    if (live && tlive) startFlight(n, tgt, full)
    else if (n.phase === "dwelling") {
      n.t += dt; n.labelT += dt
      if (n.t >= DWELL_S) {
        if (full) startReturn(n)
        else { n.phase = live ? "follow" : "hidden"; n.x = n.ox; n.y = n.oy; n.vx = 0; n.vy = 0; settle(n) }
      }
    } else if (fly(n, n.ox, n.oy, dt)) {
      n.phase = live ? "follow" : "hidden"
      n.x = n.ox; n.y = n.oy; n.vx = 0; n.vy = 0; settle(n)
    }
  }
  n.clicking = (n.phase === "held") && !!tgt && tgt.state === "clicking"
  return n
}

function modeFor(status) {
  if (status === "listening") return "waveform"
  if (status === "transcribing" || status === "deciding" || status === "acting") return "spinner"
  if (status === "speaking") return "triangle"
  if (status === "awaiting_choice") return "triangleNeedsYou"
  return "hidden"
}

// Label pill beside a target: left edge at +10 px, centered 18 px below
// (padding 8x4 in the component). Flips left of the target near the right
// edge and above it near the bottom edge so the pill stays on screen.
function labelBox(tx, ty, pill, screen) {
  var x = tx + 10, cy = ty + 18
  if (screen && x + pill.w > screen.w) x = tx - 10 - pill.w
  if (screen && cy + pill.h / 2 > screen.h) cy = ty - 18
  if (screen) {
    x = clamp(x, 0, Math.max(0, screen.w - pill.w))
    cy = clamp(cy, pill.h / 2, Math.max(pill.h / 2, screen.h - pill.h / 2))
  }
  return { x: x, y: cy - pill.h / 2 }
}

function view(m, ctx) {
  var full = ctx.motion === "full"
  var away = m.phase === "held" || m.phase === "dwelling"
  var mode = m.live ? modeFor(m.status) : "triangle"
  if (mode === "hidden") mode = "triangle"
  var visible = m.phase !== "hidden"
  if (m.phase === "follow" && !(m.hasPtr && m.placed)) visible = false
  var fade = full ? clamp((m.entryT - ENTRY_DELAY_S) / ENTRY_FADE_S, 0, 1)
                  : (m.entryT >= ENTRY_DELAY_S ? 1 : 0)
  if (!visible) fade = 0
  var lab = { visible: false, text: "", x: 0, y: 0, scale: 0 }
  if (away && m.label !== "") {
    var pill = ctx.pill || { w: 16 + 7 * m.label.length, h: 22 }
    var box = labelBox(m.x, m.y, pill, ctx.screen)
    lab = { visible: true, text: m.label, x: box.x, y: box.y,
      scale: full ? 0.5 + 0.5 * clamp(m.labelT / LABEL_POP_S, 0, 1) : 1 }
  }
  return { visible: visible && fade > 0, phase: m.phase, x: m.x, y: m.y,
    rotation: m.rot, scale: m.scale, opacity: fade, mode: m.phase === "hidden" ? "hidden" : mode,
    clicking: m.clicking, label: lab,
    spinAngle: spinnerAngle(m.spinT, ctx.motion),
    bars: waveHeights(m.level, m.wavePhase, ctx.motion) }
}

// Five bars, profile 0.4 0.7 1.0 0.7 0.4: h = 3 + level*10*profile plus a
// 1.5 px sine wobble that only runs in full motion.
var PROFILE = [0.4, 0.7, 1.0, 0.7, 0.4]
function waveHeights(level, phase, motion) {
  var out = []
  for (var i = 0; i < 5; i++) {
    var wob = motion === "full" ? (Math.sin(phase * 1.8 + 0.35 * i) + 1) / 2 * 1.5 : 0
    out.push(3 + level * 10 * PROFILE[i] + wob)
  }
  return out
}

// Arc start angle in degrees: one revolution per 0.8 s of spinner time in
// full motion, fixed otherwise.
function spinnerAngle(t, motion) {
  return motion === "full" ? (t / 0.8 * 360) % 360 : 0
}

// Hyprland `j/cursorpos` reply -> { x, y } in global pixels, or null for an
// empty, garbled or incomplete reply (the buddy then keeps its last pointer).
function parsePointer(text) {
  var o
  try { o = JSON.parse(String(text)) } catch (e) { return null }
  if (!o || typeof o.x !== "number" || typeof o.y !== "number"
      || !isFinite(o.x) || !isFinite(o.y)) return null
  return { x: o.x, y: o.y }
}

// Global pointer -> layer coordinates of the screen rect { x, y, w, h }
// the overlay window sits on; null when the pointer is on another screen.
function layerPointer(ptr, rect) {
  if (!ptr || !rect) return null
  var x = ptr.x - rect.x, y = ptr.y - rect.y
  if (x < 0 || y < 0 || x >= rect.w || y >= rect.h) return null
  return { x: x, y: y }
}
