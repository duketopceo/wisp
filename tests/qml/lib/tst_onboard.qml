import QtQuick
import QtTest
import "../../../shell-plugin/lib/onboard.js" as O
import "../../../shell-plugin/components"
import "../harness"

// First-run card (W28): lib/onboard.js row model and command argv, and
// FirstRunCard against the harness FixtureService: run, skip, undo and
// finish chips emit the matching signal with the step id.
TestCase {
  name: "onboard"
  width: 400
  height: 600
  when: windowShown

  FixtureService { id: svc }

  SignalSpy { id: runs; target: card; signalName: "run" }
  SignalSpy { id: skips; target: card; signalName: "skip" }
  SignalSpy { id: undos; target: card; signalName: "undo" }
  SignalSpy { id: finishes; target: card; signalName: "finish" }

  FirstRunCard {
    id: card
    service: svc
    width: 360
    steps: [
      { id: "mic", name: "microphone", optional: false, state: "done", detail: "ok", "try": "" },
      { id: "models", name: "local models", optional: false, state: "todo", detail: "none up", "try": "wispd health start" },
      { id: "cua", name: "cua", optional: true, state: "todo", detail: "", "try": "" },
      { id: "notifications", name: "notifications", optional: false, state: "todo", detail: "", "try": "" },
      { id: "keybinding", name: "keybinding", optional: true, state: "na", detail: "needs W24", "try": "" }
    ]
    skipped: ["cua"]
  }

  function init() { runs.clear(); skips.clear(); undos.clear(); finishes.clear() }

  function find(item, name) {
    if (item.objectName === name) return item
    var kids = item.children
    for (var i = 0; i < kids.length; i++) {
      var r = find(kids[i], name)
      if (r) return r
    }
    return null
  }

  function test_parse_envelope_and_bare() {
    var env = JSON.stringify({ ok: true, data: { finished: false, steps: [{ id: "mic" }] } })
    compare(O.parse(env).steps.length, 1)
    compare(O.parse(JSON.stringify({ steps: [] })).steps.length, 0)
    compare(O.parse("not json"), null)
    compare(O.parse("{}"), null)
  }

  function test_rows_mark_skipped_and_count_done() {
    var rows = O.rows(card.steps, ["cua"])
    compare(rows[0].state, "done")
    compare(rows[2].state, "skipped")
    compare(rows[3].state, "todo")
    compare(rows[4].state, "na")
    var c = O.counts(rows)
    compare(c.done, 1)
    compare(c.total, 4)
    // a skipped step that is done stays done
    compare(O.rows([{ id: "mic", state: "done" }], ["mic"])[0].state, "done")
  }

  function test_commands() {
    compare(O.stepCommand("/bin/wispd", "mic"), ["/bin/wispd", "onboard", "--step", "mic", "--json"])
    compare(O.stepCommand("/bin/wispd", "notifications"),
            ["/bin/wispd", "onboard", "--step", "notifications", "--json", "--yes"])
    compare(O.undoCommand("w", "mic"), ["w", "onboard", "--undo", "mic", "--json"])
    compare(O.finishCommand("w"), ["w", "onboard", "--finish", "--json"])
    compare(O.statusCommand("w"), ["w", "onboard", "--status", "--json"])
  }

  function test_visible_until_finished() {
    verify(O.visible({ finished: false, steps: [] }))
    verify(!O.visible({ finished: true, steps: [] }))
    verify(!O.visible(null))
  }

  function test_chips_emit_signals_with_the_step_id() {
    var run = find(card, "run:models")
    verify(run !== null)
    run.clicked()
    compare(runs.count, 1)
    compare(runs.signalArguments[0][0], "models")
    find(card, "skip:models").clicked()
    compare(skips.signalArguments[0][0], "models")
    find(card, "undo:mic").clicked()
    compare(undos.signalArguments[0][0], "mic")
    find(card, "finish").clicked()
    compare(finishes.count, 1)
  }

  // the card's chips come from O.actions; the chips exist for every row
  function test_state_decides_which_actions_exist() {
    compare(O.actions("done"), { run: false, skip: false, undo: true })
    compare(O.actions("todo"), { run: true, skip: true, undo: false })
    compare(O.actions("skipped"), { run: true, skip: false, undo: false })
    compare(O.actions("na"), { run: false, skip: false, undo: false })
    verify(find(card, "undo:mic") !== null)
    verify(find(card, "run:cua") !== null)
  }
}
