.pragma library

// Health section model (W22): turns the state `health` rows, the `spend`
// field and the one-shot `wispd cua status --json` / `wispd spend --json`
// results into plain rows. No strings for users here except raw names;
// labels come from the copy table in the component.

var SPECIAL = ["cua", "spend", "stt"]

function isObj(x) { return x !== null && typeof x === "object" && !Array.isArray(x) }

function row(name, h) {
  return { name: name, ok: h.ok === true, code: h.code === undefined ? null : h.code,
    since: h.since || "", latencyMs: typeof h.latency_ms === "number" ? h.latency_ms : null }
}

// {endpoints: [row], stt, cua, spend (rows or null), errors: [row]}
function sections(health) {
  var out = { endpoints: [], stt: null, cua: null, spend: null, errors: [] }
  var names = isObj(health) ? Object.keys(health).sort() : []
  for (var i = 0; i < names.length; i++) {
    var n = names[i]
    if (!isObj(health[n])) continue
    var r = row(n, health[n])
    if (n === "stt") out.stt = r
    else if (n === "cua") out.cua = r
    else if (n === "spend") out.spend = r
    else out.endpoints.push(r)
    if (!r.ok) out.errors.push(r)
  }
  return out
}

function usd(v) {
  var n = Number(v)
  return isFinite(n) ? "$" + n.toFixed(2) : ""
}

// Spend field -> {today, cap, month, monthCap, blocked, ratio}; empty
// strings when there is no cap or no data.
function spendView(spend) {
  var s = isObj(spend) ? spend : {}
  var cap = s.cap_usd === null || s.cap_usd === undefined ? NaN : Number(s.cap_usd)
  var today = Number(s.today_usd)
  return {
    has: s.today_usd !== undefined,
    today: usd(s.today_usd), month: usd(s.month_usd),
    cap: isFinite(cap) ? usd(cap) : "",
    monthCap: s.monthly_cap_usd === null || s.monthly_cap_usd === undefined ? "" : usd(s.monthly_cap_usd),
    blocked: s.blocked === true,
    ratio: isFinite(cap) && cap > 0 && isFinite(today) ? Math.max(0, Math.min(1, today / cap)) : 0
  }
}

// `wispd cua status --json` data -> view; null when never loaded.
function cuaView(c) {
  if (!isObj(c) || !c.state) return null
  return { state: String(c.state), fix: c.fix || "", kill: c.kill === true,
    dryRun: c.dry_run === true, version: c.version || "", live: c.live === true,
    mode: c.mode || "" }
}

function modelRows(models) {
  var out = []
  // a list handed in as a QML property may be a sequence wrapper, not an Array
  var list = models && typeof models.length === "number" ? models : []
  for (var i = 0; i < list.length; i++) {
    var m = list[i]
    if (!isObj(m)) continue
    out.push({ model: String(m.model || ""), calls: Number(m.calls) || 0, usd: usd(m.usd) })
  }
  return out
}
