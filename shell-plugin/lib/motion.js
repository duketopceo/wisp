.pragma library

// Motion tokens (DESIGN-v2 5.5). Springs are Qt SpringAnimation values
// approximating the M3 Expressive tokens; durations are ms.

var spring = {
  spatialFast: { spring: 6.0, damping: 0.45 },     // ghost click hop, chip press
  spatialDefault: { spring: 4.0, damping: 0.35 },  // travel to target, panel morph
  spatialSlow: { spring: 2.5, damping: 0.3 }       // drifting home
}

var duration = {
  instant: 90,
  quick: 140,          // = Omarchy kit
  state: 220,
  effectsFast: 90,     // opacity, color, uniforms (OutCubic)
  effectsDefault: 160,
  effectsSlow: 280
}

var MODES = ["full", "reduced", "off"]

// [ui] motion wins when valid; otherwise Hyprland animations:enabled
// decides (false -> reduced). Unknown -> full.
function resolveMode(configValue, animationsEnabled) {
  if (MODES.indexOf(configValue) >= 0) return configValue
  return animationsEnabled === false ? "reduced" : "full"
}

// Enter uses OutCubic; exit uses InCubic at ~70% of the enter duration.
function exitMs(enterMs) { return Math.round(enterMs * 0.7) }

// Travel: 320ms + 0.25ms/px, capped at 520. Reduced motion cross-fades
// in `quick`; off is instant.
function travelMs(distancePx, mode) {
  if (mode === "off") return 0
  if (mode === "reduced") return duration.quick
  return Math.min(520, Math.round(320 + 0.25 * Math.max(0, distancePx)))
}

// Only the creature loops, only in states that need it, only in full mode.
var LOOPING = ["listening", "deciding", "thinking", "speaking"]
function loops(status, mode) {
  return mode === "full" && LOOPING.indexOf(status) >= 0
}
