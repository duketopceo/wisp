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
