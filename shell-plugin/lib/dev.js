.pragma library

// Dev tab model (U5): the argv for the one-shot `wispd dev turns --json`
// call, the parse of its reply, and the pure math the view draws with
// (gate percentages, stage shares, bar widths, label icons). No colors and
// no user-facing words here: tokens come from the service, copy from the
// copy table. Rates are fractions (0 to 1), as the daemon sends them.

var DOT = " · "

function command(wispd) { return [wispd, "dev", "turns", "--json"] }

// `wispd ... --json` stdout (envelope or bare data) -> {ok, data|error}
function parse(stdout) {
  var o
  try { o = JSON.parse(stdout) } catch (e) { return { ok: false, error: "parse" } }
  if (!o || typeof o !== "object") return { ok: false, error: "parse" }
  if (o.ok === false) {
    var code = o.error && o.error.code ? String(o.error.code) : "error"
    return { ok: false, error: code }
  }
  var d = o.data && typeof o.data === "object" ? o.data : o
  if (!d || !Array.isArray(d.turns)) return { ok: false, error: "parse" }
  return { ok: true, data: d }
}

// QML hands arrays over as list wrappers that Array.isArray rejects
function _list(v) {
  return v && typeof v !== "string" && typeof v.length === "number" ? v : []
}

function isEmpty(data) {
  return !data || _list(data.turns).length === 0
}

function _num(v) { return typeof v === "number" && isFinite(v) }

function pct(rate) { return _num(rate) ? Math.round(rate * 100) + "%" : "-" }

function _clamp01(v) { return Math.max(0, Math.min(1, v)) }

// The gate card: "<rate> of <gate>" with a tone (fail below the gate, ok at
// or above it, muted when either side is unknown), the bar fill and the
// tick position (-1 when no gate is set).
function gateView(gate) {
  var g = gate || {}
  var hasRate = _num(g.rate)
  var hasGate = _num(g.gate_rate)
  var tone = "muted"
  if (hasRate && hasGate) tone = g.rate >= g.gate_rate ? "ok" : "fail"
  return {
    rateText: pct(g.rate), gateText: pct(g.gate_rate), tone: tone,
    fill: hasRate ? _clamp01(g.rate) : 0,
    tick: hasGate ? _clamp01(g.gate_rate) : -1,
    labelled: g.labelled || 0, minTurns: g.min_turns || 0
  }
}

// "act 27% · launch 50% · answer 0%": kinds with a rate only
function kindLine(kinds) {
  var out = []
  for (var k in (kinds || {})) {
    var r = kinds[k] ? kinds[k].rate : null
    if (_num(r)) out.push(k + " " + pct(r))
  }
  return out.join(DOT)
}

function seconds(ms) { return _num(ms) ? (ms / 1000).toFixed(1) + " s" : "-" }

// "act · 4 steps · 2.4 s": parts that exist, joined; words = {step, steps}
function routeLine(t, words) {
  var parts = []
  if (t.route) parts.push(t.route)
  if (_num(t.act_steps)) parts.push(t.act_steps + " " + (t.act_steps === 1 ? words.step : words.steps))
  if (_num(t.total_ms)) parts.push(seconds(t.total_ms))
  return parts.join(DOT)
}

// Each stage's ms as a share of the turn total; the denominator is never
// below the sum of the stages, so the shares add to at most 1.
function stageShares(stages, total) {
  var src = _list(stages)
  var sum = 0
  for (var i = 0; i < src.length; i++) sum += _num(src[i].ms) ? Math.max(0, src[i].ms) : 0
  var denom = Math.max(sum, _num(total) ? total : 0)
  if (denom <= 0) return []
  var out = []
  for (var j = 0; j < src.length; j++) {
    var ms = _num(src[j].ms) ? Math.max(0, src[j].ms) : 0
    out.push({ name: String(src[j].name), ms: ms, share: ms / denom })
  }
  return out
}

// Pixel widths for a stacked bar `width` px wide: floor each share, keep a
// stage that has time at least 1 px, never exceed `width` in total.
function barWidths(shares, width) {
  var w = []
  var used = 0
  for (var i = 0; i < shares.length; i++) {
    var px = Math.floor(shares[i].share * width)
    if (px < 1 && shares[i].ms > 0) px = 1
    w.push(px)
    used += px
  }
  for (var j = w.length - 1; used > width && j >= 0; j--) {
    var cut = Math.min(w[j] - (shares[j].ms > 0 ? 1 : 0), used - width)
    if (cut > 0) { w[j] -= cut; used -= cut }
  }
  return w
}

function labelIcon(label) {
  return label === "correct" ? "check" : label === "incorrect" ? "cross" : "hollow"
}

function labelTone(label) {
  return label === "correct" ? "ok" : label === "incorrect" ? "fail" : "muted"
}

// the turn with this id, else the newest (the first), else null
function selected(turns, id) {
  var src = _list(turns)
  for (var i = 0; i < src.length; i++) if (id && src[i].id === id) return src[i]
  return src.length > 0 ? src[0] : null
}

// stage names in order of first appearance across the turns shown
function stageNames(turns) {
  var seen = {}
  var out = []
  var src = _list(turns)
  for (var i = 0; i < src.length; i++) {
    var st = src[i].stages || []
    for (var j = 0; j < st.length; j++) {
      if (!seen[st[j].name]) { seen[st[j].name] = true; out.push(st[j].name) }
    }
  }
  return out
}

// Distinct theme tokens for stage colors; red (fail) is left out so a stage
// never reads as an error.
var STAGE_TOKENS = ["ember", "ok", "needsYou", "ink", "inkMuted", "accent"]
function stageToken(names, name) {
  var i = names.indexOf(name)
  return i < 0 ? "inkMuted" : STAGE_TOKENS[i % STAGE_TOKENS.length]
}

function toneToken(tone) {
  return tone === "ok" ? "ok" : tone === "fail" ? "fail" : "inkMuted"
}
