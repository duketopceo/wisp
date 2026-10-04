import QtQuick
import QtTest
import "../../../shell-plugin/lib/copy.js" as Copy

// copy.js is generated from wisp/copy.py; these mirror tests/test_copy.py
// so the JS interpreter of the shared rules cannot drift from Python.
TestCase {
  name: "copy"

  function test_status_words() {
    compare(Copy.statusWord("awaiting_choice"), "your call")
    compare(Copy.statusWord("deciding"), "thinking")
    compare(Copy.statusWord("nope"), "offline")
    compare(Copy.statusTone("error"), "fail")
    compare(Copy.statusTone("awaiting_choice"), "needsYou")
  }

  function test_pill_view() {
    compare(Copy.pillView("done", "BLOCKED (risk=0.90 > 0.5)").word, "blocked")
    compare(Copy.pillView("done", "BLOCKED (risk=0.90 > 0.5)").tone, "needsYou")
    compare(Copy.pillView("done", "ACTED ok").word, "done")
    compare(Copy.pillView("done", "").tone, "ok")
    compare(Copy.pillView("acting", "BLOCKED (x)").word, "working")
  }

  function test_results() {
    var r = Copy.translateResult("SKIP (launch route but no app identified)")
    compare(r.text, "didn't catch which app")
    compare(r.state, "didnt_understand")
    compare(r.detail, "SKIP (launch route but no app identified)")
    compare(Copy.translateResult("BLOCKED (tool 'x' needs confirmation)").text,
            "blocked: needs your ok")
    compare(Copy.translateResult("BLOCKED (window is locked)").text,
            "blocked: window is locked")
    compare(Copy.translateResult("ASK_USER which account?").text, "which account?")
    var plain = Copy.translateResult("Opened Firefox.")
    compare(plain.text, "Opened Firefox.")
    compare(plain.state, null)
    compare(plain.detail, "")
    verify(Copy.translateResult("BLOCKED (a — b)").text.indexOf("—") < 0)
  }

  function test_pick_label() {
    compare(Copy.pickLabel("app:none"), "none of these")
    compare(Copy.pickLabel("action:run_shell"), "run a command")
    compare(Copy.pickLabel("action:new_thing"), "new thing")
    compare(Copy.pickLabel("suggestion:action:act"), "do it for me")
    compare(Copy.pickLabel("Close all windows — yes"), "Close all windows: yes")
  }

  function test_errors_and_strings() {
    compare(Copy.errorMessage("timeout"), "that took too long")
    compare(Copy.errorMessage("nope"), Copy.errorMessage("internal"))
    compare(Copy.errorHint("cancelled"), "")
    compare(Copy.string("state.stale"), "out of date")
    compare(Copy.string("no.such"), "no.such")
  }
}
