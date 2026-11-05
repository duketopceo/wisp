.pragma library

// Dev tab model (U5): the argv for the one-shot `wispd dev turns --json`
// call, the parse of its reply, and the pure math the view draws with
// (gate percentages, stage shares, bar widths, label icons). No colors and
// no user-facing words here: tokens come from the service, copy from the
// copy table. Rates are fractions (0 to 1), as the daemon sends them.

var DOT = " · "

function command(wispd) { return [wispd, "dev", "turns", "--json"] }

// `wispd ... --json` stdout (envelope or bare data) -> {ok, data|error};
// `key` is the list the reply must carry ("turns", or "runs")
function _parse(stdout, key) {
  var o
  try { o = JSON.parse(stdout) } catch (e) { return { ok: false, error: "parse" } }
  if (!o || typeof o !== "object") return { ok: false, error: "parse" }
  if (o.ok === false) {
    var code = o.error && o.error.code ? String(o.error.code) : "error"
    return { ok: false, error: code }
  }
  var d = o.data && typeof o.data === "object" ? o.data : o
  if (!d || !Array.isArray(d[key])) return { ok: false, error: "parse" }
  return { ok: true, data: d }
}

function parse(stdout) { return _parse(stdout, "turns") }

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

// ---- Runs section and the dev badge (U5) ---------------------------------

function runsCommand(wispd) { return [wispd, "dev", "runs", "--json"] }

// `wispd dev runs --json` stdout -> {ok, data:{runs}|error}
function parseRuns(stdout) { return _parse(stdout, "runs") }

function isRunsEmpty(data) { return !data || _list(data.runs).length === 0 }

// newest first, as the daemon sends them
function latestRun(data) {
  var src = data ? _list(data.runs) : []
  return src.length > 0 ? src[0] : null
}

// the dev session on the state stream: state.dev = {on, runs_left}
function sessionOn(raw) {
  return !!(raw && raw.dev && raw.dev.on === true)
}

function runsLeft(raw) {
  var n = raw && raw.dev ? Number(raw.dev.runs_left) : 0
  return isFinite(n) && n > 0 ? Math.floor(n) : 0
}

// "dev · 3 runs left" while the session is on, else the local badge word.
// words: {dev, local, one, many}
function badgeText(on, left, words) {
  if (!on) return words.local
  return words.dev + DOT + left + " " + (left === 1 ? words.one : words.many)
}

// outcome order and the token each segment of the mix bar draws with
var MIX = [["success", "ok"], ["wrong_tries", "ember"],
  ["incomplete", "needsYou"], ["stopped", "fail"],
  ["unjudged", "inkMuted"]]

function usd(x) { return _num(x) ? "$" + x.toFixed(3) : "-" }

// "2026-10-30T08:12:09+00:00" -> "2026-10-30 08:12"; else the run id
function whenText(run) {
  var t = String(run.started || run.ended || "")
  var m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(t)
  if (m) return m[1] + " " + m[2]
  return run.run_id ? String(run.run_id) : "-"
}

// The latest run as the card draws it. words: {success, stopped,
// incomplete, wrong_tries, unjudged, a, b, tie} (copy table words).
function runView(run, words) {
  var r = run || {}
  var acc = r.accuracy || {}
  var mix = r.mix && r.mix.judged ? r.mix.judged : {}
  var total = 0
  var i
  for (i = 0; i < MIX.length; i++) total += _num(mix[MIX[i][0]]) ? Math.max(0, mix[MIX[i][0]]) : 0
  var segs = []
  var parts = []
  for (i = 0; i < MIX.length; i++) {
    var n = _num(mix[MIX[i][0]]) ? Math.max(0, mix[MIX[i][0]]) : 0
    if (n <= 0) continue
    segs.push({ key: MIX[i][0], n: n, ms: n, share: n / total, token: MIX[i][1] })
    parts.push(n + " " + words[MIX[i][0]])
  }
  var pairs = _list(r.pairs)
  var ab = pairs.length > 0
  var cnt = { a: 0, b: 0, tie: 0 }
  for (i = 0; i < pairs.length; i++)
    if (cnt.hasOwnProperty(pairs[i].better)) cnt[pairs[i].better]++
  return {
    when: whenText(r),
    tasks: _num(r.tasks) ? r.tasks : 0,
    judgedN: _num(r.judged_n) ? r.judged_n : 0,
    judged: pct(acc.judged), confirmed: pct(acc.confirmed),
    segments: segs, mixLine: parts.join(DOT),
    drift: _num(r.drift_count) ? r.drift_count : 0,
    cost: usd(r.cost ? r.cost.total_usd : null),
    ab: ab, vs: r.vs ? String(r.vs) : "",
    pairLine: ab ? cnt.a + " " + words.a + DOT + cnt.b + " " + words.b
      + DOT + cnt.tie + " " + words.tie : ""
  }
}
