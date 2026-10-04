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
