.pragma library

// Settings editor model (W22): which config keys the Panel edits, how a
// value is validated before it is sent, and the command that writes it.
// Writes go through `wispd config set KEY VALUE` only; the daemon reloads
// its config live. Pure functions, no strings shown to users: validate()
// returns a copy-table key (ui.err.*) or "".

// The field table, its validators and the bad-character rule come from
// settings_schema.js, generated from wisp/settings_schema.py, so the Panel
// and `wispd config set` cannot disagree. This file adds the Panel-side
// helpers on top.
.import "settings_schema.js" as Schema

var FIELDS = Schema.FIELDS
var KEYS = Schema.KEYS

function field(key) { return Schema.field(key) }

function group(name) {
  return FIELDS.filter(function (f) { return f.group === name })
}

function trim(s) { return Schema.trim(s) }

// "" when the value may be written, else a copy key for the inline error.
function validate(key, raw) { return Schema.validate(key, raw) }

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
