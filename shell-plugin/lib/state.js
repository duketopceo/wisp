.pragma library

// Pure reducer behind WispService.qml: wispd state contract
// (docs/IPC_CONTRACT.md) in, one normalized view out. No Quickshell
// imports, so it runs under qmltestrunner and node
// (tests/test_state_reader.py). Every apply* returns
// { view, ok, resync, refused }: ok=false means the input changed nothing
// (bad JSON, duplicate, old); resync=true means take a fresh snapshot;
// refused=true means the server declined the subscription (use the file).

// Highest contract_version this reader understands; a newer daemon is
// still read (additive fields) but flagged contractNewer.
var CONTRACT_VERSION = 1
var STALE_AFTER_MS = 20000  // above the W3 bus heartbeat (15 s) so long turns never flag stale between beats
var STATUSES = ["idle", "listening", "transcribing", "deciding",
  "awaiting_choice", "acting", "speaking", "suggestion", "done", "error"]
// statuses in which the daemon is working and must keep writing
var BUSY = ["transcribing", "deciding", "acting"]
var ERROR_CODES = ["jev_down", "brain_down", "stt_down", "ground_down",
  "ground_failed", "timeout", "cancelled", "busy", "stale_prompt",
  "restarted", "tool_failed", "budget_exceeded", "internal"]
var TOPICS = ["state", "health", "tasks", "events"]
var CUA_PHASES = ["aim", "click", "done"]
var META_KEYS = ["seq", "updated_at", "turn_id"]

function subscribeRequest() { return { cmd: "subscribe", topics: TOPICS } }

// Reconnect delay for attempt n (0 based): 500 ms doubling, capped 15 s.
function backoffMs(attempt) {
  var n = Number(attempt)
  if (!isFinite(n) || n < 0) n = 0
  return Math.min(15000, 500 * Math.pow(2, Math.floor(n)))
}

function initial() {
  return {
    status: "offline", rawStatus: "offline", transcript: "", answer: "",
    result: "", choices: [], promptId: "", confirm: null, points: [], steps: [],
    suggestion: null, guide: null, focus: {}, goal: "", goalStatus: "",
    level: 0, tasks: {}, error: "", errorCode: "", health: {},
    startedAt: "", turnId: "", seq: null, contractVersion: 1,
    updatedAt: "", heartbeatAt: "",
    connection: "none", offline: true, stale: false, contractNewer: false,
    cuaTarget: null,
    changedAtMs: 0, lastMessageMs: 0, parseErrors: 0, raw: {}
  }
}

function isObj(x) { return x !== null && typeof x === "object" && !Array.isArray(x) }
function str(x) { return typeof x === "string" ? x : "" }
function arr(x) { return Array.isArray(x) ? x : [] }

// state.confirm (additive, W25): {prompt_id, prompt, timeout_s} while a
// confirm waits. Anything without a prompt id is not a card.
function normalizeConfirm(c) {
  if (!isObj(c) || !str(c.prompt_id)) return null
  var t = Number(c.timeout_s)
  return { promptId: str(c.prompt_id), prompt: str(c.prompt),
    timeoutS: isFinite(t) && t > 0 ? t : 0 }
}

// UI-side prompt id guard: a reply goes to the daemon only when it names
// the prompt the view currently shows and picks one of its choices. A
// click on a card that has already been answered, timed out or replaced
// is dropped here (the daemon refuses it too: stale_prompt).
function acceptChoice(view, pick, promptId) {
  if (!view || !promptId || view.promptId !== promptId) return false
  if (view.status !== "awaiting_choice") return false
  return view.choices.indexOf(pick) >= 0
}

// Raw snapshot object -> view fields (defaults, clamps, closed sets).
function normalize(raw) {
  var st = str(raw.status) || "idle"
  var status = STATUSES.indexOf(st) >= 0 ? st : "idle"
  var code = str(raw.error_code)
  if (code && ERROR_CODES.indexOf(code) < 0) code = "internal"
  var goal = raw.goal, goalText = "", goalStatus = ""
  if (typeof goal === "string") goalText = goal
  else if (isObj(goal)) { goalText = str(goal.text); goalStatus = str(goal.status) }
  var lv = Number(raw.level)
  if (!isFinite(lv)) lv = 0
  var seq = Number(raw.seq)
  var cv = Number(raw.contract_version)
  if (!isFinite(cv) || cv < 1) cv = 1
  var choices = arr(raw.choices).filter(function (c) { return typeof c === "string" })
  var confirm = normalizeConfirm(raw.confirm)
  return {
    status: status, rawStatus: st, transcript: str(raw.transcript),
    answer: str(raw.answer), result: str(raw.result), choices: choices,
    promptId: str(raw.prompt_id), confirm: confirm, points: arr(raw.points),
    steps: arr(raw.steps), suggestion: isObj(raw.suggestion) ? raw.suggestion : null,
    guide: isObj(raw.guide) ? raw.guide : null,
    focus: isObj(raw.focus) ? raw.focus : {},
    goal: goalText, goalStatus: goalStatus, level: Math.max(0, Math.min(1, lv)),
    tasks: isObj(raw.tasks) ? raw.tasks : {}, error: str(raw.error),
    errorCode: code, health: isObj(raw.health) ? raw.health : {},
    startedAt: str(raw.started_at), turnId: str(raw.turn_id),
    seq: raw.seq === undefined || raw.seq === null || !isFinite(seq) ? null : seq,
    contractVersion: cv, updatedAt: str(raw.updated_at),
    heartbeatAt: str(raw.heartbeat_at)
  }
}

// cua.target stream event (docs/IPC_CONTRACT.md "cua.target"): data is
// {x, y, window, label, confidence, phase}. x and y are screen pixels
// (finite numbers), window and label strings, confidence 0..1, phase one
// of CUA_PHASES (default "aim"). Returns the normalized target, null for
// the explicit clear (x and y both null), or undefined when malformed
// (the event is ignored and the current target stays).
function normalizeTarget(d) {
  if (!isObj(d)) return undefined
  if (d.x === null && d.y === null) return null
  if (typeof d.x !== "number" || typeof d.y !== "number") return undefined
  var x = d.x, y = d.y
  if (!isFinite(x) || !isFinite(y)) return undefined
  var c = Number(d.confidence)
  var phase = CUA_PHASES.indexOf(d.phase) >= 0 ? d.phase : "aim"
  return { x: x, y: y, window: str(d.window), label: str(d.label),
    confidence: isFinite(c) ? Math.max(0, Math.min(1, c)) : 1, phase: phase }
}

// Statuses in which a target may be shown; anything else drops it.
var TARGET_STATUSES = ["acting", "deciding", "awaiting_choice"]

function copy(o) { var r = {}; for (var k in o) r[k] = o[k]; return r }

function build(prev, raw, source, nowMs, changed) {
  var v = copy(prev)
  var n = normalize(raw)
  for (var k in n) v[k] = n[k]
  v.raw = raw
  v.connection = source
  v.offline = false
  if (v.cuaTarget && (TARGET_STATUSES.indexOf(v.status) < 0 || n.turnId !== prev.turnId))
    v.cuaTarget = null
  v.contractNewer = v.contractVersion > CONTRACT_VERSION
  v.lastMessageMs = nowMs
  if (changed) v.changedAtMs = nowMs
  return v
}

function result(view, ok, resync, refused) {
  return { view: view, ok: ok, resync: !!resync, refused: !!refused }
}

// Full snapshot (state.json, status reply, or stream snapshot).
function applySnapshot(view, snap, nowMs, source) {
  if (!isObj(snap)) return result(view, false)
  var n = normalize(snap)
  if (view.seq !== null && n.seq !== null && !view.offline) {
    var sameDaemon = !n.startedAt || !view.startedAt || n.startedAt === view.startedAt
    if (sameDaemon && n.seq < view.seq) return result(view, false)
    if (sameDaemon && n.seq === view.seq) {
      var v0 = copy(view)
      v0.lastMessageMs = nowMs
      v0.connection = source
      return result(v0, true)
    }
  }
  return result(build(view, snap, source, nowMs, true), true)
}

// Stream event: {type:"state", seq, diff} or {type:"event", name, data}.
function applyEvent(view, ev, nowMs) {
  if (!isObj(ev)) return result(view, false)
  if (ev.type === "state") {
    var diff = ev.diff
    var seq = Number(ev.seq !== undefined ? ev.seq : (diff && diff.seq))
    if (!isObj(diff) || !isFinite(seq)) return result(view, false)
    if (view.seq === null || view.offline) return result(view, false, true)
    if (seq <= view.seq) return result(view, false)
    if (seq !== view.seq + 1) return result(view, false, true)
    var raw = copy(view.raw)
    for (var k in diff) raw[k] = diff[k]
    raw.seq = seq
    return result(build(view, raw, view.connection === "none" ? "stream" : view.connection, nowMs, true), true)
  }
  if (ev.type === "event") {
    var v = copy(view)
    v.lastMessageMs = nowMs
    if (ev.name === "overflow") return result(v, true, true)
    if (ev.name === "cua.target") {
      if (v.offline) return result(v, true)
      var t = normalizeTarget(ev.data)
      if (t === undefined) return result(v, false)
      if (t && TARGET_STATUSES.indexOf(v.status) < 0) t = null
      v.cuaTarget = t
      v.changedAtMs = nowMs
      return result(v, true)
    }
    if (ev.name === "health_changed" && isObj(ev.data) && ev.data.name) {
      var h = copy(v.health)
      var prev = isObj(h[ev.data.name]) ? h[ev.data.name] : {}
      var e = copy(prev)
      e.ok = !!ev.data.ok
      e.code = ev.data.code === undefined ? null : ev.data.code
      h[ev.data.name] = e
      v.health = h
      v.raw = copy(v.raw)
      v.raw.health = h
      v.changedAtMs = nowMs
    }
    return result(v, true)
  }
  return result(view, false)
}

// One newline-delimited message from the daemon (stream line, status
// reply, or a bare state object).
function applyMessage(view, text, nowMs, source) {
  var t = String(text || "").replace(/^\s+|\s+$/g, "")
  if (!t) return result(view, false)
  var m
  try { m = JSON.parse(t) } catch (e) {
    var bad = copy(view)
    bad.parseErrors = view.parseErrors + 1
    return result(bad, false)
  }
  if (!isObj(m)) return result(view, false)
  if (m.type === "hello") {
    if (m.ok === false) return result(markOffline(view, nowMs), false, false, true)
    var h = copy(view)
    h.connection = "stream"
    h.lastMessageMs = nowMs
    var cv = Number(m.contract_version)
    if (isFinite(cv) && cv > CONTRACT_VERSION) h.contractNewer = true
    return result(h, true)
  }
  if (m.type === "ping") {
    var p = copy(view)
    p.lastMessageMs = nowMs
    return result(p, true)
  }
  if (m.type === "snapshot") return applySnapshot(view, m.state, nowMs, source)
  if (m.type === "state" || m.type === "event") return applyEvent(view, m, nowMs)
  if (m.ok === false) return result(view, false, false, true)
  if (isObj(m.state)) return applySnapshot(view, m.state, nowMs, source)
  if (m.status !== undefined) return applySnapshot(view, m, nowMs, source)
  return result(view, false)
}

// Daemon gone or file unreadable: keep the last content, read offline.
function markOffline(view, nowMs) {
  var v = copy(view)
  v.status = "offline"
  v.rawStatus = "offline"
  v.cuaTarget = null
  v.offline = true
  v.connection = "none"
  v.lastMessageMs = nowMs || view.lastMessageMs
  return v
}

// Stream dropped but the daemon may be fine (resync, overflow, restart):
// keep status and content, let the file fallback or a new subscription
// supply the next snapshot.
function markDisconnected(view) {
  var v = copy(view)
  v.connection = "none"
  return v
}

// A busy turn whose snapshot has not changed for afterMs. Heartbeats
// (heartbeat_at) and any state diff count as change; pings do not.
function isStale(view, nowMs, afterMs) {
  if (view.offline) return false
  if (BUSY.indexOf(view.status) < 0) return false
  var limit = afterMs === undefined ? STALE_AFTER_MS : afterMs
  return nowMs - view.changedAtMs > limit
}
