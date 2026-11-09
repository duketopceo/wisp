"""Double-Control typed composer (U1, KTD1): tap detector, bind install and
fallback, the `tap` fastkey command, and the typed-question path."""
import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wisp import composer, fastkey, hypr  # noqa: E402


def taps(det, *spans, talk=False):
    """Feed (down, up) pairs; returns the list of detector verdicts."""
    out = []
    for down, up in spans:
        out.append(det.feed("down", down, talk_held=talk))
        out.append(det.feed("up", up, talk_held=talk))
    return out


class TestTapDetector(unittest.TestCase):
    def test_two_short_taps_close_together_open(self):
        d = composer.TapDetector()
        self.assertTrue(any(taps(d, (0.0, 0.08), (0.28, 0.36))))

    def test_opens_on_the_second_release_not_before(self):
        d = composer.TapDetector()
        self.assertEqual(taps(d, (0.0, 0.08), (0.28, 0.36)),
                         [False, False, False, True])

    def test_two_taps_500ms_apart_do_not_open(self):
        d = composer.TapDetector()
        self.assertFalse(any(taps(d, (0.0, 0.08), (0.58, 0.66))))

    def test_a_long_hold_is_a_chord_not_a_tap(self):
        d = composer.TapDetector()
        self.assertFalse(any(taps(d, (0.0, 0.40), (0.5, 0.58))))
        # and a hold between two real taps breaks the pair
        d = composer.TapDetector()
        self.assertFalse(any(taps(d, (0.0, 0.08), (0.2, 0.6))))

    def test_taps_while_talk_key_held_are_ignored(self):
        d = composer.TapDetector()
        self.assertFalse(any(taps(d, (0.0, 0.08), (0.2, 0.28), talk=True)))
        # and one tap made during talk does not pair with a later one
        d = composer.TapDetector()
        d.feed("down", 0.0, talk_held=True)
        d.feed("up", 0.08, talk_held=True)
        self.assertFalse(any(taps(d, (0.2, 0.28))))

    def test_three_taps_open_once(self):
        d = composer.TapDetector()
        res = taps(d, (0.0, 0.08), (0.2, 0.28), (0.4, 0.48))
        self.assertEqual(res.count(True), 1)

    def test_up_without_down_is_ignored(self):
        d = composer.TapDetector()
        self.assertFalse(d.feed("up", 1.0))
        self.assertFalse(d.feed("junk", 1.0))

    def test_module_handle_respects_config_and_fallback_phase(self):
        composer.reset()
        off = {"composer": {"enabled": "false"}}
        self.assertFalse(composer.handle_tap(off, "open"))
        self.assertFalse(any([composer.handle_tap(off, "down", now=0.0),
                              composer.handle_tap(off, "up", now=0.05),
                              composer.handle_tap(off, "down", now=0.2),
                              composer.handle_tap(off, "up", now=0.25)]))
        on = {}
        self.assertTrue(composer.handle_tap(on, "open"))
        res = [composer.handle_tap(on, p, now=t) for p, t in
               (("down", 0.0), ("up", 0.05), ("down", 0.2), ("up", 0.25))]
        self.assertEqual(res, [False, False, False, True])
        composer.reset()


class TestFastkeyTap(unittest.TestCase):
    def test_tap_commands_build(self):
        for ph in ("down", "up", "open"):
            self.assertEqual(fastkey.build(["tap", ph]),
                             {"cmd": "tap", "phase": ph})

    def test_unknown_still_errors(self):
        self.assertIsNone(fastkey.build(["tap"]))
        self.assertIsNone(fastkey.build(["tap", "sideways"]))
        self.assertIsNone(fastkey.build(["nonsense"]))
        self.assertEqual(fastkey.build(["interrupt"]), {"cmd": "interrupt"})


RUNNER = ["/usr/bin/python3", "/opt/wisp/wisp/fastkey.py", "--sock", "/s"]


class FakeBinds:
    """Stands in for the hypr module's bind(); records every call."""

    def __init__(self, fail_lone=False, fail_fallback=False):
        self.calls = []
        self.fail_lone = fail_lone
        self.fail_fallback = fail_fallback

    def bind(self, chord, action, **kw):
        self.calls.append((chord, list(action), kw))
        lone = kw.get("lone")
        if lone and self.fail_lone:
            raise hypr.HyprError("bind_clash", chord)
        if not lone and self.fail_fallback:
            raise hypr.HyprError("bind_clash", chord)
        return f"wisp:{len(self.calls)}"


class TestInstall(unittest.TestCase):
    def test_installs_press_and_release_lone_control(self):
        fb = FakeBinds()
        res = composer.install({}, RUNNER, fb)
        self.assertEqual(res["mode"], "double-ctrl")
        self.assertEqual(len(fb.calls), 2)
        (c1, a1, k1), (c2, a2, k2) = fb.calls
        self.assertEqual(a1[-2:], ["tap", "down"])
        self.assertEqual(a2[-2:], ["tap", "up"])
        for c, k in ((c1, k1), (c2, k2)):
            self.assertEqual(c.upper(), "CONTROL")
            self.assertTrue(k["lone"] and k["non_consuming"])
        self.assertFalse(k1.get("release"))
        self.assertTrue(k2["release"])

    def test_falls_back_to_configured_chord_when_binds_fail(self):
        fb = FakeBinds(fail_lone=True)
        cfg = {"composer": {"fallback_chord": "SUPER + SHIFT + K"}}
        res = composer.install(cfg, RUNNER, fb)
        self.assertEqual(res["mode"], "chord")
        chord, action, kw = fb.calls[-1]
        self.assertEqual(chord, "SUPER + SHIFT + K")
        self.assertEqual(action[-2:], ["tap", "open"])
        self.assertFalse(kw.get("lone"))

    def test_half_installed_pair_is_removed_before_fallback(self):
        fb = FakeBinds()
        removed = []
        orig = fb.bind

        def bind(chord, action, **kw):
            if kw.get("release"):
                raise hypr.HyprError("eval_failed", "x")
            return orig(chord, action, **kw)
        fb.bind = bind
        fb.unbind = removed.append
        res = composer.install({}, RUNNER, fb)
        self.assertEqual(res["mode"], "chord")
        self.assertEqual(len(removed), 1)

    def test_nothing_when_both_fail_or_disabled(self):
        fb = FakeBinds(fail_lone=True, fail_fallback=True)
        self.assertEqual(composer.install({}, RUNNER, fb)["mode"], "none")
        fb = FakeBinds()
        res = composer.install({"composer": {"enabled": "false"}},
                               RUNNER, fb)
        self.assertEqual(res["mode"], "none")
        self.assertEqual(fb.calls, [])

    def test_empty_fallback_chord_means_no_fallback(self):
        fb = FakeBinds(fail_lone=True)
        res = composer.install({"composer": {"fallback_chord": ""}},
                               RUNNER, fb)
        self.assertEqual(res["mode"], "none")


def _load_wispd():
    path = str(pathlib.Path(__file__).resolve().parent.parent / "wispd")
    loader = importlib.machinery.SourceFileLoader("wispd_composer", path)
    spec = importlib.util.spec_from_loader("wispd_composer", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TestDaemonPath(unittest.TestCase):
    def setUp(self):
        from wisp import cancel, state as state_mod
        composer.reset()
        self.addCleanup(composer.reset)
        self.w = _load_wispd()
        self.bus = state_mod.StateBus(
            state_file=pathlib.Path(tempfile.mkdtemp()) / "state.json")
        self.addCleanup(self.bus.close)
        self.ctl = {"stop": threading.Event(), "busy": threading.Event(),
                    "interrupt": threading.Event(),
                    "choice_event": threading.Event(), "choice_pick": "",
                    "broker": cancel.PromptBroker(),
                    "rec_lock": threading.Lock(), "rec": None,
                    "token": cancel.CancelToken()}
        raw = self.w._handler(self.bus, {}, self.ctl)
        peer = {"pid": os.getpid(),
                "uid": getattr(os, "getuid", lambda: 0)()}
        self.h = lambda cmd: raw(cmd, peer)
        self.events = []
        self.bus.emit_event = lambda ev, **d: self.events.append((ev, d))

    def _taps(self, seq, times):
        clock = mock.Mock()
        clock.monotonic.side_effect = times   # only composer reads this
        with mock.patch.object(composer, "time", clock):
            return [self.h({"cmd": "tap", "phase": p}) for p in seq]

    def test_double_tap_over_ipc_emits_an_open_event(self):
        outs = self._taps(("down", "up", "down", "up"),
                          [0.0, 0.05, 0.2, 0.25])
        self.assertEqual([o["opened"] for o in outs],
                         [False, False, False, True])
        self.assertEqual(self.events, [("composer", {"action": "open"})])

    def test_tap_while_recording_is_ignored(self):
        self.ctl["rec"] = {"t0": 0}
        outs = self._taps(("down", "up", "down", "up"),
                          [0.0, 0.05, 0.2, 0.25])
        self.assertEqual([o["opened"] for o in outs], [False] * 4)
        self.assertEqual(self.events, [])

    def test_fallback_open_phase_opens(self):
        self.assertTrue(self.h({"cmd": "tap", "phase": "open"})["opened"])
        self.assertEqual(self.events, [("composer", {"action": "open"})])

    def test_open_prefetches_context_for_the_typed_question(self):
        # review #3: the submitted `ask` takes ctl["spec"] like a spoken
        # turn, so the composer's question gets the window text too
        old, new = mock.Mock(), mock.Mock()
        self.ctl["spec"] = old
        spec = mock.Mock()
        spec.start.return_value = new
        with mock.patch.object(self.w.pipeline, "speculative_context",
                               return_value=spec):
            self._taps(("down", "up", "down", "up"), [0.0, 0.05, 0.2, 0.25])
        old.cancel.assert_called_once()
        self.assertIs(self.ctl["spec"], new)

    def test_no_prefetch_without_an_open(self):
        with mock.patch.object(self.w.pipeline,
                               "speculative_context") as sc:
            self._taps(("down", "up"), [0.0, 0.05])
        sc.assert_not_called()
        self.assertNotIn("spec", self.ctl)

    def test_bad_phase_is_an_error(self):
        self.assertFalse(self.h({"cmd": "tap", "phase": "sideways"})["ok"])

    def test_typed_question_runs_the_same_turn_path_as_voice(self):
        seen = []
        done = threading.Event()

        def fake(*a, **k):
            seen.append(a)
            done.set()
        with mock.patch.object(self.w, "_run_listen", side_effect=fake):
            out = self.h({"cmd": "ask", "text": "what is  this page?"})
            self.assertTrue(done.wait(2))
        self.assertEqual(out, {"ok": True, "asked": True})
        st, cfg, ctl, wav, spans, tid, typed = seen[0]
        self.assertIs(ctl, self.ctl)   # the one daemon control block
        self.assertIsNone(wav)         # typed: no audio, same turn runner
        self.assertEqual(typed, "what is this page?")
        self.assertEqual(tid, self.bus.current_turn())



class TestComposerWindow(unittest.TestCase):
    """The composer types in its own window; the overlay never takes keys."""

    def read(self, name):
        return (pathlib.Path(__file__).resolve().parents[1]
                / "shell-plugin" / name).read_text()

    def test_window_takes_keyboard_only_while_loaded_open(self):
        win = self.read("ComposerWindow.qml")
        self.assertIn("WlrKeyboardFocus.Exclusive", win)
        self.assertIn('namespace: "wisp-composer"', win)
        host = self.read("Companion.qml")
        self.assertIn("active: root.svc !== null && root.composerOpen", host)
        self.assertIn("onClosed: root.composerOpen = false", host)
        self.assertNotIn("Composer {", host)

if __name__ == "__main__":
    unittest.main()
