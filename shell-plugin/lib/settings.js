.pragma library

// Settings editor model (W22): which config keys the surfaces edit, how a
// value is validated before it is sent, and the command that writes it.
// Writes go through `wispd config set KEY VALUE` only; the daemon reloads
// its config live. Pure functions, no strings shown to users: validate()
// returns a copy-table key (ui.err.*) or "".

// The field table, its validators and the bad-character rule come from
// settings_schema.js, generated from wisp/settings_schema.py, so the Panel
// and `wispd config set` cannot disagree. This file adds the Panel-side
// helpers on top.
.import "settings_schema.js" as Schema
.import "copy.js" as Copy

var FIELDS = Schema.FIELDS
var KEYS = Schema.KEYS

function field(key) { return Schema.field(key) }

var CATEGORIES = Schema.CATEGORIES
// the settings window's other pages and its whole sidebar order
// (one-surface U3); a page shows daemon state, so the window keeps the
// stream on while one is open
var PAGES = Schema.PAGES
var MANAGE_PAGES = Schema.MANAGE_PAGES
var STATUS_PAGES = Schema.STATUS_PAGES
var SIDEBAR = Schema.SIDEBAR
function isPage(name) { return PAGES.indexOf(name) >= 0 }
// the sidebar entry for a requested name: itself when known, else the
// first page (home)
function startPage(name) { return SIDEBAR.indexOf(name) >= 0 ? name : SIDEBAR[0] }

// The Panel's quick settings in one config section. The Panel tab only
// ever shows quick fields; every field validates (see validate), the
// settings window renders them all by category.
function group(name) {
  return FIELDS.filter(function (f) { return f.group === name && f.quick })
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
      out[s + "." + k] = formatValue(s + "." + k, String(val))
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

// A value in the schema's format, so a row compares equal to its default
// and the daemon receives what the schema shows: usd has two decimals
// (8 -> 8.00; blank, non-numbers and more than two decimals pass through
// for validate() to judge), int is a plain integer, bool is true or false,
// anything else is the trimmed string.
// The usd pattern here is looser than validate()'s on purpose: it only
// formats what it recognises and leaves the rest for validate() to reject.
function formatValue(key, raw) {
  var v = trim(raw)
  var f = field(key)
  if (f === null) return v
  if (f.kind === "usd") {
    var m = v.match(/^(\d+)(?:\.(\d{1,2}))?$/)
    if (!m) return v
    return m[1] + "." + ((m[2] || "") + "00").slice(0, 2)
  }
  if (f.kind === "int") return /^[+-]?\d+$/.test(v) ? String(parseInt(v, 10)) : v
  if (f.kind === "bool") {
    var b = v.toLowerCase()
    return b === "true" || b === "false" ? b : v
  }
  return v
}

// Fields by category (each key sits on exactly one page, its schema
// category), in schema order.
function byCategory() {
  if (_byCategory !== null) return _byCategory
  var out = {}
  for (var i = 0; i < CATEGORIES.length; i++) out[CATEGORIES[i]] = []
  for (var j = 0; j < FIELDS.length; j++) {
    var c = FIELDS[j].category
    if (!out[c]) out[c] = []
    out[c].push(FIELDS[j])
  }
  _byCategory = out
  return out
}
// the schema table never changes, so the grouping is built once
var _byCategory = null

function categoryFields(name) { return byCategory()[name] || [] }

// Settings matching a query: every word must appear in the label text
// (through the copy table), the help text or the key, case-insensitive.
// Returns [{key, category, def}] in schema order; no words, no rows.
function search(query) {
  var words = trim(query).toLowerCase().split(/\s+/).filter(function (w) { return w !== "" })
  if (words.length === 0) return []
  if (_haystacks === null) {
    _haystacks = FIELDS.map(function (f) {
      return [Copy.string(f.label), f.help ? Copy.string(f.help) : "", f.key].join("\n").toLowerCase()
    })
  }
  var out = []
  for (var i = 0; i < FIELDS.length; i++) {
    var f = FIELDS[i]
    var hay = _haystacks[i]
    var all = true
    for (var w = 0; w < words.length; w++) {
      if (hay.indexOf(words[w]) < 0) { all = false; break }
    }
    if (all) out.push({ key: f.key, category: f.category, def: f })
  }
  return out
}

// lower-cased search text per field, built on the first search
var _haystacks = null

function clone(o) {
  var out = {}
  for (var k in o) out[k] = o[k]
  return out
}

// --- write queue: one `wispd config set` at a time ------------------------
// The service keeps `queue` ([{key, value}], FIFO) and `states` (key ->
// "queued" | "saving" | "saved" | "error"); these functions are its rules,
// pure so they can be tested without a daemon. All return new objects.

// One queue entry per key: a newer value for a queued key replaces the
// older one in place.
function enqueue(queue, key, value) {
  var out = []
  var found = false
  for (var i = 0; i < queue.length; i++) {
    if (queue[i].key === key) { out.push({ key: key, value: value }); found = true }
    else out.push(queue[i])
  }
  if (!found) out.push({ key: key, value: value })
  return out
}

// A write for a key that is queued or saving is refused (accepted false,
// nothing changes). Otherwise the key is queued and the older "saved" marks
// are cleared, so only the latest write shows saved.
function enqueueWrite(queue, states, key, value) {
  if (states[key] === "queued" || states[key] === "saving")
    return { accepted: false, queue: queue, states: states }
  var next = {}
  for (var k in states) if (states[k] !== "saved") next[k] = states[k]
  next[key] = "queued"
  return { accepted: true, queue: enqueue(queue, key, value), states: next }
}

// The oldest queued write, marked saving; write is null when none waits.
function nextWrite(queue, states) {
  if (queue.length === 0) return { write: null, queue: queue, states: states }
  var next = clone(states)
  next[queue[0].key] = "saving"
  return { write: queue[0], queue: queue.slice(1), states: next }
}

function finishWrite(states, key, ok) {
  var next = clone(states)
  next[key] = ok ? "saved" : "error"
  return next
}
