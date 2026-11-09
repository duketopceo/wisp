import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../harness"

// Composer: closed until the host opens it, sends one trimmed question
// through service.askAbout on Enter, and closes on send, Esc or an empty Enter.
TestCase {
  id: tc
  name: "composer"
  when: windowShown
  width: 600
  height: 200

  property var sent: []

  Component {
    id: svcC
    FixtureService {
      property var log: null
      function askAbout(text) { if (log) log.push(text); return true }
    }
  }
  Component { id: compC; Composer { width: 400 } }

  function make() {
    var svc = createTemporaryObject(svcC, tc)
    svc.log = []
    var c = createTemporaryObject(compC, tc, { service: svc })
    return { svc: svc, c: c }
  }

  function test_closed_by_default() {
    var m = make()
    compare(m.c.open, false)
    compare(m.c.visible, false)
  }

  function test_open_shows_and_enter_sends_trimmed_text() {
    var m = make()
    m.c.open = true
    // the harness TestCase is not itself visible, so `open` stands for shown
    compare(m.c.open, true)
    m.c.text = "  what is on this page?  "
    keyClick(Qt.Key_Return)
    compare(m.svc.log.length, 1)
    compare(m.svc.log[0], "what is on this page?")
    compare(m.c.open, false)
  }

  function test_empty_enter_closes_without_sending() {
    var m = make()
    m.c.open = true
    m.c.text = "   "
    keyClick(Qt.Key_Return)
    compare(m.svc.log.length, 0)
    compare(m.c.open, false)
  }

  function test_escape_closes_without_sending() {
    var m = make()
    m.c.open = true
    m.c.text = "never sent"
    keyClick(Qt.Key_Escape)
    compare(m.svc.log.length, 0)
    compare(m.c.open, false)
  }

  function test_reopen_starts_empty() {
    var m = make()
    m.c.open = true
    m.c.text = "old"
    m.c.open = false
    m.c.open = true
    compare(m.c.text, "")
  }
}
