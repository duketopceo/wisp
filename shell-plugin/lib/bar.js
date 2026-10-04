.pragma library

// Bar mark rules (Ember U10): which action a mouse button maps to, the
// tooltip lines, and the glyph state. Pure: no copy table import (the
// caller passes service.ui), no colors, no timers. Runs under
// qmltestrunner and node.

// Qt.LeftButton, Qt.RightButton, Qt.MiddleButton
var LEFT = 1, RIGHT = 2, MIDDLE = 4

// left: toggle listening (wispd trigger, empty phase toggles), or start
// the daemon while offline; middle:
// stop the turn in flight (wispd interrupt, the daemon keeps running);
// right: open the Panel. Anything else does nothing.
function actionFor(button, offline) {
  if (button === LEFT) return offline ? "start" : "talk"
  if (button === MIDDLE) return "stop"
  if (button === RIGHT) return "panel"
  return ""
}

var MAX_ROWS = 6

function isObj(x) { return x !== null && typeof x === "object" && !Array.isArray(x) }

// Health rows from state.health, down first then ok, each sorted by name.
// An entry that is not an object, or has no boolean-ish ok, is skipped, so
// a registry row the reader does not know (or a missing cua row) never
// breaks the tooltip.
function healthRows(health) {
  var down = [], up = []
  if (!isObj(health)) return []
  var names = Object.keys(health).sort()
  for (var i = 0; i < names.length; i++) {
    var e = health[names[i]]
    if (!isObj(e) || e.ok === undefined || e.ok === null) continue
    var row = { name: names[i], ok: !!e.ok,
      code: typeof e.code === "string" ? e.code : "" }
    if (row.ok) up.push(row); else down.push(row)
  }
  return down.concat(up)
}

function money(x) {
  var n = Number(x)
  if (!isFinite(n) || n < 0) return ""
  return "$" + n.toFixed(2)
}

// "spent today $0.12 of $5.00" pieces from state.spend when the daemon
// publishes it ({today_usd, cap_usd}); "" when absent (this contract
// version does not carry spend yet, W14 adds it).
function spendLine(spend, ui) {
  if (!isObj(spend)) return ""
  var today = money(spend.today_usd)
  if (today === "") return ""
  var cap = money(spend.cap_usd)
  return ui("ui.bar.spend") + " " + today + (cap !== "" ? " / " + cap : "")
}

// Tooltip lines. o: {word, hint, notice, stale, offline, ui}. `word` is the
// service's wordView word (reconnecting while stale, the typed message on
// an error) and `hint` the error's next step, both from the copy table.
// Offline shows the notice and the start action only; stale keeps the rows
// and says so.
function tooltipLines(view, o) {
  var ui = o.ui
  var lines = ["wisp: " + o.word]
  if (o.notice) lines.push(o.notice)
  if (o.hint && !o.offline) lines.push(o.hint)
  if (!o.offline) {
    var rows = healthRows(view.health)
    var shown = Math.min(rows.length, MAX_ROWS)
    for (var i = 0; i < shown; i++) {
      var r = rows[i]
      lines.push(r.name + " " + (r.ok ? ui("ui.bar.ok")
        : ui("ui.bar.down") + (r.code ? " (" + r.code + ")" : "")))
    }
    if (rows.length > shown) lines.push("+" + (rows.length - shown) + " " + ui("ui.more"))
    var sp = spendLine(view.raw ? view.raw.spend : null, ui)
    if (sp) lines.push(sp)
  }
  lines.push(ui(o.offline ? "ui.bar.hint.offline" : "ui.bar.hint"))
  return lines
}

// Mark dimming: offline and stale read as muted, never as live.
function dimmed(offline, stale) { return !!offline || !!stale }

// A badge dot for a pending suggestion. A pending choice already has its
// own glyph (bar-needs-you), so it gets no dot on top of it.
function badge(status, hasSuggestion) {
  return status === "suggestion" || !!hasSuggestion
}
