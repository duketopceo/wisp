import QtQuick
import QtTest
import "../../../shell-plugin/lib/status.js" as Status
import "../../../shell-plugin/lib/copy.js" as Copy
import "../../../shell-plugin/lib/bar.js" as B
import "../../../shell-plugin/lib/metrics.js" as M
import "../../../shell-plugin/lib/creature.js" as C
import "../../../shell-plugin/lib/buddy.js" as Buddy

// The one status table (wisp-one-surface plan U1): every surface function
// returns the table's values for each status. status.js is generated from
// wisp/status.py; tests/test_status_table.py checks it against Python.
TestCase {
  name: "status"

  readonly property var daemon: ["idle", "listening", "transcribing", "deciding",
    "acting", "speaking", "awaiting_choice", "suggestion", "done", "error", "offline"]

  function test_every_status_has_a_row_with_text() {
    compare(Status.STATUSES.length, daemon.length)
    for (var i = 0; i < daemon.length; i++) {
      var r = Status.ROWS[daemon[i]]
      verify(r !== undefined, daemon[i])
      verify(Copy.string(r.word) !== r.word, daemon[i] + " word key has text")
      verify(Copy.string(r.short) !== r.short, daemon[i] + " short key has text")
    }
    for (var d = 0; d < Status.DERIVED.length; d++)
      verify(Status.ROWS[Status.DERIVED[d]] !== undefined, Status.DERIVED[d])
  }

  function test_short_word_is_the_main_word_or_a_prefix() {
    var keys = Status.STATUSES.concat(Status.DERIVED)
    for (var i = 0; i < keys.length; i++) {
      var r = Status.ROWS[keys[i]]
      var w = Copy.string(r.word), s = Copy.string(r.short)
      compare(w.indexOf(s), 0, keys[i] + ": " + s + " of " + w)
    }
    compare(Status.shortWord("transcribing"), "hearing")
    compare(Status.statusWord("transcribing"), "hearing you")
  }

  function test_the_status_words() {
    var want = { idle: "ready", listening: "listening", transcribing: "hearing you",
      deciding: "thinking", acting: "working", speaking: "speaking",
      awaiting_choice: "your call", suggestion: "idea", done: "done",
      error: "that failed", offline: "offline" }
    for (var k in want) compare(Status.statusWord(k), want[k], k)
    compare(Status.statusWord("nope"), "offline")
    compare(Status.statusTone("error"), "fail")
    compare(Status.statusTone("awaiting_choice"), "needsYou")
  }

  function test_bar_pill_reads_the_short_word() {
    for (var i = 0; i < daemon.length; i++) {
      var s = daemon[i], r = Status.ROWS[s]
      var v = B.pillState({ status: s, windowOpen: true, rateable: true, errorCode: "timeout" })
      if (r.pill === null || s === "offline") { verify(!v.visible, s); continue }
      verify(v.visible, s)
      compare(v.wordKey, r.short, s)
      compare(v.glyph, r.pill.glyph, s)
      compare(v.token, r.pill.token, s)
      compare(v.kind, r.pill.kind, s)
    }
  }

  function test_idle_and_offline_hide_the_pill() {
    verify(!B.pillState({ status: "idle" }).visible)
    verify(!B.pillState({ status: "offline" }).visible)
    verify(!B.pillState({ status: "acting", offline: true }).visible)
    verify(!B.pillState({ status: "suggestion" }).visible)
  }

  function test_derived_states_read_their_rows() {
    var c = B.pillState({ status: "acting", confirm: true })
    compare(c.wordKey, Status.ROWS.confirm.short); compare(c.kind, "needsYou")
    var b = B.pillState({ status: "done", result: "BLOCKED (x)" })
    compare(b.wordKey, Status.ROWS.blocked.short); compare(b.kind, "needsYou")
    compare(Copy.string(b.wordKey), "blocked")
  }

  function test_error_causes_come_from_the_error_row() {
    var causes = Status.ROWS.error.causes
    for (var code in causes)
      compare(B.pillState({ status: "error", errorCode: code }).cause, Copy.string(causes[code]), code)
    compare(B.pillState({ status: "error", errorCode: "internal" }).cause, "")
  }

  function test_mark_creature_and_buddy_follow_the_table() {
    for (var i = 0; i < daemon.length; i++) {
      var s = daemon[i], r = Status.ROWS[s]
      compare(M.markIcon(s), r.glyph, s)
      compare(M.markToken(s), r.mark_token, s)
      compare(C.stateFor(s, "", false), s === "error" ? "error" : r.creature, s)
      compare(C.toneToken(r.creature), r.creature_token, s)
      compare(Buddy.modeFor(s), r.buddy, s)
      compare(Buddy.stateLabel(s), Status.statusWord(s), s)
    }
    compare(M.markIcon("nope"), "bar-offline")
    compare(C.stateFor("nope", "", false), "offline")
  }

  function test_word_view_precedence() {
    compare(Status.wordView("acting", "", "", true).word, "reconnecting")
    compare(Status.wordView("error", "", "timeout", false).word, Copy.errorMessage("timeout"))
    compare(Status.wordView("done", "BLOCKED (x)", "", false).tone, "needsYou")
    compare(Status.wordView("idle", "", "", true).word, "ready")
    compare(Status.wordView("bogus", "", "", false).word, "offline")
  }
}
