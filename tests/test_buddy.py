#!/usr/bin/env python3
"""U6: lean cursor buddy. shell-plugin/lib/buddy.js (pure, run under node)
plus the static shape of components/Buddy.qml: one short state label per
daemon status, reduced motion that never animates movement, and a buddy
that never takes keyboard focus."""
import json
import pathlib
import re
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
QML = ROOT / "shell-plugin" / "components" / "Buddy.qml"
MAX_WORDS = 3
MAX_CHARS = 18


def js(expr):
    return jsnode.call(expr, B="buddy", C="copy")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestStateLabels(unittest.TestCase):
    def statuses(self):
        return js("B.LIVE") + ["idle", "offline"]

    def test_every_status_has_one_short_label(self):
        for s in self.statuses():
            label = js("B.stateLabel(%s)" % json.dumps(s))
            self.assertIsInstance(label, str, s)
            self.assertTrue(label.strip(), s)
            self.assertLessEqual(len(label.split()), MAX_WORDS, (s, label))
            self.assertLessEqual(len(label), MAX_CHARS, (s, label))

    def test_label_comes_from_copy(self):
        for s in self.statuses():
            self.assertEqual(js("B.stateLabel(%s)" % json.dumps(s)),
                             js("C.statusWord(%s)" % json.dumps(s)), s)

    def test_unknown_status_reads_offline(self):
        self.assertEqual(js("B.stateLabel('bogus')"), "offline")

    def test_view_carries_the_label_for_the_status(self):
        for s in js("B.LIVE"):
            text = js("""(function () {
              var m = B.step(B.init(), { pointer: {x: 10, y: 10}, status: %s,
                level: 0, target: null, motion: 'full' }, 1 / 60)
              return B.view(m, { screen: {w: 800, h: 600}, motion: 'full' }).state.text
            })()""" % json.dumps(s))
            self.assertEqual(text, js("B.stateLabel(%s)" % json.dumps(s)), s)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestReducedMotion(unittest.TestCase):
    RUN = """(function () {
      var tgt = { visible: true, state: 'parked', x: 700, y: 400, label: 'Save', unsure: false }
      var m = B.init(), out = [], mode = %s
      function go(status, ptr, target, secs) {
        for (var i = 0; i < secs * 60; i++) {
          m = B.step(m, { pointer: ptr, status: status, level: 0.7, target: target, motion: mode }, 1 / 60)
          var v = B.view(m, { screen: {w: 1920, h: 1080}, motion: mode })
          out.push({ phase: v.phase, x: v.x, y: v.y, scale: v.scale, rot: v.rotation,
            spin: v.spinAngle, ls: v.label.scale, vis: v.visible })
        }
      }
      go('listening', {x: 100, y: 100}, null, 1)
      go('listening', {x: 300, y: 250}, null, 0.5)
      go('speaking', {x: 300, y: 250}, tgt, 1)
      go('done', {x: 300, y: 250}, null, 6)
      return out
    })()"""

    def frames(self, mode):
        return js(self.RUN % json.dumps(mode))

    def test_reduced_and_off_never_animate_movement(self):
        for mode in ("reduced", "off"):
            frames = self.frames(mode)
            phases = {f["phase"] for f in frames}
            self.assertFalse(phases & {"flying", "returning"}, (mode, phases))
            for f in frames:
                self.assertEqual(f["scale"], 1, mode)
                self.assertEqual(f["rot"], -35, mode)
                self.assertEqual(f["spin"], 0, mode)
                if f["ls"]:
                    self.assertEqual(f["ls"], 1, mode)

    def test_reduced_follow_snaps_to_the_pointer_offset(self):
        for mode in ("reduced", "off"):
            m = js("""(function () {
              var m = B.step(B.init(), { pointer: {x: 100, y: 100}, status: 'listening',
                level: 0, target: null, motion: %s }, 1 / 60)
              return B.step(m, { pointer: {x: 400, y: 300}, status: 'listening',
                level: 0, target: null, motion: %s }, 1 / 60)
            })()""" % (json.dumps(mode), json.dumps(mode)))
            self.assertEqual((m["x"], m["y"]), (435, 325), mode)

    def test_reduced_target_lands_in_one_step(self):
        m = js("""(function () {
          var i = { pointer: {x: 100, y: 100}, status: 'speaking', level: 0,
            target: { visible: true, state: 'parked', x: 900, y: 500, label: 'Save', unsure: false },
            motion: 'reduced' }
          return B.step(B.step(B.init(), i, 1 / 60), i, 1 / 60)
        })()""")
        self.assertEqual(m["phase"], "held")
        self.assertEqual((m["x"], m["y"]), (900, 500))

    def test_full_motion_flight_is_calm(self):
        peak = js("""(function () {
          var idle = { pointer: {x: 100, y: 100}, status: 'listening', level: 0,
            target: null, motion: 'full' }
          var fly = { pointer: {x: 100, y: 100}, status: 'speaking', level: 0,
            target: { visible: true, state: 'parked', x: 1200, y: 600, label: 'Save', unsure: false },
            motion: 'full' }
          var m = B.init(), top = 1, k
          for (k = 0; k < 120; k++) m = B.step(m, idle, 1 / 60)
          for (k = 0; k < 120; k++) { m = B.step(m, fly, 1 / 60); top = Math.max(top, m.scale) }
          return top
        })()""")
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 1.12)


class TestNeverTakesFocus(unittest.TestCase):
    def source(self):
        src = re.sub(r"/\*.*?\*/", "", QML.read_text(), flags=re.S)
        return re.sub(r"//.*", "", src)

    def test_buddy_has_no_focus_or_key_handling(self):
        src = self.source()
        for pat in (r"\bfocus\b", r"activeFocusOnTab", r"\bKeys\b",
                    r"forceActiveFocus", r"FocusScope", r"MouseArea",
                    r"TapHandler", r"HoverHandler",
                    r"TextInput|TextField|TextEdit"):
            self.assertIsNone(re.search(pat, src), pat)

    def test_buddy_has_no_decoration(self):
        src = self.source()
        self.assertNotIn("emberHalo", src)
        self.assertNotIn("NumberAnimation", src)


if __name__ == "__main__":
    unittest.main()
