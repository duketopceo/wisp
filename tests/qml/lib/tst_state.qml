import QtQuick
import QtTest
import "../../../shell-plugin/lib/state.js" as S

// Mirrors tests/test_state_reader.py on the same state.js the QML service
// imports, so the reducer is checked in the QML engine as well as in node.
TestCase {
  name: "state"

  function snap(o) {
    var b = { status: "idle", seq: 1, turn_id: "t1", contract_version: 2,
              started_at: "2026-10-04T10:00:00Z" }
    for (var k in o) b[k] = o[k]
    return b
  }

  function entry(i, extra) {
    var e = { id: "a" + i, kind: "tool", label: "tool" + i,
              status: "done", target: "", reason: "", undo_ref: null,
              at: "2026-10-10T01:00:00Z" }
    for (var k in (extra || {})) e[k] = extra[k]
    return e
  }

  function test_initial_offline() {
    var v = S.initial()
    compare(v.status, "offline")
    compare(v.connection, "none")
    verify(v.seq === null)
  }

  function test_snapshot_fields_and_defaults() {
    var r = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: ["yes", "no"], prompt_id: "p1", goal: { text: "g", status: "open" } }), 100, "file")
    compare(r.view.status, "awaiting_choice")
    compare(r.view.promptId, "p1")
    compare(r.view.goal, "g")
    compare(r.view.connection, "file")
    var legacy = S.applySnapshot(S.initial(), { status: "done" }, 1, "file").view
    compare(legacy.contractVersion, 1)
    verify(legacy.seq === null)
  }

  function test_unknown_status_and_code() {
    var v = S.applySnapshot(S.initial(), snap({ status: "zzz" }), 1, "file").view
    compare(v.status, "idle")
    v = S.applySnapshot(S.initial(), snap({ status: "error", error_code: "zzz" }), 1, "file").view
    compare(v.errorCode, "internal")
  }

  function test_diff_gap_and_dup() {
    var v = S.applySnapshot(S.initial(), snap({ seq: 5 }), 1, "stream").view
    var ok = S.applyEvent(v, { type: "state", seq: 6, diff: { status: "deciding", seq: 6 } }, 2)
    compare(ok.view.status, "deciding")
    compare(ok.view.seq, 6)
    var gap = S.applyEvent(v, { type: "state", seq: 9, diff: { status: "acting", seq: 9 } }, 2)
    verify(gap.resync)
    compare(gap.view.status, "idle")
    var dup = S.applyEvent(v, { type: "state", seq: 5, diff: { status: "acting", seq: 5 } }, 2)
    verify(!dup.ok)
  }

  function test_hello_refused_and_ping() {
    var v = S.initial()
    var r = S.applyMessage(v, '{"type":"hello","ok":false,"error":"x"}', 1, "stream")
    verify(r.refused)
    r = S.applyMessage(v, '{"type":"ping"}', 7, "stream")
    verify(r.ok)
    compare(r.view.lastMessageMs, 7)
    r = S.applyMessage(v, "{nope", 1, "stream")
    verify(!r.ok)
    compare(r.view.parseErrors, 1)
  }

  function test_stale_after_default_window() {
    var v = S.applySnapshot(S.initial(), snap({ status: "acting" }), 10000, "file").view
    verify(!S.isStale(v, 29900))
    verify(S.isStale(v, 30001))
    var idle = S.applySnapshot(S.initial(), snap({ status: "idle" }), 0, "file").view
    verify(!S.isStale(idle, 999999))
  }

  function test_backoff() {
    compare(S.backoffMs(0), 500)
    compare(S.backoffMs(3), 4000)
    compare(S.backoffMs(20), 15000)
    compare(S.backoffMs(-1), 500)
  }

  function test_subscribe_request() {
    var q = S.subscribeRequest()
    compare(q.cmd, "subscribe")
    compare(q.topics.length, 4)
  }

  function test_cua_target_event() {
    var v = S.applySnapshot(S.initial(), snap({ status: "acting", seq: 2 }), 1, "stream").view
    compare(v.cuaTarget, null)
    var ev = { type: "event", name: "cua.target", data: { x: 640, y: 360, window: "Settings", label: "night light", confidence: 0.9 } }
    var r = S.applyEvent(v, ev, 2)
    compare(r.view.cuaTarget.x, 640)
    compare(r.view.cuaTarget.phase, "aim")
    compare(r.view.seq, 2)
    var bad = S.applyEvent(r.view, { type: "event", name: "cua.target", data: { x: "5", y: 2 } }, 3)
    verify(!bad.ok)
    compare(bad.view.cuaTarget.x, 640)
    var clear = S.applyEvent(r.view, { type: "event", name: "cua.target", data: { x: null, y: null } }, 3)
    compare(clear.view.cuaTarget, null)
    var done = S.applyEvent(r.view, { type: "state", seq: 3, diff: { status: "done", seq: 3 } }, 3)
    compare(done.view.cuaTarget, null)
    compare(S.applyEvent(S.initial(), ev, 2).view.cuaTarget, null)
  }

  function test_actions_normalize_cap_and_diff() {
    // absent -> empty; the stream rides the same snapshot+diff path
    var v = S.applySnapshot(S.initial(), snap({}), 1, "file").view
    compare(v.actions.length, 0)
    var a = entry(1, { status: "in_flight", target: "640,360",
                       prompt_id: "p1", options: ["yes", "no"] })
    v = S.applySnapshot(S.initial(), snap({ actions: [a] }), 1, "file").view
    compare(v.actions[0].id, "a1")
    compare(v.actions[0].status, "in_flight")
    compare(v.actions[0].promptId, "p1")
    compare(v.actions[0].options.length, 2)
    // unknown status reads done; junk drops; cap keeps the last 50
    v = S.applySnapshot(S.initial(), snap({ actions:
      [entry(1, { status: "weird" }), "junk", null, entry(2)] }), 1, "file").view
    compare(v.actions.length, 2)
    compare(v.actions[0].status, "done")
    var many = []
    for (var i = 1; i <= 61; i++) many.push(entry(i))
    v = S.applySnapshot(S.initial(), snap({ actions: many }), 1, "file").view
    compare(v.actions.length, 50)
    compare(v.actions[0].id, "a12")
    compare(v.actions[49].id, "a61")
    // a diff replaces the stream wholesale
    v = S.applySnapshot(S.initial(), snap({ seq: 5,
      actions: [entry(1)] }), 1, "stream").view
    var r = S.applyEvent(v, { type: "state", seq: 6,
      diff: { seq: 6, actions: [entry(1), entry(2, { status: "awaiting" })] } }, 2)
    compare(r.view.actions.length, 2)
    compare(r.view.actions[1].status, "awaiting")
  }

  function test_confirm_demotes_from_the_stream() {
    // v2: the card IS an awaiting stream entry — options + prompt id
    // come from the entry; the legacy confirm object only adds timeout
    var conf = entry(1, { kind: "confirm", status: "awaiting",
      label: "run close: w1?", prompt_id: "p7",
      options: ["run close: w1? — yes", "no"] })
    var v = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      prompt_id: "p7", actions: [conf] }), 1, "file").view
    compare(v.confirm.promptId, "p7")
    compare(v.confirm.prompt, "run close: w1?")
    compare(v.confirm.allow, "run close: w1? — yes")
    compare(v.confirm.deny, "no")
    // a stale awaiting entry (prompt already over, or another live)
    // can't park a dead card
    v = S.applySnapshot(S.initial(), snap({ status: "acting",
      prompt_id: "", actions: [conf] }), 1, "file").view
    verify(v.confirm === null)
    v = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      prompt_id: "p8", actions: [conf] }), 1, "file").view
    verify(v.confirm === null)
    // other awaiting kinds never demote to the card
    var sug = entry(2, { kind: "suggestion", status: "awaiting",
      prompt_id: "p7", options: ["a", "b"] })
    v = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      prompt_id: "p7", actions: [sug] }), 1, "file").view
    verify(v.confirm === null)
    // resolved confirm entry -> back to the legacy field (none here)
    var done = entry(1, { kind: "confirm", status: "cancelled",
      prompt_id: "p7" })
    v = S.applySnapshot(S.initial(), snap({ status: "acting",
      actions: [done] }), 1, "file").view
    verify(v.confirm === null)
    // legacy fallback still works when no entry carries the card
    v = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: ["y", "n"], prompt_id: "p9",
      confirm: { prompt_id: "p9", prompt: "run?", timeout_s: 30 } }), 1, "file").view
    compare(v.confirm.prompt, "run?")
    compare(v.confirm.timeoutS, 30)
  }

  function test_confirm_snapshots_offered_picks() {
    // the card carries its own allow/deny — a later diff emptying
    // `choices` must not change what a pending click sends
    var r = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: ["yes", "no"], prompt_id: "p7",
      confirm: { prompt_id: "p7", prompt: "run?", timeout_s: 120 } }), 1, "file")
    compare(r.view.confirm.allow, "yes")
    compare(r.view.confirm.deny, "no")
    var gone = S.applyEvent(r.view, { type: "state", seq: 2,
      diff: { choices: [], seq: 2 } }, 2)
    compare(gone.view.confirm.allow, "yes")
    compare(gone.view.confirm.deny, "no")
  }

  function test_accept_choice_normal_and_suggestion() {
    var SUG = ["suggestion:automate", "suggestion:not now", "suggestion:never"]
    // a normal pick: the shown prompt id plus an offered choice
    var waiting = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: ["yes", "no"], prompt_id: "p7" }), 1, "file").view
    verify(S.acceptChoice(waiting, "no", "p7"))
    verify(!S.acceptChoice(waiting, "no", "p6"))   // another prompt
    verify(!S.acceptChoice(waiting, "no", ""))     // no id
    verify(!S.acceptChoice(waiting, "later", "p7"))// not offered
    // suggestion picks carry no prompt id: a bare pick passes only while
    // the card is live and offers it
    var sug = S.applySnapshot(S.initial(), snap({ status: "suggestion",
      choices: SUG }), 1, "file").view
    verify(S.acceptChoice(sug, "suggestion:automate", ""))
    verify(!S.acceptChoice(sug, "suggestion:later", ""))
    verify(!S.acceptChoice(waiting, "suggestion:automate", ""))
    // a keyed pick addresses a suggestions.jsonl row — safe to pass at
    // any time (a stale key ends in a SKIP server-side)
    var idle = S.applySnapshot(S.initial(), snap({}), 1, "file").view
    verify(S.acceptChoice(idle, "suggestion:automate:abc123", ""))
    verify(S.acceptChoice(idle, "suggestion:never:zz", ""))
    // malformed picks still drop
    verify(!S.acceptChoice(idle, "suggestion:", ""))
    verify(!S.acceptChoice(idle, "suggestion:automate:", ""))
    verify(!S.acceptChoice(idle, "", ""))
    verify(!S.acceptChoice(null, "x", ""))
    verify(!S.acceptChoice(idle, 3, ""))
  }

  function test_accept_choice_free_text_questions() {
    // a live question card with no offered picks accepts ANY non-empty
    // pick — the typed or spoken answer goes through verbatim (U8)
    var q = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: [], prompt_id: "p9",
      confirm: { prompt_id: "p9", prompt: "which file?",
                 timeout_s: 60, kind: "question" } }), 1, "file").view
    verify(S.acceptChoice(q, "the second one", "p9"))
    verify(!S.acceptChoice(q, "arbitrary", "p8"))   // another prompt's id
    verify(!S.acceptChoice(q, "", "p9"))            // empty stays refused
    // the awaiting question stream entry alone (no confirm block) is
    // enough — the card may derive from the stream only
    var qe = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: [], prompt_id: "p9",
      actions: [entry(1, { kind: "question", status: "awaiting",
                           prompt_id: "p9" })] }), 1, "file").view
    verify(S.acceptChoice(qe, "free text", "p9"))
    // but a normal confirm card whose choices list emptied is NOT
    // free-text — the prompt kind gate keeps it option-only
    var c = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: [], prompt_id: "p9",
      confirm: { prompt_id: "p9", prompt: "run?", timeout_s: 60 } }),
      1, "file").view
    verify(!S.acceptChoice(c, "arbitrary", "p9"))
    // and a question that DID offer picks takes only those picks
    var qp = S.applySnapshot(S.initial(), snap({ status: "awaiting_choice",
      choices: ["work", "personal"], prompt_id: "p9",
      confirm: { prompt_id: "p9", prompt: "which account?",
                 timeout_s: 60, kind: "question" } }), 1, "file").view
    verify(S.acceptChoice(qp, "work", "p9"))
    verify(!S.acceptChoice(qp, "unlisted", "p9"))
  }

  function test_action_result_never_silent() {
    // --json envelope success: the daemon's words land in text
    var ok = S.actionResult(0,
      '{"ok":true,"data":{"result":"labeled correct: t1"}}', "")
    verify(ok.ok)
    compare(ok.text, "labeled correct: t1")
    // --json envelope typed refusal
    var stale = S.actionResult(1,
      '{"ok":false,"error":{"code":"E_STALE_PROMPT","message":"That prompt expired."}}', "")
    verify(!stale.ok)
    compare(stale.error, "stale_prompt")
    compare(stale.text, "That prompt expired.")
    // raw daemon error line
    var raw = S.actionResult(1, '{"ok":false,"error":"stale_prompt"}', "")
    compare(raw.error, "stale_prompt")
    // E_-coded human-mode stderr
    var busy = S.actionResult(1, "",
      "E_BUSY: Busy with another request.\nTry: wispd interrupt")
    verify(!busy.ok)
    compare(busy.error, "busy")
    compare(busy.text, "Busy with another request.")
    // nonzero exit without parseable output still reports
    compare(S.actionResult(3, "", "spawn blew up").text, "spawn blew up")
    compare(S.actionResult(3, "", "").text, "exit 3")
    // success without JSON still surfaces stdout's first line
    var line = S.actionResult(0, "labeled correct: t1\n", "")
    verify(line.ok)
    compare(line.text, "labeled correct: t1")
  }
}
