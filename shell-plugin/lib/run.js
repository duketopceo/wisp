.pragma library

// Run-card model (plan U8): the newest run in the action stream as one
// legible object — intent echo, step cursor, in-flight step, outcome and
// mutation accounting — for BarPill and NowTab's RunCard. A run is the
// newest `route`/`act` boundary entry plus every entry after it (one
// dispatch is one run); with no boundary the whole stream is the
// cluster. Daemon-lifetime stream: a fresh daemon publishes no actions,
// so no ghost run survives a restart. A settled status
// (idle/done/error/offline) or a stale heartbeat kills still-open
// entries — the card resolves them cancelled instead of showing a dead
// run as forever-running.

var BOUNDARY = { route: true, act: true }
var OPEN = { queued: true, in_flight: true, awaiting: true }
var SETTLED = { idle: true, done: true, error: true, offline: true }
// kinds that read as work, not chatter — a tail of pure label/suggestion
// entries is not a run
var STEPLIKE = { route: true, act: true, tool: true, question: true,
  confirm: true, handoff: true, clarify: true }
// prompt-ish kinds render as cards/chips elsewhere; the in-flight line
// names tool work only
var PROMPT = { confirm: true, handoff: true, question: true,
  clarify: true, choice: true, suggestion: true }

function empty() {
  return { present: false, active: false, intent: "", key: "",
    steps: 0, stepAt: 0, current: "", outcome: "", durationS: 0,
    mutations: 0, undoRefs: [], question: null }
}

function s(x) { return typeof x === "string" ? x : "" }

function ms(at) {
  var t = Date.parse(String(at === undefined || at === null ? "" : at))
  return isFinite(t) ? t : -1
}

function join(label, target) {
  label = s(label); target = s(target)
  return target !== "" ? label + " " + target : label
}

// actions = normalized view.actions (see lib/state.js normalizeActions);
// status/promptId = view.status/view.promptId; stale = a busy turn whose
// heartbeat stopped; intent = fallback task text (goal, transcript);
// nowMs = optional clock for the active-run duration.
function card(actions, status, promptId, stale, intent, nowMs) {
  var list = Array.isArray(actions) ? actions : []
  var bi = -1
  for (var i = list.length - 1; i >= 0; i--) {
    if (BOUNDARY[list[i] && list[i].kind]) { bi = i; break }
  }
  var start = bi < 0 ? 0 : bi
  var boundary = bi < 0 ? null : list[bi]
  var settled = stale === true || SETTLED[String(status)] === true
  var open = false, steps = 0, resolved = 0, current = ""
  var failed = false, cancelled = false, steplike = false
  var mutations = 0, undoRefs = [], question = null
  var firstMs = -1, lastMs = -1
  for (i = start; i < list.length; i++) {
    var a = list[i] || {}
    var st = a.status
    if (OPEN[st]) {
      if (settled) st = "cancelled"
      else open = true
    }
    if (STEPLIKE[a.kind]) steplike = true
    if (i > start || bi < 0) {
      if (a.kind === "tool") {
        steps += 1
        if (!OPEN[st]) resolved += 1
      }
      if (st === "in_flight" && !PROMPT[a.kind])
        current = join(a.label, a.target)
      // mutation accounting: undo_ref is the daemon's own T1 marker —
      // "this step changed something and here is how to take it back".
      // `delivery` only records the channel (screenshots carry it too),
      // so it can't stand in for a change count.
      if (a.kind === "tool" && st === "done"
          && a.undoRef !== undefined && a.undoRef !== null) {
        mutations += 1
        if (undoRefs.indexOf(a.undoRef) < 0)
          undoRefs.push(a.undoRef)
      }
      if (a.kind === "question" && a.status === "awaiting" && !settled
          && a.promptId && a.promptId === promptId)
        question = { promptId: a.promptId, text: s(a.label),
                     options: a.options || [] }
    }
    if (st === "failed") failed = true
    if (st === "cancelled") cancelled = true
    var t = ms(a.at)
    if (t >= 0) { if (firstMs < 0) firstMs = t; lastMs = t }
  }
  // a bare route for a one-shot answer/launch is not a run — the answer
  // surface already covers it. The card persists once resolved until a
  // new boundary (or nothing, when the stream is empty).
  var actBoundary = boundary !== null
    && (boundary.kind === "act" || s(boundary.label) === "act")
  var present = boundary !== null
    ? actBoundary || steps > 0 || question !== null
    : steplike
  if (!present) return empty()
  var text = ""
  if (boundary) {
    if (boundary.kind === "act") {
      text = s(boundary.label).replace(/^run:\s*/, "") || s(boundary.target)
    } else {
      text = s(boundary.target) || s(intent)
        || s(boundary.label)
    }
  } else {
    text = s(intent)
  }
  var outcome = ""
  if (!open) {
    var bs = boundary ? s(boundary.status) : ""
    if (OPEN[bs]) bs = "cancelled"   // a boundary that never resolved is dead
    outcome = (bs === "done" || bs === "failed" || bs === "cancelled") ? bs
      : (failed ? "failed" : (cancelled ? "cancelled" : "done"))
  }
  var span = lastMs >= 0 && firstMs >= 0 ? lastMs - firstMs : 0
  if (open && firstMs >= 0 && isFinite(Number(nowMs)))
    span = Math.max(span, Number(nowMs) - firstMs)
  return {
    present: true, active: open, intent: text,
    key: boundary ? s(boundary.id)
      : (list.length > 0 ? s(list[list.length - 1].id) : ""),
    steps: steps,
    // step cursor ("step 3/8"): the position the card is on — the next
    // unresolved tool entry — clamped when only a prompt is left open
    stepAt: steps > 0 ? Math.min(resolved + 1, steps) : 0,
    current: current, outcome: outcome,
    durationS: Math.max(0, Math.round(span / 1000)),
    mutations: mutations, undoRefs: undoRefs.slice(0, 2),
    question: question
  }
}
