.pragma library

// Settings editor model (W22): which config keys the Panel edits, how a
// value is validated before it is sent, and the command that writes it.
// Writes go through `wispd config set KEY VALUE` only; the daemon reloads
// its config live. Pure functions, no strings shown to users: validate()
// returns a copy-table key (ui.err.*) or "".

var BUDGET = "budget"
var CUA = "cua"
var POINTER = "pointer"

// kind: usd (blank means no cap), int, bool, choice
var FIELDS = [
  { key: "budget.daily_usd", group: BUDGET, kind: "usd", label: "ui.set.daily" },
  { key: "budget.monthly_usd", group: BUDGET, kind: "usd", label: "ui.set.monthly" },
  { key: "pointer.mode", group: POINTER, kind: "choice", label: "ui.set.pointer",
    options: ["guide", "drive", "auto"] },
  { key: "cua.dry_run", group: CUA, kind: "bool", label: "ui.set.dry_run" },
  { key: "cua.kill_switch", group: CUA, kind: "bool", label: "ui.set.kill" },
  { key: "cua.confirm", group: CUA, kind: "choice", label: "ui.set.confirm",
    options: ["tier", "always"] },
  { key: "cua.max_clicks_per_min", group: CUA, kind: "int", min: 1, max: 600,
    label: "ui.set.clicks" },
  { key: "cua.max_per_turn", group: CUA, kind: "int", min: 1, max: 200,
    label: "ui.set.per_turn" }
]

var BAD_CHARS = /["\\#\n]/

function field(key) {
  for (var i = 0; i < FIELDS.length; i++)
    if (FIELDS[i].key === key) return FIELDS[i]
  return null
}

function group(name) {
  return FIELDS.filter(function (f) { return f.group === name })
}

function trim(s) { return String(s === undefined || s === null ? "" : s).replace(/^\s+|\s+$/g, "") }

// "" when the value may be written, else a copy key for the inline error.
function validate(key, raw) {
  var f = field(key)
  if (f === null) return "ui.err.unknown"
  var v = trim(raw)
  if (BAD_CHARS.test(v)) return "ui.err.chars"
  if (f.kind === "usd") {
    if (v === "") return ""
    if (!/^\d+(\.\d+)?$/.test(v)) return "ui.err.number"
    if (Number(v) > 100000) return "ui.err.range"
    return ""
  }
  if (f.kind === "int") {
    if (!/^\d+$/.test(v)) return "ui.err.number"
    var n = Number(v)
    return n < f.min || n > f.max ? "ui.err.range" : ""
  }
  if (f.kind === "bool") return v === "true" || v === "false" ? "" : "ui.err.choice"
  if (f.kind === "choice") return f.options.indexOf(v) >= 0 ? "" : "ui.err.choice"
  return "ui.err.unknown"
}

// The argv that writes one key; the value is trimmed.
function setCommand(wispd, key, raw) {
  return [wispd, "config", "set", key, trim(raw)]
}

// `wispd config show --json` envelope or bare config -> {"section.key": "value"}
function flatten(cfg) {
  var out = {}
  var c = cfg && cfg.data && cfg.data.config ? cfg.data.config : (cfg && cfg.config ? cfg.config : cfg)
  if (!c || typeof c !== "object") return out
  for (var s in c) {
    var sec = c[s]
    if (!sec || typeof sec !== "object" || Array.isArray(sec)) continue
    for (var k in sec) {
      var val = sec[k]
      if (typeof val === "object") continue
      out[s + "." + k] = String(val)
    }
  }
  return out
}

// stderr of a failed `wispd config set`: "E_BAD_CONFIG: sentence" (plus a
// Try line) -> the sentence; anything else passes through trimmed.
function errorText(stderr) {
  var lines = String(stderr || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var m = lines[i].match(/^E_[A-Z_]+:\s*(.*)$/)
    if (m) return trim(m[1])
  }
  return trim(lines[0])
}
