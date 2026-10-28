import QtQuick
import QtTest
import "../../../shell-plugin/components"
import "../harness"

// The REAL OverlayLayer's picture card: shown only with an answer on screen
// and a stored picture (the harness TestCase is not itself visible, so the
// layer's own cardShown stands for "shown"), parked on calm space, clear of every mark and the bubble.
TestCase {
  id: tc
  name: "imageCard"
  when: windowShown
  width: 900
  height: 600

  property var svc: null
  property var overlay: null

  Component { id: svcC; FixtureService {} }
  Component { id: overlayC; OverlayLayer { width: 900; height: 600 } }

  function tokens() {
    var x = new XMLHttpRequest()
    x.open("GET", Qt.resolvedUrl("../../fixtures/themes/vantablack/expected.json"), false)
    x.send()
    return JSON.parse(x.responseText).tokens
  }

  function localPath() {
    return Qt.resolvedUrl("../../fixtures/images/landscape.png").toString().replace("file://", "")
  }

  function note(status) {
    return { title: "t", closed: false, objects: [{ kind: "image", attrs: {}, body: "",
      image: { status: status, local: status === "ready" ? localPath() : "",
        source: "https://upload.wikimedia.org/a.png", host: "upload.wikimedia.org",
        w: 320, h: 200 } }] }
  }

  function make(answer, nt, points) {
    svc = createTemporaryObject(svcC, tc)
    svc.tokens = tokens()
    svc.answer = answer
    svc.status = "idle"
    svc.note = nt
    svc.points = points || []
    overlay = createTemporaryObject(overlayC, tc, { service: svc })
    wait(30)
  }

  function cleanup() {
    if (overlay) overlay.destroy()
    if (svc) svc.destroy()
    wait(0)
    overlay = null
    svc = null
  }

  function card() {
    var d = overlay.data
    for (var i = 0; i < d.length; i++)
      if (d[i].objectName === "imageCard") return d[i]
    return null
  }

  function hits(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
  }

  function test_shows_with_an_answer_and_a_stored_picture() {
    make("here you go", note("ready"))
    var c = card()
    verify(c !== null)
    compare(overlay.cardShown, true)
    verify(c.width > 0 && c.height > 0)
  }

  function test_hidden_without_an_answer() {
    make("", note("ready"))
    compare(overlay.cardShown, false)
  }

  function test_hidden_until_the_picture_is_stored() {
    make("here you go", note("loading"))
    compare(overlay.cardShown, false)
    svc.note = note("ready")
    wait(30)
    compare(overlay.cardShown, true)
  }

  function test_hidden_when_the_fetch_was_refused() {
    make("nope", note("refused"))
    compare(overlay.cardShown, false)
  }

  function test_stays_clear_of_beacons_and_the_bubble() {
    make("look at these two", note("ready"),
      [{ x: 120, y: 300, label: "a", step: 1 }, { x: 760, y: 420, label: "b", step: 2 }])
    var c = card()
    verify(overlay.cardShown)
    var box = { x: c.x, y: c.y, w: c.width, h: c.height }
    var host = overlay.bubbleHost
    verify(!hits(box, { x: host.x, y: host.y, w: host.width, h: host.height }))
    var pts = svc.points
    for (var i = 0; i < pts.length; i++)
      verify(!hits(box, { x: pts[i].x - 18, y: pts[i].y - 18, w: 36, h: 36 }),
             "overlaps point " + i)
    verify(box.x >= 0 && box.y >= 0 && box.x + box.w <= overlay.width
           && box.y + box.h <= overlay.height)
  }
}
