import QtQuick
import QtTest
import "../../../shell-plugin/lib/state.js" as S

// Mirrors tests/test_state_reader.py on the same state.js the QML service
// imports, so the reducer is checked in the QML engine as well as in node.
TestCase {
  name: "state"

  function snap(o) {
    var b = { status: "idle", seq: 1, turn_id: "t1", contract_version: 1,
              started_at: "2026-10-04T10:00:00Z" }
    for (var k in o) b[k] = o[k]
    return b
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

  function test_stale_after_five_seconds() {
    var v = S.applySnapshot(S.initial(), snap({ status: "acting" }), 10000, "file").view
    verify(!S.isStale(v, 14900))
    verify(S.isStale(v, 15001))
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
}
