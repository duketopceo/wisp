import QtQuick
import QtTest
import "../../../shell-plugin/lib/creature.js" as C
import "../../../shell-plugin/lib/motion.js" as Motion

// Creature state model (Ember U7): 13 states, transients, timing, caps.
TestCase {
  name: "creature"

  function test_thirteen_states_each_have_a_vector() {
    compare(C.STATES.length, 13)
    for (var i = 0; i < C.STATES.length; i++) {
      var v = C.VECTORS[C.STATES[i]]
      verify(v !== undefined, C.STATES[i])
      verify(v.energy >= 0 && v.energy <= 1)
      verify(v.cohesion >= 0 && v.cohesion <= 1)
      compare(v.gaze.length, 2)
    }
  }

  function test_every_reducer_status_maps_and_unknown_is_offline() {
    var map = { idle: "idle", listening: "listening", transcribing: "transcribing",
      deciding: "thinking", speaking: "speaking", acting: "acting",
      awaiting_choice: "awaiting_choice", suggestion: "suggestion",
      done: "done", error: "error", offline: "offline" }
    for (var k in map) compare(C.stateFor(k, "", false), map[k], k)
    compare(C.stateFor("nope", "", false), "offline")
    compare(C.stateFor(undefined, "", false), "offline")
  }

  function test_transients_win_and_error_returns_to_idle() {
    compare(C.stateFor("acting", "confirmed", false), "confirmed")
    compare(C.stateFor("idle", "didnt_understand", false), "didnt_understand")
    compare(C.stateFor("error", "", false), "error")
    compare(C.stateFor("error", "", true), "idle")
    compare(C.stateFor("idle", "bogus", false), "idle")
  }

  function test_transition_rules() {
    compare(C.transition("awaiting_choice", "acting", null), "confirmed")
    compare(C.transition("awaiting_choice", "error", null), "")
    compare(C.transition("awaiting_choice", "offline", null), "")
    compare(C.transition("acting", "done", "didnt_understand"), "didnt_understand")
    compare(C.transition("acting", "done", null), "")
    compare(C.transition("idle", "idle", "didnt_understand"), "")
  }

  function test_beckon_is_at_most_twice_eight_seconds_apart() {
    var plan = C.beckonPlan()
    compare(plan.length, 2)
    compare(plan[1] - plan[0], 8000)
    compare(C.TIMING.errorReturnMs, 6000)
  }

  function test_only_listening_thinking_speaking_run_continuously() {
    for (var i = 0; i < C.STATES.length; i++) {
      var s = C.STATES[i]
      var cont = ["listening", "thinking", "speaking"].indexOf(s) >= 0
      compare(Motion.loops(s, "full"), cont, s)
      compare(Motion.loops(s, "reduced"), false, s)
      compare(Motion.loops(s, "off"), false, s)
      compare(C.needsClock(s, "off"), false, s)
      compare(C.needsClock(s, "reduced"), false, s)
    }
    compare(C.needsClock("idle", "full"), true)
    compare(C.needsClock("acting", "full"), false)
    compare(C.needsClock("awaiting_choice", "full"), false)
  }

  function test_redraw_caps_hold_at_120hz() {
    compare(C.clockStep("idle", 60), 0.1)
    compare(C.clockStep("idle", 120), 0.1)
    compare(C.clockStep("listening", 60), 1 / 60)
    compare(C.clockStep("listening", 120), 1 / 60)
    compare(C.clockStep("listening", 30), 1 / 30)
    compare(C.clockStep("listening", 0), 1 / 60)
    // the uniform clock moves at most 10 times a second at idle
    var seen = {}
    for (var f = 0; f < 120; f++) seen[C.quantize(f / 120, "idle", 120).toFixed(3)] = 1
    compare(Object.keys(seen).length, 10)
  }

  function test_reduced_changes_brightness_only() {
    var full = C.uniforms("acting", 0, 0.5, "full", 0, 0)
    var red = C.uniforms("acting", 0, 0.5, "reduced", 0, 0)
    compare(red.gaze[0], 0)
    verify(full.gaze[0] !== 0)
    var lf = C.uniforms("listening", 1, 0.5, "full", 0, 0)
    var lr = C.uniforms("listening", 1, 0.5, "reduced", 0, 0)
    verify(lf.energy > C.VECTORS.listening.energy)
    verify(lr.energy > C.VECTORS.listening.energy)
    var lo = C.uniforms("listening", 1, 0.5, "off", 0, 0)
    compare(lo.energy, C.VECTORS.listening.energy)
    var bk = C.uniforms("awaiting_choice", 0, 0.5, "reduced", 1, 0)
    compare(bk.energy, C.VECTORS.awaiting_choice.energy)
  }

  function test_didnt_understand_shake_only_in_full() {
    var a = C.uniforms("didnt_understand", 0, 0.5, "full", 0, 1)
    var b = C.uniforms("didnt_understand", 0, 0.5, "reduced", 0, 1)
    verify(a.gaze[0] > b.gaze[0])
    verify(Math.abs(C.shakeOffset(0, 5)) < 1e-9)
    verify(Math.abs(C.shakeOffset(1, 5)) < 1e-9)
  }

  function test_speaking_rhythm_is_low_amplitude() {
    var lo = 1, hi = 0
    for (var i = 0; i < 400; i++) {
      var e = C.speakingEnvelope(i / 400, "full")
      lo = Math.min(lo, e); hi = Math.max(hi, e)
    }
    verify(hi - lo <= 0.41)
    compare(C.speakingEnvelope(0.3, "off"), 0.5)
    // reduced: one slow pulse, no faster than 0.5 Hz
    var flips = 0, prev = C.speakingEnvelope(0, "reduced")
    for (var j = 1; j < 1000; j++) {
      var cur = C.speakingEnvelope(j / 1000, "reduced")
      if ((cur - 0.5) * (prev - 0.5) < 0) flips++
      prev = cur
    }
    verify(flips <= 2)
  }

  function test_idle_flicker_under_three_percent() {
    var m = 0
    for (var i = 0; i < 2000; i++) m = Math.max(m, Math.abs(C.flicker(i * 0.05)))
    verify(m < 0.03)
  }

  function test_tone_tokens() {
    compare(C.toneToken("error"), "fail")
    compare(C.toneToken("awaiting_choice"), "needsYou")
    compare(C.toneToken("offline"), "inkMuted")
    compare(C.toneToken("listening"), "ember")
  }
}
