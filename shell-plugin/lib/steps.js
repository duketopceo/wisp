.pragma library

// Step strings from wispd state ("tool arg -> result") to row models for
// StepRow. Raw tool text stays available as `raw` (tooltip or details);
// rows show the part before the arrow, and the state comes from the result.

var ARROW = /\s+(?:→|->)\s+/
var FAILED = /^(ERROR|FAIL|FAILED|REFUSED|ABORTED|CANCELLED)\b/
var CONFIRM = /^(BLOCKED|ASK_USER)\b|needs confirmation/

function parse(raw, isLast, busy) {
  raw = String(raw === undefined || raw === null ? "" : raw)
  var parts = raw.split(ARROW)
  var text = parts[0].replace(/^\s+|\s+$/g, "")
  var result = parts.length > 1 ? parts.slice(1).join(" ").replace(/^\s+|\s+$/g, "") : ""
  var state = "done"
  if (result === "" && isLast && busy) state = "running"
  else if (result === "" && !isLast) state = "done"
  else if (FAILED.test(result)) state = "failed"
  else if (CONFIRM.test(result)) state = "confirm"
  return { text: text, state: state, raw: raw }
}

function rows(steps, busy) {
  var out = []
  var list = Array.isArray(steps) ? steps : []
  for (var i = 0; i < list.length; i++)
    out.push(parse(list[i], i === list.length - 1, busy === true))
  return out
}

// Action stream entries (state.actions, contract v2) -> StepRow models.
// The daemon's lifecycle status maps onto the row states. `status` is
// the daemon status — open states (queued/in_flight/awaiting) read
// cancelled once the daemon settles (idle/done/error/offline), since an
// unresolved entry at rest is dead, not pending. `livePromptId` scopes
// awaiting rows: one carrying a different live prompt is stale even
// while another prompt waits. Only the tail shows (the stream is a
// 50-entry log; the tab is a glance).
var ACTION_STATE = { queued: "pending", in_flight: "running",
  awaiting: "confirm", done: "done", failed: "failed",
  cancelled: "cancelled" }
var SETTLED = ["idle", "done", "error", "offline"]
var OPEN = { queued: true, in_flight: true, awaiting: true }
var ACTION_ROWS_MAX = 8

function actionRows(actions, status, livePromptId) {
  var list = Array.isArray(actions) ? actions : []
  var tail = list.slice(Math.max(0, list.length - ACTION_ROWS_MAX))
  var settled = SETTLED.indexOf(String(status)) >= 0
  var out = []
  for (var i = 0; i < tail.length; i++) {
    var a = tail[i]
    if (typeof a !== "object" || a === null) a = {}
    var state = ACTION_STATE[a.status] || "done"
    var stale = settled
    if (!stale && a.status === "awaiting" && a.promptId
        && livePromptId && a.promptId !== livePromptId)
      stale = true
    if (stale && OPEN[a.status]) state = "cancelled"
    var text = String(a.label === undefined ? "" : a.label)
    if (a.target) text += " " + a.target
    out.push({ text: text, state: state,
      raw: a.reason ? text + " -> " + a.reason : text })
  }
  return out
}
