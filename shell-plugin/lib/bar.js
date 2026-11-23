.pragma library
.import "status.js" as Status

// Bar mark rules (Ember U10): which action a mouse button maps to, the
// tooltip lines, and the glyph state. Pure: words and glyphs come from the
// status table (lib/status.js), the caller passes service.ui, no colors, no
// timers. Runs under qmltestrunner and node.

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

// "today $0.12 · 4 turns" from state.spend ({today_usd, turns_today});
// "" when the daemon publishes no spend. The turn count is left off when the
// daemon does not publish one, never guessed.
function spendLine(spend, ui) {
  if (!isObj(spend)) return ""
  var today = money(spend.today_usd)
  if (today === "") return ""
  var line = ui("ui.bar.spend") + " " + today
  var n = Number(spend.turns_today)
  if (spend.turns_today !== undefined && spend.turns_today !== null && isFinite(n) && n >= 0) {
    n = Math.floor(n)
    line += " \u00b7 " + n + " " + ui(n === 1 ? "ui.bar.turn" : "ui.bar.turns")
  }
  return line
}

// Hover card lines. o: {word, hint, notice, stale, offline, voice, ui}.
// `word` is the service's wordView word (reconnecting while stale, the typed
// message on an error) and `hint` the error's next step, both from the copy
// table. Spend lives here and only here (never on the pill). `voice` is the
// voice in use when the caller knows it; the line is left out otherwise.
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
    if (o.voice) lines.push(ui("ui.bar.voice") + " " + o.voice)
  }
  lines.push(ui(o.offline ? "ui.bar.hint.offline" : "ui.bar.hint"))
  return lines
}

// Mark dimming: offline and stale read as muted, never as live.
// the open-mic mark: up for as long as the daemon says the wake word listens
function micOpen(mic, offline) { return mic === "open" && !offline }

function dimmed(offline, stale) { return !!offline || !!stale }

// A badge dot for a pending suggestion. A pending choice already has its
// own glyph (bar-needs-you), so it gets no dot on top of it.
function badge(status, hasSuggestion) {
  return status === "suggestion" || !!hasSuggestion
}

// ---- pill (U3) ------------------------------------------------------

// The done rating window: how long the pill keeps the thumbs up.
var WINDOW_MS = 8000

// Statuses a turn passes through; a done reached from one of these is a
// turn finishing now (a snapshot of an old done after a reconnect is not).
var LIVE = { listening: true, transcribing: true, deciding: true,
  acting: true, speaking: true, awaiting_choice: true }

// What the service does to the window on a state message: "open" on the
// done edge of a rateable turn, "close" when the turn moved on, the daemon
// went offline or the status left done, else "keep".
// A turn the daemon marked cancelled (errorCode) never holds a window.
function windowAction(prevStatus, status, prevTurn, turn, offline, rateable, errorCode) {
  if (offline || status !== "done" || errorCode === "cancelled") return "close"
  if (prevStatus !== "done" && LIVE[prevStatus] === true && rateable) return "open"
  if (turn !== prevTurn) return "close"
  return "keep"
}

function causeWord(code) { return Status.causeWord(code) }

var HIDDEN = { kind: "idle", visible: false, glyph: "", token: "ink",
  wordToken: "ink", border: "keyline", wordKey: "", step: "", cause: "",
  thumbs: false, dev: false }

function view(kind, glyph, token, wordKey, extra) {
  var v = { kind: kind, visible: true, glyph: glyph, token: token,
    wordToken: "ink", border: "keyline", wordKey: wordKey, step: "",
    cause: "", thumbs: false, dev: false }
  for (var k in extra) v[k] = extra[k]
  return v
}

// Daemon status to the pill's state. o: {status, result, errorCode,
// offline, confirm, windowOpen, rateable, dev, run:{steps, stepAt}}. The
// status table (lib/status.js) decides: a row with no pill (idle, offline,
// suggestion) is no pill, the mark alone; every other state is glyph plus
// the row's short word (the word repeats the state, color is never the only
// signal). The done row shows only while the rating window is open.
// While the dev session is on (o.dev) every state also carries `dev`, a
// small badge so the mode is never on by accident, and idle shows that
// badge alone. Offline never does: the daemon's session state is unknown.
function pillState(o) {
  var v = _pillState(o)
  if (o.dev !== true || v.kind === "offline") return v
  var out = {}
  for (var k in v) out[k] = v[k]
  out.dev = true
  out.visible = true
  return out
}

function _pillState(o) {
  var key = Status.rowKey(o)
  if (key === "offline") {
    var off = view("offline", "", "inkMuted", "", {})
    off.visible = false
    return off
  }
  if (key === "") return HIDDEN
  var r = Status.ROWS[key], p = r.pill
  if (p === null) return HIDDEN
  if (p.when === "rated" && !(o.windowOpen === true && o.rateable === true)) return HIDDEN
  var extra = { border: p.border, wordToken: p.word_token }
  if (key === "error") extra.cause = causeWord(String(o.errorCode || ""))
  if (key === "acting") {
    var run = o.run, step = ""
    if (run && Number(run.steps) > 0 && Number(run.stepAt) > 0)
      step = Math.min(Number(run.stepAt), Number(run.steps)) + "/" + Number(run.steps)
    extra.step = step
  }
  if (p.when === "rated") extra.thumbs = true
  return view(p.kind, p.glyph, p.token, r.short, extra)
}

// Five mic bars, heights in px, from the mic level (0 to 1). The middle
// bar moves most; a silent mic still shows a short stub.
var WAVE_WEIGHT = [0.45, 0.75, 1, 0.75, 0.45]
function waveBars(level) {
  var l = Number(level)
  if (!isFinite(l)) l = 0
  l = Math.max(0, Math.min(1, l))
  var out = []
  for (var i = 0; i < WAVE_WEIGHT.length; i++)
    out.push(3 + Math.round(9 * WAVE_WEIGHT[i] * l))
  return out
}
