.pragma library

// Omarchy theme -> Wisp tokens, QML port of wisp/theme.py (the reference).
// Same pure functions, same constants; both are tested against
// tests/fixtures/themes/*/expected.json (tests/qml/lib/tst_tokens.qml), so
// change them together. DESIGN-v2 5.1 (token map) and 5.2 (ember).
//
// Usage: derive(parseColors(colorsTomlText), parseShell(shellTomlText))
// -> { source, mode, tokens: { canvas, ink, ember, ... } } with every token
// an opaque "#rrggbb" string.

var TOKENS = ["canvas", "raised", "keyline", "keylineStrong", "ink",
  "inkMuted", "accent", "ember", "emberCore", "emberWick", "emberHalo",
  "needsYou", "fail", "ok", "selection"]

// No-Omarchy fallback palettes (wisp/theme.py DARK / LIGHT, the subset the
// derivation reads). The only hex literals Wisp chrome may contain.
var FALLBACK = {
  dark: { mode: "dark", background: "#1a1b26", foreground: "#c0caf5",
    accent: "#7aa2f7", muted: "#9aa5ce", red: "#e05555", yellow: "#e0af68",
    green: "#9ece6a", lighter_background: "#283457" },
  light: { mode: "light", background: "#f5f6fa", foreground: "#1f2335",
    accent: "#2e7de9", muted: "#4c5578", red: "#c43a3a", yellow: "#8f5e15",
    green: "#33701f", lighter_background: "#e2e6f2" }
}

var COLOR_DEFAULTS = { foreground: "#cacccc", background: "#101315",
  accent: "#cacccc", urgent: "#a55555" }
var NORMAL_BORDER_ALPHA = 0.4
var RAISED_ALPHA = 0.06
var SELECTION_ALPHA = 0.35
var EMBER_CHROMA_FLOOR = 0.05
var EMBER_URGENT_DE = 10.0
var EMBER_L = { dark: [0.70, 0.85], light: [0.45, 0.60] }
var MIX_STEP = 0.05
var L_STEP = 0.01

// --- color math -----------------------------------------------------------

function rgb(hex) {
  return [parseInt(hex.substr(1, 2), 16) / 255,
          parseInt(hex.substr(3, 2), 16) / 255,
          parseInt(hex.substr(5, 2), 16) / 255]
}

function toHex(c) {
  var s = "#"
  for (var i = 0; i < 3; i++) {
    var v = Math.max(0, Math.min(255, Math.floor(c[i] * 255 + 0.5)))
    s += (v < 16 ? "0" : "") + v.toString(16)
  }
  return s
}

function lin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4) }
function gam(c) {
  c = Math.max(0, Math.min(1, c))
  return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055
}

function oklab(hex) {
  var c = rgb(hex).map(lin)
  var l = Math.cbrt(0.4122214708 * c[0] + 0.5363325363 * c[1] + 0.0514459929 * c[2])
  var m = Math.cbrt(0.2119034982 * c[0] + 0.6806995451 * c[1] + 0.1073969566 * c[2])
  var s = Math.cbrt(0.0883024619 * c[0] + 0.2817188376 * c[1] + 0.6299787005 * c[2])
  return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
          1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
          0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]
}

function fromOklab(L, a, b) {
  var l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3)
  var m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3)
  var s = Math.pow(L - 0.0894841775 * a - 1.2914855480 * b, 3)
  return toHex([gam(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
                gam(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
                gam(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)])
}

function oklch(hex) {
  var o = oklab(hex)
  var h = Math.atan2(o[2], o[1]) * 180 / Math.PI
  return [o[0], Math.sqrt(o[1] * o[1] + o[2] * o[2]), (h + 360) % 360]
}

function withLightness(hex, L) {
  var o = oklab(hex)
  return fromOklab(Math.max(0, Math.min(1, L)), o[1], o[2])
}

function cielab(hex) {
  var c = rgb(hex).map(lin)
  var xyz = [(0.4124564 * c[0] + 0.3575761 * c[1] + 0.1804375 * c[2]) / 0.95047,
             (0.2126729 * c[0] + 0.7151522 * c[1] + 0.0721750 * c[2]),
             (0.0193339 * c[0] + 0.1191920 * c[1] + 0.9503041 * c[2]) / 1.08883]
  var f = xyz.map(function (t) {
    return t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116
  })
  return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])]
}

function deltaE(x, y) {
  var a = cielab(x), b = cielab(y)
  return Math.sqrt(Math.pow(a[0] - b[0], 2) + Math.pow(a[1] - b[1], 2)
                   + Math.pow(a[2] - b[2], 2))
}

function luminance(hex) {
  var c = rgb(hex).map(lin)
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}

function contrast(x, y) {
  var a = luminance(x), b = luminance(y)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

function mix(x, y, t) {
  var a = rgb(x), b = rgb(y)
  return toHex([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                a[2] + (b[2] - a[2]) * t])
}

function over(fg, alpha, bg) { return mix(bg, fg, alpha) }

// --- parsing --------------------------------------------------------------

var HEX6 = /^#[0-9a-fA-F]{6}$/

function parseColors(text) {
  var out = {}
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var m = lines[i].match(/^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#?[^"'#\s]+)/)
    if (!m) continue
    var k = m[1].toLowerCase(), v = m[2]
    if (HEX6.test(v)) out[k] = v.toLowerCase()
    else if (k === "mode" && (v.toLowerCase() === "light" || v.toLowerCase() === "dark"))
      out[k] = v.toLowerCase()
  }
  return out
}

function parseShell(text) {
  var out = {}, section = ""
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].replace(/^\s+|\s+$/g, "")
    if (!line || line.charAt(0) === "#") continue
    var s = line.match(/^\[([A-Za-z0-9_-]+)\]\s*(#.*)?$/)
    if (s) { section = s[1]; continue }
    var m = line.match(/^([A-Za-z0-9_-]+)\s*=\s*["']?([^"'#]+?)["']?\s*(#.*)?$/)
    if (m && section) out[section + "." + m[1]] = m[2].replace(/^\s+|\s+$/g, "")
  }
  return out
}

function shellHex(shell, key, seen) {
  seen = seen || []
  var v = shell ? shell[key] : undefined
  if (!v || seen.indexOf(key) >= 0) return null
  var parts = v.split(/\s+/), tok = ""
  for (var i = 0; i < parts.length; i++)
    if (!/^-?[\d.]+deg$/.test(parts[i])) { tok = parts[i]; break }
  if (HEX6.test(tok)) return tok.toLowerCase()
  if (shell.hasOwnProperty(tok)) return shellHex(shell, tok, seen.concat([key]))
  return null
}

// --- derivation -----------------------------------------------------------

function base(c) {
  var fg = c.foreground || c.color7 || COLOR_DEFAULTS.foreground
  return {
    foreground: fg,
    background: c.background || c.color0 || COLOR_DEFAULTS.background,
    accent: c.accent || c.color4 || COLOR_DEFAULTS.accent,
    urgent: c.red || c.color1 || COLOR_DEFAULTS.urgent,
    muted: c.muted || c.color8 || fg
  }
}

function emberFor(colors, mode) {
  var b = base(colors)
  var cand = b.accent
  if (oklch(cand)[1] < EMBER_CHROMA_FLOOR)
    cand = colors.orange || colors.yellow || cand
  if (deltaE(cand, b.urgent) < EMBER_URGENT_DE) {
    var keys = ["orange", "yellow"]
    for (var i = 0; i < keys.length; i++) {
      var alt = colors[keys[i]]
      if (alt && deltaE(alt, b.urgent) >= EMBER_URGENT_DE) { cand = alt; break }
    }
  }
  var lo = EMBER_L[mode][0], hi = EMBER_L[mode][1]
  var L = oklch(cand)[0]
  if (L >= lo && L <= hi) return cand
  return withLightness(cand, Math.min(hi, Math.max(lo, L)))
}

function mixUntil(color, toward, bg, floor) {
  var steps = Math.round(1 / MIX_STEP)
  for (var i = 0; i <= steps; i++) {
    var c = mix(color, toward, i / steps)
    if (contrast(c, bg) >= floor) return c
  }
  return toward
}

function liftUntil(color, bg, floor) {
  if (contrast(color, bg) >= floor) return color
  var L = oklch(color)[0]
  var sign = luminance(bg) > 0.18 ? -1 : 1
  var steps = Math.round(1 / L_STEP)
  var c = color
  for (var i = 1; i <= steps; i++) {
    c = withLightness(color, L + sign * i * L_STEP)
    if (contrast(c, bg) >= floor) return c
  }
  return c
}

function derive(colors, shell, source) {
  colors = colors || {}
  var b = base(colors)
  var canvas = shellHex(shell, "popups.background") || b.background
  var mode = colors.mode || (luminance(canvas) > 0.18 ? "light" : "dark")
  var ink = b.foreground, accent = b.accent
  var borderAlpha = NORMAL_BORDER_ALPHA
  if (shell && shell["controls.normal-border-alpha"] !== undefined) {
    var n = Number(shell["controls.normal-border-alpha"])
    if (isFinite(n)) borderAlpha = Math.max(0, Math.min(1, n))
  }
  var ember = emberFor(colors, mode)
  var eL = oklch(ember)[0]
  var halo = contrast(ink, ember) > contrast(b.background, ember) ? ink : b.background
  return {
    source: source || "omarchy",
    mode: mode,
    tokens: {
      canvas: canvas,
      raised: colors.lighter_background || over(ink, RAISED_ALPHA, canvas),
      keyline: over(ink, borderAlpha, canvas),
      keylineStrong: shellHex(shell, "popups.border") || accent,
      ink: ink,
      inkMuted: mixUntil(b.muted, ink, canvas, 4.5),
      accent: accent,
      ember: ember,
      emberCore: withLightness(ember, eL + 0.1),
      emberWick: withLightness(ember, eL - 0.1),
      emberHalo: halo,
      needsYou: liftUntil(colors.yellow || b.urgent, canvas, 3.0),
      fail: liftUntil(b.urgent, canvas, 3.0),
      ok: liftUntil(colors.green || accent, canvas, 3.0),
      selection: colors.selection || over(accent, SELECTION_ALPHA, canvas)
    }
  }
}

// Tokens from raw file text; empty or unparseable colors.toml -> fallback
// palette ("dark" unless fallbackName is "light"), source "fallback".
function load(colorsText, shellText, fallbackName) {
  var colors = parseColors(colorsText)
  if (Object.keys(colors).length === 0)
    return derive(FALLBACK[fallbackName === "light" ? "light" : "dark"], null, "fallback")
  return derive(colors, shellText ? parseShell(shellText) : null)
}
