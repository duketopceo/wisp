.pragma library

// Layout and state-to-visual maps shared by the window-free components
// (DESIGN-v2 5.3 to 5.5, 5.8). Pure data and functions, no colors: every
// color comes from service.tokens. Spacing, radius and type values follow
// the Omarchy Style defaults so a component renders the same inside the
// shell and in the offscreen snapshot harness (which has no Style).

var spacing = { xs: 3, sm: 4, md: 6, lg: 8, xl: 10, xxl: 12, huge: 18 }
var radius = { chrome: 8, chip: 4 }
var font = { answer: 13, body: 12, label: 11, caption: 10, title: 14, icon: 14 }
var size = {
  control: 28,          // minimum hit target
  creatureRest: 28, creatureListening: 40, creaturePill: 20, creatureBar: 14,
  cursorHeight: 22, beacon: 20, tabUnderline: 2, tick: 2, keyline: 1
}
var lineHeight = 1.35

// Type and spacing scale; the older font and spacing blocks above remain
// for surfaces not yet moved over. Sizes are pixels at text scale 1.
// minimum holds independent floors (checked by tests, not derived from the
// scale): body text 14, secondary text 12; a control is 32 tall in the
// settings window and Panel, 28 on the overlay and bar.
var scale = {
  font: { caption: 12, label: 13, body: 14, answer: 15, title: 17, heading: 20 },
  space: { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, huge: 48 },
  control: { window: 32, compact: 28 },
  minimum: { body: 14, secondary: 12, control: 28, windowControl: 32 },
  textScaleRange: { min: 1, max: 2 }
}

// Text-scale hook: the host passes the desktop text size as a
// multiplier. Anything that is not a positive number reads as 1. The result
// is clamped to 1..2: a larger system text size enlarges Wisp, a smaller one
// never takes text under the minimums above.
function textScale(value) {
  var n = Number(value)
  if (!isFinite(n) || n <= 0) return 1
  return Math.max(scale.textScaleRange.min, Math.min(scale.textScaleRange.max, n))
}

// Pixel size of a named step at a text scale. Text grows and shrinks;
// hit targets do not (see controlHeight).
function fontSize(name, ts) {
  var base = scale.font.hasOwnProperty(name) ? scale.font[name] : scale.font.body
  return Math.round(base * textScale(ts))
}

// Control height: never scaled by text size, so a larger font cannot move
// the hit target (and a smaller one cannot shrink it below the minimum).
function controlHeight(compact) {
  return compact ? scale.control.compact : scale.control.window
}

// Pill radius: square themes stay square.
function pillRadius(height, chromeRadius) {
  return chromeRadius === 0 ? 0 : height / 2
}

// Copy tone (lib/copy.js STATUS tones) -> token name.
var TONE_TOKEN = { ember: "ember", needsYou: "needsYou", fail: "fail",
  ok: "ok", muted: "inkMuted" }
function toneToken(tone) { return TONE_TOKEN.hasOwnProperty(tone) ? TONE_TOKEN[tone] : "inkMuted" }

// Status -> bar glyph name (assets/icons/src bar-*). Statuses without a
// glyph of their own borrow the closest one.
var MARK_ICON = {
  idle: "bar-idle", listening: "bar-listening", transcribing: "bar-thinking",
  deciding: "bar-thinking", speaking: "bar-thinking", acting: "bar-acting",
  awaiting_choice: "bar-needs-you", suggestion: "bar-idle", done: "bar-idle",
  error: "bar-error", offline: "bar-offline"
}
function markIcon(status) { return MARK_ICON.hasOwnProperty(status) ? MARK_ICON[status] : "bar-offline" }

// Mark color token: idle and done read as plain ink, busy as ember.
var MARK_TOKEN = {
  idle: "ink", listening: "ember", transcribing: "ember", deciding: "ember",
  speaking: "ember", acting: "ember", awaiting_choice: "needsYou",
  suggestion: "accent", done: "ink", error: "fail", offline: "inkMuted"
}
function markToken(status) { return MARK_TOKEN.hasOwnProperty(status) ? MARK_TOKEN[status] : "inkMuted" }

// Creature energy (DESIGN-v2 5.5 table), 0 to 1; listening adds mic level.
var ENERGY = { offline: 0.05, idle: 0.25, listening: 0.6, transcribing: 0.5,
  deciding: 0.55, speaking: 0.5, acting: 0.7, awaiting_choice: 0.65,
  suggestion: 0.4, done: 0.25, error: 0.2 }
function energy(status, level) {
  var e = ENERGY.hasOwnProperty(status) ? ENERGY[status] : 0.25
  if (status === "listening") e += 0.3 * Math.max(0, Math.min(1, Number(level) || 0))
  return Math.min(1, e)
}

// Creature token by status (halo color).
var CREATURE_TOKEN = { offline: "inkMuted", error: "fail", awaiting_choice: "needsYou" }
function creatureToken(status) { return CREATURE_TOKEN.hasOwnProperty(status) ? CREATURE_TOKEN[status] : "ember" }

function creatureSize(status) {
  return status === "listening" ? size.creatureListening : size.creatureRest
}

// "1m 05s" style elapsed text from seconds; tabular, no units spelled out.
function elapsed(seconds) {
  var s = Math.max(0, Math.floor(Number(seconds) || 0))
  var m = Math.floor(s / 60)
  var r = s % 60
  if (m === 0) return s + "s"
  return m + "m " + (r < 10 ? "0" : "") + r + "s"
}
