.pragma library

// Management app views (W26): the audit log and the Hyprland binds as plain
// rows, next to lib/health.js (health, spend, cua). wisp/tui.py builds the
// same shapes from the same JSON (tests/test_manage_parity.py compares them),
// so the app and the terminal dashboard cannot drift. No colors, no strings
// for users: labels come from the copy table in the components.

function isObj(x) { return x !== null && typeof x === "object" && !Array.isArray(x) }
function pad2(n) { return (n < 10 ? "0" : "") + n }

// Epoch seconds -> "HH:MM:SS" in local time.
function clock(ts) {
  var n = Number(ts)
  if (!isFinite(n) || n <= 0) return ""
  var d = new Date(n * 1000)
  return pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds())
}

var DECISION_TONE = { allow: "ok", dry_run: "muted", cancelled: "needsYou", deny: "fail" }
function decisionTone(d) { return DECISION_TONE.hasOwnProperty(d) ? DECISION_TONE[d] : "muted" }

// cua.jsonl text (one JSON object per line, written by wisp/cua_safety.py)
// -> rows, newest first, at most `limit`. Only decision, app, tool, result
// verb and duration are read: the log never holds typed text (a length and a
// salted hash at most) and the view never shows coordinates or keys either.
function auditRows(text, limit) {
  var max = limit > 0 ? limit : 50
  var lines = String(text || "").split("\n")
  var out = []
  for (var i = lines.length - 1; i >= 0 && out.length < max; i--) {
    var l = lines[i].replace(/^\s+|\s+$/g, "")
    if (!l) continue
    var r
    try { r = JSON.parse(l) } catch (e) { continue }
    if (!isObj(r) || typeof r.tool !== "string") continue
    out.push({
      time: clock(r.ts), tool: r.tool, app: typeof r.app === "string" ? r.app : "",
      decision: typeof r.decision === "string" ? r.decision : "",
      result: typeof r.result === "string" ? r.result : "",
      ms: Number(r.ms) >= 0 ? Math.round(Number(r.ms)) : 0,
      dryRun: r.dry_run === true
    })
  }
  return out
}

var MODS = [[64, "SUPER"], [4, "CTRL"], [8, "ALT"], [1, "SHIFT"]]

// Hyprland modmask + key -> "SUPER+SHIFT+D".
function chord(mask, key) {
  var m = Number(mask) || 0
  var parts = []
  for (var i = 0; i < MODS.length; i++) if (m & MODS[i][0]) parts.push(MODS[i][1])
  if (key) parts.push(String(key))
  return parts.join("+")
}

// `wispd binds --json` data -> {hotkey, hyprland, global: [row], submaps:
// [row], hasSubmap}. A bind that carries a submap name (W24 registers the
// Esc, Enter and number keys that way) lands in `submaps`; without W24 that
// list is empty and the view says so.
function bindsView(data) {
  var d = isObj(data) ? data : {}
  var hk = isObj(d.hotkey) ? d.hotkey : {}
  var out = { hotkey: hk.chord ? String(hk.chord) : "", hyprland: d.hyprland === true,
    global: [], submaps: [], hasSubmap: false }
  var list = d.binds && typeof d.binds.length === "number" ? d.binds : []
  for (var i = 0; i < list.length; i++) {
    var b = list[i]
    if (!isObj(b)) continue
    var row = { chord: chord(b.modmask, b.key), arg: String(b.arg || ""), submap: String(b.submap || "") }
    if (row.submap !== "") out.submaps.push(row)
    else out.global.push(row)
  }
  out.hasSubmap = out.submaps.length > 0
  return out
}

// `wispd spend --json` models -> rows with a token pair.
function spendModels(models) {
  var out = []
  var list = models && typeof models.length === "number" ? models : []
  for (var i = 0; i < list.length; i++) {
    var m = list[i]
    if (!isObj(m)) continue
    var n = Number(m.usd)
    out.push({ model: String(m.model || ""), calls: Number(m.calls) || 0,
      usd: isFinite(n) ? "$" + n.toFixed(2) : "",
      tokens: (Number(m["in"]) || 0) + "/" + (Number(m.out) || 0) })
  }
  return out
}

// Tone name -> token name, for a component colouring a row.
var TONE_KEY = { ok: "ok", fail: "fail", needsYou: "needsYou", muted: "inkMuted" }

// --- settings window pages (one-surface U3) ---------------------------

// The frame state of a Status or management page. `heard` is false until
// the first state arrives after the stream turns on; `error` is the page's
// own read failure ("" when fine). Loading and error replace the page;
// offline and stale sit above what was last seen.
function pageState(heard, offline, stale, error) {
  if (!heard) return "loading"
  if (error) return "error"
  if (offline) return "offline"
  if (stale) return "stale"
  return "ready"
}
function showsContent(state) { return state !== "loading" && state !== "error" }

function _jsonLines(text) {
  var out = []
  var lines = String(text || "").split("\n")
  for (var i = 0; i < lines.length; i++) {
    var l = lines[i].trim()
    if (!l) continue
    try { out.push(JSON.parse(l)) } catch (e) {}
  }
  return out
}

// decisions.jsonl -> the newest `limit` turns as display rows, newest last:
// {time, route, ms, you, wisp}
function turnRows(text, limit) {
  var all = _jsonLines(text).filter(isObj)
  var rows = all.slice(-(limit || 30))
  return rows.map(function (d) {
    var route = isObj(d.answers) && isObj(d.answers.route) ? d.answers.route.choice : ""
    var ms = isObj(d.timing_ms) ? Number(d.timing_ms.act_ms) || 0 : 0
    return { time: String(d.ts || "").slice(11, 19), route: String(route || ""), ms: ms,
             you: String(d.transcript || ""), wisp: String(d.reply || d.result || "") }
  })
}

// corrections.jsonl -> the newest `limit` raw lines, newest first
function correctionLines(text, limit) {
  var lines = String(text || "").split("\n").filter(function (l) { return l.trim() !== "" })
  return lines.slice(-(limit || 6)).reverse()
}

// suggestions.jsonl appends status updates per key: the latest record per
// key wins, and only those still "new" are shown, newest first
function openSuggestions(text) {
  var latest = {}
  var order = []
  var recs = _jsonLines(text)
  for (var i = 0; i < recs.length; i++) {
    var r = recs[i]
    if (!isObj(r) || !r.key) continue
    if (!latest.hasOwnProperty(r.key)) { latest[r.key] = {}; order.push(r.key) }
    for (var k in r) latest[r.key][k] = r[k]
  }
  return order.filter(function (k) { return latest[k].status === "new" })
    .map(function (k) { return latest[k] }).reverse()
}

// a task entry is {status, task, ...}; older daemons publish the status
function taskOf(t) {
  if (t === null || t === undefined) return { status: "", task: "" }
  return typeof t === "string" ? { status: t, task: "" } : t
}

// `wispd binds --json` stdout -> {data, error}: error is "" when it parsed
function bindsRead(code, text) {
  if (code !== 0) return { data: null, error: "exit" }
  try {
    var doc = JSON.parse(text)
    return { data: isObj(doc) ? doc.data : null, error: "" }
  } catch (e) {
    return { data: null, error: "parse" }
  }
}
