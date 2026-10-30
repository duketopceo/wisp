#!/usr/bin/env python3
"""TLY-430: the overlay must let go when a turn is cancelled.

Scribble holds the whole screen (a full-screen input mask) and the bar pill
shows the live state; both hang on the "turn ended" signal. These pin the
pure rules (scribble.js holdAction, bar.js windowAction/pillState,
rate.js rateable) under node and the wiring that applies them. QML itself
cannot run here (no qmltestrunner), so the service and layer are checked
statically."""
import pathlib
import re
import unittest

import jsnode

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"
SVC = (PLUGIN / "WispService.qml").read_text()
OVERLAY = (PLUGIN / "components" / "OverlayLayer.qml").read_text()
LAYER = (PLUGIN / "components" / "ScribbleLayer.qml").read_text()
COMPANION = (PLUGIN / "Companion.qml").read_text()

LIBS = dict(S="scribble", B="bar", R="rate")


def js(expr):
    return jsnode.call(expr, **LIBS)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class ScribbleHold(unittest.TestCase):
    def act(self, prev, status, code="", pt="t1", t="t1"):
        return js("S.holdAction(%r, %r, %r, %r, %r)"
                  % (prev, status, code, pt, t))

    def test_grab_on_the_listening_edge_only(self):
        self.assertEqual(self.act("idle", "listening"), "grab")
        self.assertEqual(self.act("done", "listening", pt="t1", t="t2"), "grab")
        self.assertEqual(self.act("listening", "listening"), "keep")

    def test_a_new_turn_regrabs_even_from_listening(self):
        self.assertEqual(self.act("listening", "listening", pt="t1", t="t2"),
                         "grab")

    def test_every_other_status_releases(self):
        for st in ("idle", "transcribing", "deciding", "acting", "speaking",
                   "awaiting_choice", "done", "error", "offline"):
            self.assertEqual(self.act("listening", st), "release", st)

    def test_a_cancelled_turn_releases_whatever_the_status(self):
        self.assertEqual(self.act("listening", "listening", code="cancelled"),
                         "release")
        self.assertEqual(self.act("acting", "idle", code="cancelled"),
                         "release")

    def test_hard_timeout_is_a_few_seconds(self):
        ms = js("S.HOLD_MS")
        self.assertGreaterEqual(ms, 2000)
        self.assertLessEqual(ms, 10000)


@unittest.skipUnless(jsnode.NODE, "node not installed")
class PillAfterCancel(unittest.TestCase):
    def pill(self, status, **kw):
        o = dict(status=status, result="", errorCode="", offline=False,
                 confirm=False, windowOpen=False, rateable=False, run=None)
        o.update(kw)
        return js("B.pillState(%s)" % jsnode.json.dumps(o))

    def win(self, prev, status, code="", rateable=True):
        return js("B.windowAction(%r, %r, 't1', 't1', false, %s, %r)"
                  % (prev, status, "true" if rateable else "false", code))

    def test_listening_acting_cancelled_idle_collapses_with_no_window(self):
        prev, open_ = "offline", False
        for status, code, vis in (("listening", "", True), ("acting", "", True),
                                  ("idle", "cancelled", False)):
            a = self.win(prev, status, code)
            if a == "open":
                open_ = True
            elif a == "close":
                open_ = False
            info = self.pill(status, errorCode=code, windowOpen=open_,
                             rateable=False)
            self.assertEqual(info["visible"], vis, status)
            prev = status
        self.assertFalse(open_)
        self.assertEqual(info["kind"], "idle")

    def test_a_cancelled_done_never_opens_the_rating_window(self):
        # the daemon's suggestion run ends `done` / "interrupted"
        self.assertEqual(self.win("acting", "done", code="cancelled"),
                         "close")
        self.assertEqual(self.win("acting", "done", code="", rateable=True),
                         "open")  # the plain finished turn still rates

    def test_a_stale_open_window_closes_on_cancel(self):
        self.assertEqual(self.win("done", "done", code="cancelled"), "close")

    def test_interrupted_results_are_not_rateable(self):
        f = "R.rateable('done', 'hi', %r, '')"
        for r in ("INTERRUPTED (user)", "interrupted", "ABORTED (x)",
                  "CANCELLED (user)"):
            self.assertFalse(js(f % r), r)
        self.assertTrue(js(f % "ANSWERED x"))


class Wiring(unittest.TestCase):
    def test_service_owns_the_hold_and_its_timer(self):
        self.assertRegex(SVC, r"property\s+bool\s+scribbleHeld")
        m = re.search(r"Timer\s*\{[^}]*id:\s*scribbleTimer(.*?)\n  \}", SVC, re.S)
        self.assertIsNotNone(m, "scribbleTimer")
        body = m.group(1)
        self.assertRegex(body, r"interval:\s*Scribble\.HOLD_MS")
        self.assertRegex(body, r"repeat:\s*false")
        self.assertRegex(body, r"running:\s*root\.scribbleHeld")
        self.assertRegex(body, r"scribbleHeld\s*=\s*false")

    def test_adopt_applies_the_hold_action(self):
        self.assertIn("Scribble.holdAction(", SVC)

    def test_interrupt_releases_at_once(self):
        m = re.search(r"function interrupt\(\)\s*\{(.*?)\n  \}", SVC, re.S)
        self.assertRegex(m.group(1), r"scribbleHeld\s*=\s*false")
        self.assertRegex(m.group(1), r"ratingWindowOpen\s*=\s*false")

    def test_the_overlay_mask_needs_the_hold(self):
        self.assertRegex(OVERLAY, r"scribbleActive:[^\n]*scribbleHeld")

    def test_a_stroke_rearms_the_timeout(self):
        self.assertIn("scribbleTouch", LAYER)
        self.assertRegex(SVC, r"function scribbleTouch\(\)")

    def test_no_timer_in_the_component(self):
        code = re.sub(r"//.*", "", LAYER)
        self.assertNotRegex(code, r"\b(Timer|Process|FileView)\s*\{")


if __name__ == "__main__":
    unittest.main()
