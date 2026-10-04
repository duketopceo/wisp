import QtQuick
import QtTest
import "../../../shell-plugin/lib/motion.js" as Motion

TestCase {
  name: "motion"

  function test_mode_resolution() {
    compare(Motion.resolveMode("off", true), "off")
    compare(Motion.resolveMode("reduced", true), "reduced")
    compare(Motion.resolveMode("", true), "full")
    compare(Motion.resolveMode("", false), "reduced")
    compare(Motion.resolveMode("bogus", false), "reduced")
    compare(Motion.resolveMode(undefined, undefined), "full")
  }

  function test_travel_is_distance_scaled_and_capped() {
    compare(Motion.travelMs(0, "full"), 320)
    compare(Motion.travelMs(400, "full"), 420)
    compare(Motion.travelMs(5000, "full"), 520)
    compare(Motion.travelMs(400, "reduced"), Motion.duration.quick)
    compare(Motion.travelMs(400, "off"), 0)
  }

  function test_exit_is_shorter_than_enter() {
    compare(Motion.exitMs(220), 154)
    verify(Motion.exitMs(Motion.duration.state) < Motion.duration.state)
  }

  function test_springs() {
    compare(Motion.spring.spatialDefault.spring, 4.0)
    compare(Motion.spring.spatialDefault.damping, 0.35)
    verify(Motion.spring.spatialFast.spring > Motion.spring.spatialSlow.spring)
  }

  function test_continuous_motion_only_when_needed() {
    verify(Motion.loops("listening", "full"))
    verify(!Motion.loops("idle", "full"))
    verify(!Motion.loops("listening", "reduced"))
    verify(!Motion.loops("listening", "off"))
  }
}
