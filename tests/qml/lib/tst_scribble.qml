import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../../../shell-plugin/lib/scribble.js" as S
import "../harness"

// Scribble to ask: lib/scribble.js (pure) and the real sl: only a drag
// while listening draws, the strokes go up, and they are gone the moment
// listening ends.
TestCase {
  id: tc
  name: "scribble"
  when: windowShown
  visible: true     // the pointer only reaches visible items
  width: 400
  height: 300

  property var svc: null
  property var sl: null
  property var sent: []

  Component { id: svcC; FixtureService {} }
  Component { id: layerC; ScribbleLayer { width: 400; height: 300 } }
  Component { id: overlayC; OverlayLayer { width: 400; height: 300 } }

  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function make(status) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.status = status
    sent = []
    sl = createTemporaryObject(layerC, tc, { service: svc, active: status === "listening" })
    sl.scribbled.connect(function (p) { tc.sent = tc.sent.concat([p]) })
    wait(20)
  }

  function cleanup() {
    if (sl) sl.destroy()
    if (svc) svc.destroy()
    wait(0)
    sl = null
    svc = null
  }

  function drag(x0, y0, x1, y1) {
    mousePress(sl, x0, y0)
    for (var i = 1; i <= 10; i++)
      mouseMove(sl, x0 + (x1 - x0) * i / 10, y0 + (y1 - y0) * i / 10, 0, Qt.LeftButton)
    mouseRelease(sl, x1, y1)
  }

  // ---- lib/scribble.js ----

  function test_a_point_is_kept_only_after_it_moves_far_enough() {
    var p = S.begin(10, 10)
    compare(S.extend(p, 11, 11), p)
    compare(S.extend(p, 20, 10).length, 2)
  }

  function test_a_click_is_not_a_scribble_and_a_drag_is() {
    verify(!S.counts(S.begin(5, 5)))
    verify(!S.counts([{ x: 0, y: 0 }, { x: 5, y: 0 }]))
    verify(S.counts([{ x: 0, y: 0 }, { x: 40, y: 0 }]))
  }

  function test_thinning_keeps_the_ends_and_the_cap() {
    var pts = []
    for (var i = 0; i < 500; i++) pts.push({ x: i, y: 0 })
    var t = S.thin(pts, 50)
    compare(t.length, 50)
    compare(t[0].x, 0)
    compare(t[49].x, 499)
    compare(S.thin(pts.slice(0, 10), 50).length, 10)
  }

  function test_commit_drops_clicks_and_keeps_the_newest_twelve() {
    var strokes = []
    for (var i = 0; i < 15; i++)
      strokes = S.commit(strokes, [{ x: i, y: 0 }, { x: i + 40, y: 0 }])
    compare(strokes.length, 12)
    compare(strokes[0][0].x, 3)
    compare(S.commit(strokes, S.begin(1, 1)), strokes)
  }

  function test_payload_is_whole_pixels_and_empty_means_clear() {
    var p = S.payload([[{ x: 1.4, y: 2.6 }, { x: 10.5, y: 3 }]], 400.2, 300.7)
    compare(JSON.stringify(p), '{"strokes":[[[1,3],[11,3]]],"w":400,"h":301}')
    compare(S.payload([], 10, 10).strokes.length, 0)
  }

  function test_only_listening_activates() {
    verify(S.active("listening"))
    verify(!S.active("speaking"))
    verify(!S.active("idle"))
  }

  function test_bounds() {
    compare(S.bounds([]), null)
    var b = S.bounds([[{ x: 5, y: 9 }, { x: 25, y: 3 }]])
    compare(b.x, 5); compare(b.w, 20); compare(b.y, 3); compare(b.h, 6)
  }

  // ---- the sl ----

  function test_a_drag_while_listening_draws_and_reports() {
    make("listening")
    drag(50, 50, 250, 150)
    compare(sl.strokes.length, 1)
    compare(sent.length, 1)
    compare(sent[0].w, 400)
    compare(sent[0].strokes.length, 1)
    verify(sent[0].strokes[0].length >= 2)
  }

  function test_a_plain_click_draws_nothing_and_sends_nothing() {
    make("listening")
    mouseClick(sl, 60, 60)
    compare(sl.strokes.length, 0)
    compare(sent.length, 0)
  }

  function test_not_listening_takes_no_input() {
    make("speaking")
    drag(50, 50, 250, 150)
    compare(sl.strokes.length, 0)
    compare(sent.length, 0)
  }

  function test_strokes_vanish_the_moment_listening_ends() {
    make("listening")
    drag(50, 50, 250, 150)
    compare(sl.strokes.length, 1)
    svc.status = "transcribing"
    sl.active = false
    compare(sl.strokes.length, 0)
    compare(sl.live.length, 0)
  }

  function test_a_new_listening_turn_clears_what_the_last_one_sent() {
    make("listening")
    drag(50, 50, 250, 150)
    sl.active = false
    sl.active = true
    // the empty payload tells the daemon to forget the old strokes
    compare(sent[sent.length - 1].strokes.length, 0)
    compare(sl.strokes.length, 0)
  }

  function test_no_clear_is_sent_when_nothing_was() {
    make("listening")
    sl.active = false
    sl.active = true
    compare(sent.length, 0)
  }

  function test_the_overlay_claims_input_only_while_listening() {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.status = "idle"
    var o = createTemporaryObject(overlayC, tc, { service: svc })
    compare(o.scribbleActive, false)
    svc.status = "listening"
    compare(o.scribbleActive, true)
    compare(o.shown, true)
    svc.status = "transcribing"
    compare(o.scribbleActive, false)
    o.destroy()
  }
}
