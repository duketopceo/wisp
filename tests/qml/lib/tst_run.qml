import QtQuick
import QtTest
import "../../../shell-plugin/lib/run.js" as R
import "../../../shell-plugin/lib/tokens.js" as Tokens
import "../../../shell-plugin/components"
import "../harness"

// U8 run-card model (lib/run.js): the card reduces the action stream to
// intent / step cursor / in-flight step / outcome / mutations / live
// question. Settled or stale daemons can never leave a ghost "running"
// card. (The bar pill's own tests are tst_bar_pill.qml.)
TestCase {
  id: tc
  name: "run"
  when: windowShown
  width: 420
  height: 240

  FixtureService { id: svc }
  property var tokens: Tokens.load("", "", "dark").tokens

  function ent(i, extra) {
    var e = { id: "a" + i, kind: "tool", label: "tool" + i,
              status: "done", target: "", reason: "", undoRef: null,
              at: "2026-10-10T01:00:00Z" }
    for (var k in (extra || {})) e[k] = extra[k]
    return e
  }

  function boundary(extra) {
    var b = { id: "a1", kind: "route", label: "act", status: "in_flight",
              target: "open discord and message sam", reason: "",
              undoRef: null, at: "2026-10-10T01:00:00Z" }
    for (var k in (extra || {})) b[k] = extra[k]
    return b
  }

  function readJson(name) {
    var x = new XMLHttpRequest();
    x.open("GET", Qt.resolvedUrl("../../fixtures/states/" + name + ".json"), false);
    x.send();
    return JSON.parse(x.responseText);
  }

  function test_no_stream_no_run() {
    verify(!R.card([], "acting", "", false, "task", 0).present)
    // a tail of pure chatter entries is not a run either
    verify(!R.card([ent(1, { kind: "label" }),
                    ent(2, { kind: "suggestion" })],
                   "acting", "", false, "", 0).present)
    verify(!R.card(null, "acting", "", false, "", 0).present)
  }

  function test_active_run_card() {
    var c = R.card([boundary(),
                    ent(2, { status: "done", undoRef: "switch back" }),
                    ent(3, { status: "in_flight", label: "type",
                             target: "hey sam" }),
                    ent(4, { status: "queued", label: "key" })],
                   "acting", "", false, "", 0)
    verify(c.present)
    verify(c.active)
    compare(c.intent, "open discord and message sam")
    compare(c.steps, 3)
    compare(c.stepAt, 2)
    compare(c.current, "type hey sam")
    compare(c.outcome, "")
    compare(c.key, "a1")
  }

  function test_terminal_run_summary_and_mutations() {
    var c = R.card([boundary({ status: "done" }),
                    ent(2, { status: "done", undoRef: "switch back",
                             delivery: "background",
                             at: "2026-10-10T01:00:01Z" }),
                    ent(3, { status: "done", at: "2026-10-10T01:00:03Z" })],
                   "done", "", false, "", 0)
    verify(c.present)
    verify(!c.active)
    compare(c.outcome, "done")
    compare(c.steps, 2)
    compare(c.mutations, 1)
    compare(c.undoRefs[0], "switch back")
    compare(c.durationS, 3)
    // the boundary's verdict IS the run's: a failed step inside a run
    // the daemon still reported done does not fail the card; a failed
    // boundary does; a dead boundary resolves cancelled
    compare(R.card([boundary({ status: "done" }),
                    ent(2, { status: "failed" })],
                   "done", "", false, "", 0).outcome, "done")
    compare(R.card([boundary({ status: "failed" }),
                    ent(2, { status: "failed" })],
                   "error", "", false, "", 0).outcome, "failed")
    compare(R.card([boundary(),
                    ent(2, { status: "done" })],
                   "idle", "", false, "", 0).outcome, "cancelled")
  }

  function test_settled_daemon_kills_open_entries() {
    // status left acting (daemon restarted, drop) but stream entries
    // still say in_flight — the card resolves them, never ghosts
    var c = R.card([boundary(), ent(2, { status: "in_flight" })],
                   "idle", "", false, "", 0)
    verify(c.present)
    verify(!c.active)
    compare(c.outcome, "cancelled")
    // same through the stale heartbeat flag while status stays acting
    c = R.card([boundary(), ent(2, { status: "in_flight" })],
               "acting", "", true, "", 0)
    verify(!c.active)
    compare(c.outcome, "cancelled")
    // a fresh daemon publishes an empty stream — nothing to show at all
    verify(!R.card([], "idle", "", false, "", 0).present)
  }

  function test_question_block() {
    var c = R.card([boundary(),
                    ent(2, { kind: "question", status: "awaiting",
                             label: "which account?",
                             promptId: "p9",
                             options: ["work", "personal"] })],
                   "awaiting_choice", "p9", false, "", 0)
    verify(c.present && c.active)
    compare(c.question.text, "which account?")
    compare(c.question.options.length, 2)
    // no offered picks -> the free-text affordance
    c = R.card([boundary(),
                ent(2, { kind: "question", status: "awaiting",
                         label: "what should it say?",
                         promptId: "p9" })],
               "awaiting_choice", "p9", false, "", 0)
    verify(c.question !== null)
    compare(c.question.options.length, 0)
    // a question parked under another prompt id is not the live one
    c = R.card([boundary(),
                ent(2, { kind: "question", status: "awaiting",
                         promptId: "p8" })],
               "awaiting_choice", "p9", false, "", 0)
    verify(c.question === null)
  }
}
