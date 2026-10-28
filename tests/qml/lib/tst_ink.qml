import QtQuick
import QtTest
import "../../../shell-plugin/lib/ink.js" as Ink

// lib/ink.js: strokes, pen timing and luminance. Pure functions.
TestCase {
  name: "ink"

  function test_each_kind_has_strokes_and_unknown_has_none() {
    verify(Ink.strokesFor({ kind: "ring", x: 100, y: 100, r: 40 }).strokes.length === 1)
    verify(Ink.strokesFor({ kind: "arrow", x1: 0, y1: 0, x2: 100, y2: 50 }).strokes.length === 3)
    var hl = Ink.strokesFor({ kind: "hl", x: 0, y: 0, w: 100, h: 50 })
    verify(hl.strokes.length > 4)
    verify(hl.fill !== null)
    compare(Ink.strokesFor({ kind: "squiggle", x: 1 }).strokes.length, 0)
  }

  function test_the_same_mark_wobbles_the_same_way() {
    var a = Ink.strokesFor({ kind: "ring", x: 100, y: 100, r: 40 })
    var b = Ink.strokesFor({ kind: "ring", x: 100, y: 100, r: 40 })
    compare(JSON.stringify(a), JSON.stringify(b))
    var c = Ink.strokesFor({ kind: "ring", x: 101, y: 100, r: 40 })
    verify(JSON.stringify(a) !== JSON.stringify(c))
  }

  function test_pen_is_tapered() {
    var w = Ink.widths(20)
    verify(w[0] < w[10])
    verify(w[19] < w[10])
    for (var i = 0; i < w.length; i++) verify(w[i] >= 1 && w[i] <= 3)
  }

  function test_pace_follows_the_spoken_sentence() {
    compare(Ink.revealMs(1000), 600)
    compare(Ink.revealMs(100), 250)
    compare(Ink.revealMs(60000), 1800)
    compare(Ink.revealMs(0), 300)
    compare(Ink.revealMs(undefined), 300)
  }

  function test_a_mark_never_draws_before_its_sentence_starts() {
    compare(Ink.progress(1000, 600, 999, "full"), 0)
    compare(Ink.progress(1000, 600, 1000, "full"), 0)
    verify(Ink.progress(1000, 600, 1300, "full") > 0.5)
    compare(Ink.progress(1000, 600, 1600, "full"), 1)
  }

  function test_reduced_and_off_motion_animate_nothing() {
    compare(Ink.animates("full"), true)
    compare(Ink.animates("reduced"), false)
    compare(Ink.animates("off"), false)
    compare(Ink.progress(1000, 600, 0, "reduced"), 1)
    compare(Ink.progress(1000, 600, 0, "off"), 1)
  }

  function test_finish_now_completes_every_mark() {
    var f = Ink.finishNow(3)
    compare(f.length, 3)
    compare(f[0] + f[1] + f[2], 3)
  }

  function test_partial_cuts_at_the_length() {
    var s = Ink.strokesFor({ kind: "arrow", x1: 0, y1: 0, x2: 100, y2: 0 }).strokes[0]
    var half = Ink.partial(s, 0.5)
    verify(Ink.pathLength(half) < Ink.pathLength(s) * 0.55)
    verify(Ink.pathLength(half) > Ink.pathLength(s) * 0.45)
    compare(Ink.partial(s, 1).length, s.length)
  }

  function test_text_colour_follows_luminance() {
    compare(Ink.textOn(Ink.luminance(10, 10, 12)), "light")
    compare(Ink.textOn(Ink.luminance(245, 245, 240)), "dark")
    compare(Ink.tone(Ink.luminance(10, 10, 12)), "dark")
    compare(Ink.tone(Ink.luminance(245, 245, 240)), "light")
  }
}
