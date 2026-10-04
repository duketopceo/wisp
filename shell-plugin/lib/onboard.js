.pragma library

// First-run card model (W28): turns `wispd onboard --status --json` into
// card rows and builds the argv for each card action. Pure functions, no
// strings shown to users. Skipped steps live in the Panel only (a skip
// writes nothing); the daemon records only steps that passed.

// the one step whose action has a side effect and needs --yes
var CONFIRM = "notifications"

// `wispd ... --json` stdout (envelope or bare data) -> data or null
function parse(stdout) {
  var o
  try { o = JSON.parse(stdout) } catch (e) { return null }
  if (o && o.data && o.data.steps) return o.data
  if (o && o.steps) return o
  return null
}

// state: done | skipped | na | todo
function rows(steps, skipped) {
  var skip = skipped || []
  return (steps || []).map(function (s) {
    var state = s.state === "done" ? "done"
      : s.state === "na" ? "na"
      : skip.indexOf(s.id) >= 0 ? "skipped" : "todo"
    return { id: s.id, name: s.name || s.id, optional: !!s.optional,
             state: state, detail: s.detail || "", tryText: s.try || "" }
  })
}

// { done, total } over the steps that can be done here (na excluded)
function counts(rowList) {
  var done = 0, total = 0
  for (var i = 0; i < rowList.length; i++) {
    if (rowList[i].state === "na") continue
    total += 1
    if (rowList[i].state === "done") done += 1
  }
  return { done: done, total: total }
}

// which actions a state allows: a todo step can be checked or skipped, a
// skipped one checked again, a done one undone, a na one nothing
function actions(state) {
  return { run: state === "todo" || state === "skipped",
           skip: state === "todo", undo: state === "done" }
}

// the card shows until the daemon says finished
function visible(data) { return data !== null && data !== undefined && !data.finished }

function statusCommand(wispd) { return [wispd, "onboard", "--status", "--json"] }

function stepCommand(wispd, id) {
  var c = [wispd, "onboard", "--step", id, "--json"]
  if (id === CONFIRM) c.push("--yes")
  return c
}

function undoCommand(wispd, id) { return [wispd, "onboard", "--undo", id, "--json"] }

function finishCommand(wispd) { return [wispd, "onboard", "--finish", "--json"] }
