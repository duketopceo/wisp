import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../harness"

// Ask chips: text only, shown from state.chips while the service is quiet,
// never over a live turn, gone after their time, and no fade in reduced motion.
TestCase {
  id: tc
  name: "askChips"
  when: windowShown
  width: 900
  height: 600

  property var svc: null
  property var overlay: null

  Component { id: svcC; FixtureService {} }
  Component { id: overlayC; OverlayLayer { width: 900; height: 600 } }
  Component { id: chipsC; AskChips {} }

  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }
  function chips(n) {
    return { app: "kitty", seq: n || 1, asks: ["How do I open a new tab?", "How do I split this window?", "How do I copy the last output?", "a fourth"] }
  }
  function make(status, c) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.status = status
    svc.chips = c
    overlay = createTemporaryObject(overlayC, tc, { service: svc })
    wait(30)
  }

  function test_a_tap_shows_three_chips_for_the_app() {
    make("done", chips())
    verify(overlay.chipsShown)
    verify(overlay.shown)
    var item = overlay.askChipsItem
    compare(item.v.asks.length, 3)
    compare(item.v.asks[0], "How do I open a new tab?")
  }

  function test_no_chips_state_shows_nothing() {
    make("done", null)
    verify(!overlay.chipsShown)
  }

  function test_never_over_a_live_turn() {
    var live = ["listening", "transcribing", "deciding", "acting", "speaking", "awaiting_choice"]
    for (var i = 0; i < live.length; i++) {
      make(live[i], chips())
      verify(!overlay.chipsShown, live[i])
    }
  }

  function test_chips_leave_on_their_own() {
    make("done", chips())
    verify(overlay.chipsShown)
    overlay.askChipsItem.expired = true
    verify(!overlay.chipsShown)
    // a new tap (new chips value) brings them back
    svc.chips = chips(2)
    verify(overlay.chipsShown)
  }

  function test_chips_are_not_clickable_and_take_no_input() {
    make("done", chips())
    var item = overlay.askChipsItem
    compare(item.children.length > 0, true)
    var hits = 0
    for (var i = 0; i < item.children.length; i++)
      if (String(item.children[i]).indexOf("MouseArea") >= 0) hits++
    compare(hits, 0)
  }

  function test_fade_runs_only_in_full_motion() {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    var full = createTemporaryObject(chipsC, tc, { service: svc, chips: chips(), motion: "full" })
    var red = createTemporaryObject(chipsC, tc, { service: svc, chips: chips(), motion: "reduced" })
    verify(full.width > 100 && full.height > 50)
    compare(red.opacity, 1)
    compare(full.opacity, 1)
    // fading out: reduced is gone the same frame, full is still fading
    red.expired = true
    compare(red.opacity, 0)
    full.expired = true
    verify(full.opacity > 0)
    tryCompare(full, "opacity", 0, 1000)
  }

  function test_nothing_shown_for_a_chips_object_with_no_asks() {
    make("done", { app: "x", seq: 1, asks: [] })
    verify(!overlay.chipsShown)
    make("done", { app: "x", seq: 1, asks: ["   ", 7, null] })
    verify(!overlay.chipsShown)
  }
}
