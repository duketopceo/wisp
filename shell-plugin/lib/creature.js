.pragma library

// Creature state model (DESIGN-v2 5.5, Ember U7). Pure data and functions:
// the 13 states and their target vectors, the client-derived transients,
// the timing rules, and the quantizers that cap redraw rate. No colors:
// tint comes from service.tokens in Creature.qml. Runs under qmltestrunner
// and node.

var STATES = ["offline", "idle", "listening", "transcribing", "thinking",
  "speaking", "acting", "awaiting_choice", "suggestion", "confirmed",
  "didnt_understand", "error", "done"]

// energy: brightness 0..1. cohesion: 1 is a clean disc, low frays the
// edge. heat: 0 ember, 1 core-white warm (urgency). gaze: unit offset of
// the wick and core, x right, y down. tempo: what moves, if anything.
var VECTORS = {
  offline:          { energy: 0.05, cohesion: 0.3,  heat: 0.0, gaze: [0, 0.6],   tempo: "none" },
  idle:             { energy: 0.25, cohesion: 0.9,  heat: 0.1, gaze: [0, -0.1],  tempo: "flicker" },
  listening:        { energy: 0.6,  cohesion: 0.7,  heat: 0.3, gaze: [0, 0.5],   tempo: "level" },
  transcribing:     { energy: 0.5,  cohesion: 0.8,  heat: 0.3, gaze: [0, 0.2],   tempo: "decay" },
  thinking:         { energy: 0.55, cohesion: 0.5,  heat: 0.4, gaze: [0.4, -0.3], tempo: "swirl" },
  speaking:         { energy: 0.5,  cohesion: 0.85, heat: 0.4, gaze: [0.5, 0.2], tempo: "pulse" },
  acting:           { energy: 0.7,  cohesion: 0.9,  heat: 0.5, gaze: [0.6, -0.2], tempo: "travel" },
  awaiting_choice:  { energy: 0.65, cohesion: 1.0,  heat: 0.8, gaze: [0, 0.6],   tempo: "beckon" },
  suggestion:       { energy: 0.4,  cohesion: 0.9,  heat: 0.2, gaze: [0.3, -0.6], tempo: "brighten" },
  confirmed:        { energy: 0.9,  cohesion: 1.0,  heat: 0.6, gaze: [0, 0],     tempo: "spike" },
  didnt_understand: { energy: 0.4,  cohesion: 0.4,  heat: 0.2, gaze: [0, 0.2],   tempo: "shake" },
  error:            { energy: 0.2,  cohesion: 0.2,  heat: 0.9, gaze: [0, 0.6],   tempo: "gutter" },
  done:             { energy: 0.25, cohesion: 0.9,  heat: 0.1, gaze: [0, -0.1],  tempo: "settle" }
}

// States that run a continuous clock (acting travels on position springs,
// not on the shader clock). Idle and done only flicker, capped.
var CONTINUOUS = ["listening", "thinking", "speaking"]
var FLICKER_HZ = 10        // idle redraw cap (R19)
var CONTINUOUS_HZ = 60     // ceiling for continuous states, even at 120 Hz

var TIMING = {
  confirmedMs: 260,
  shakeMs: 300,            // two cycles
  beckonMs: 600,
  beckonGapMs: 8000,
  beckonMax: 2,
  errorDimMs: 400,
  errorReturnMs: 6000,
  doneSettleMs: 600,
  brightenMs: 900,
  wakeDipMs: 80
}

var TRANSIENT = { confirmed: TIMING.confirmedMs, didnt_understand: TIMING.shakeMs }

function isState(s) { return STATES.indexOf(s) >= 0 }

// Reducer status (plus the client-derived pieces) -> creature state.
// `transient` wins while it is set; an error that has outlived
// errorReturnMs reads as idle (`errorSettled`). Unknown maps to offline.
function stateFor(status, transient, errorSettled) {
  if (isState(transient) && TRANSIENT.hasOwnProperty(transient)) return transient
  switch (status) {
  case "idle": return "idle"
  case "listening": return "listening"
  case "transcribing": return "transcribing"
  case "deciding": return "thinking"
  case "speaking": return "speaking"
  case "acting": return "acting"
  case "awaiting_choice": return "awaiting_choice"
  case "suggestion": return "suggestion"
  case "done": return "done"
  case "error": return errorSettled ? "idle" : "error"
  default: return "offline"
  }
}

// Transient a status change should start, or "". confirmed: a pending
// choice resolved (it left awaiting_choice for anything but an error).
// didnt_understand: the turn ended on a result that translated to that
// state (copy table RESULT_RULES, state field).
function transition(prevStatus, status, resultState) {
  if (prevStatus === status) return ""
  if (prevStatus === "awaiting_choice" && status !== "error" && status !== "offline")
    return "confirmed"
  if (resultState === "didnt_understand" && (status === "done" || status === "idle"))
    return "didnt_understand"
  return ""
}

function copyVec(v) {
  return { energy: v.energy, cohesion: v.cohesion, heat: v.heat,
    gaze: [v.gaze[0], v.gaze[1]], tempo: v.tempo }
}

function clamp01(x) { x = Number(x); return !isFinite(x) ? 0 : Math.max(0, Math.min(1, x)) }

// Uniform values for one frame. level is the mic RMS (listening only),
// envelope an optional TTS envelope 0..1 (speaking), beckon 0..1 a decaying
// pulse, shake -1..1. Mode: "full" animates everything, "reduced" changes
// brightness and heat only (no gaze, no fray motion), "off" is the static
// mark: the target vector with no live inputs.
function uniforms(state, level, envelope, mode, beckon, shake) {
  var v = copyVec(VECTORS[isState(state) ? state : "offline"])
  var e = v.energy
  if (mode !== "off") {
    if (state === "listening") e += 0.3 * clamp01(level)
    if (state === "speaking" && envelope >= 0) e += 0.25 * (clamp01(envelope) - 0.5)
    if (state === "awaiting_choice" && mode === "full") e += 0.25 * clamp01(beckon)
  }
  if (mode !== "full") { v.gaze = [0, v.gaze[1] === 0 ? 0 : (v.gaze[1] > 0 ? 0.3 : -0.1)] }
  if (mode === "full" && state === "didnt_understand") v.gaze[0] += 0.35 * (Number(shake) || 0)
  if (mode !== "full") v.cohesion = Math.max(v.cohesion, 0.5)
  v.energy = clamp01(e)
  return v
}

// Synthetic speaking rhythm when no TTS envelope exists: 5 Hz, low
// amplitude (+-0.1 of energy, far below a high-contrast flash), so
// luminance change stays within the 3 Hz rule. Reduced motion becomes one
// slow 0.5 Hz pulse. Returns an envelope 0..1.
function speakingEnvelope(tSeconds, mode) {
  if (mode === "off") return 0.5
  if (mode === "reduced") return 0.5 + 0.2 * Math.sin(2 * Math.PI * 0.5 * tSeconds)
  return 0.5 + 0.2 * Math.sin(2 * Math.PI * 5 * tSeconds)
}

// Idle flicker: three incommensurate sines, never near 0.2 Hz at visible
// amplitude, total under 3% luminance. Returns -0.03..0.03.
function flicker(tSeconds) {
  return 0.012 * Math.sin(tSeconds * 7.31) + 0.009 * Math.sin(tSeconds * 13.07 + 1.3)
    + 0.009 * Math.sin(tSeconds * 3.77 + 4.1)
}

function flickers(state) { return state === "idle" || state === "done" }

function needsClock(state, mode) {
  return mode === "full" && (CONTINUOUS.indexOf(state) >= 0 || flickers(state))
}

// Tone token by creature state (halo and body color).
var TONE = { offline: "inkMuted", error: "fail", awaiting_choice: "needsYou" }
function toneToken(state) { return TONE.hasOwnProperty(state) ? TONE[state] : "ember" }

// Clock step in seconds for a state at a display refresh rate: idle and
// done flicker at FLICKER_HZ whatever the display does; continuous states
// follow the display up to CONTINUOUS_HZ (a 120 Hz panel does not double
// the uniform rate).
function clockStep(state, hz) {
  if (CONTINUOUS.indexOf(state) >= 0) {
    var r = Number(hz)
    if (!isFinite(r) || r <= 0) r = 60
    return 1 / Math.min(r, CONTINUOUS_HZ)
  }
  return 1 / FLICKER_HZ
}

function quantize(tSeconds, state, hz) {
  var s = clockStep(state, hz)
  return Math.floor(tSeconds / s) * s
}

// Beckon: at most TIMING.beckonMax pulses, TIMING.beckonGapMs apart,
// then still. Start offsets in ms.
function beckonPlan() {
  var out = []
  for (var i = 0; i < TIMING.beckonMax; i++) out.push(i * TIMING.beckonGapMs)
  return out
}

// Where the creature sits at the end of the shake: horizontal offset in
// px for a normalized phase 0..1 (2 cycles, decaying).
function shakeOffset(phase, amplitudePx) {
  var p = clamp01(phase)
  return amplitudePx * Math.sin(p * 4 * Math.PI) * (1 - p)
}
