"""B21: ask chips on a quick tap: per-app asks, first-week window, no
screenshot for a tap, state field, and the chip's text runs as a normal turn."""
import datetime as dt
import importlib.machinery
import importlib.util
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import chips, config, context, skills, stage_capture, state  # noqa: E402

SEED = ROOT / "wisp" / "skills_seed"
UTC = dt.timezone.utc


def _wispd():
    path = str(ROOT / "wispd")
    loader = importlib.machinery.SourceFileLoader("wispd_chips", path)
    spec = importlib.util.spec_from_loader("wispd_chips", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


class Fx(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        p = mock.patch.object(config, "DATA_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)


class Asks(unittest.TestCase):
    def test_every_app_seed_has_three_short_asks(self):
        n = 0
        for f in sorted((SEED / "apps").glob("*/SKILL.md")):
            meta = skills._frontmatter(f.read_text())
            asks = skills.asks_field(meta.get("asks"))
            self.assertEqual(len(asks), 3, f.parent.name)
            for a in asks:
                self.assertLessEqual(len(a), 61)
                self.assertTrue(a.endswith("?"), a)
            n += 1
        self.assertGreaterEqual(n, 15)

    def test_asks_field_parsing(self):
        self.assertEqual(skills.asks_field("a b ; c ;; a b; d; e"),
                         ["a b?", "c?", "d?"])
        self.assertEqual(skills.asks_field(""), [])
        self.assertEqual(skills.asks_field("x" * 80), [])

    def test_the_focused_app_gets_its_own_asks(self):
        a = chips.asks_for("kitty", skills_dir=SEED)
        self.assertEqual(a[0], "How do I open a new tab?")
        self.assertEqual(chips.asks_for("Chromium", skills_dir=SEED)[0],
                         "How do I open DevTools?")

    def test_an_unknown_app_gets_three_generic_asks(self):
        self.assertEqual(chips.asks_for("some-unknown-app", skills_dir=SEED),
                         chips.GENERIC)
        self.assertEqual(chips.asks_for("", skills_dir=SEED), chips.GENERIC)
        self.assertEqual(len(chips.GENERIC), 3)


class Window(Fx):
    CFG = {"chips": {"enabled": "true", "days": "7"}}

    def test_off_means_off(self):
        cfg = {"chips": {"enabled": "false"}}
        self.assertFalse(chips.in_window(cfg))
        self.assertIsNone(chips.build(cfg, "kitty"))

    def test_first_week_only_counted_from_the_first_tap(self):
        t0 = dt.datetime(2026, 10, 1, 9, tzinfo=UTC)
        self.assertTrue(chips.in_window(self.CFG, t0))            # no tap yet
        self.assertFalse((self.tmp / "chips.json").exists())      # peek only
        self.assertIsNotNone(chips.build(self.CFG, "kitty", now=t0,
                                         skills_dir=SEED))
        self.assertTrue((self.tmp / "chips.json").exists())
        day6 = t0 + dt.timedelta(days=6, hours=23)
        day8 = t0 + dt.timedelta(days=8)
        self.assertIsNotNone(chips.build(self.CFG, "kitty", now=day6,
                                         skills_dir=SEED))
        self.assertIsNone(chips.build(self.CFG, "kitty", now=day8))
        self.assertFalse(chips.armed(self.CFG, day8))

    def test_days_setting_and_bad_values(self):
        self.assertEqual(chips.settings({"chips": {"days": "3"}})["days"], 3)
        self.assertEqual(chips.settings({"chips": {"days": "x"}})["days"], 7)
        self.assertEqual(chips.settings({})["enabled"], True)

    def test_tap_threshold(self):
        self.assertTrue(chips.is_tap(0.1))
        self.assertFalse(chips.is_tap(chips.TAP_MAX_S))
        self.assertFalse(chips.is_tap(1.5))

    def test_payload_shape(self):
        p = chips.build(self.CFG, "kitty", seq=5, skills_dir=SEED)
        self.assertEqual(set(p), {"app", "asks", "seq"})
        self.assertEqual((p["app"], p["seq"], len(p["asks"])), ("kitty", 5, 3))


class NoScreenshotOnATap(Fx):
    def run_press(self, cfg, hold):
        calls = []
        pl = mock.Mock()
        pl.capture_screen.side_effect = lambda: calls.append(1)
        with mock.patch.object(stage_capture, "_pl", lambda: pl), \
                mock.patch.object(context, "windows_map", lambda: ""):
            spec = stage_capture.speculative_context(cfg).start()
            time.sleep(hold)
            spec.cancel()
            time.sleep(0.45)
        return len(calls)

    def test_a_tap_takes_no_screenshot(self):
        cfg = {"chips": {"enabled": "true"}, "agent": {"screenshots": "true"}}
        self.assertEqual(self.run_press(cfg, 0.05), 0)

    def test_a_real_press_still_gets_its_press_time_screenshot(self):
        cfg = {"chips": {"enabled": "true"}, "agent": {"screenshots": "true"}}
        self.assertEqual(self.run_press(cfg, 0.4), 1)

    def test_with_chips_off_the_capture_starts_at_once(self):
        cfg = {"chips": {"enabled": "false"}, "agent": {"screenshots": "true"}}
        self.assertEqual(self.run_press(cfg, 0.05), 1)

    def test_speculative_delay_never_runs_a_cancelled_gatherer(self):
        ran = []
        s = context.Speculative({"x": lambda: ran.append(1) or 1},
                                delays={"x": 0.2}).start()
        s.cancel()
        time.sleep(0.35)
        self.assertEqual(ran, [])
        self.assertIsNone(s.take("x"))
        s2 = context.Speculative({"x": lambda: 7}, delays={"x": 0.05}).start()
        self.assertEqual(s2.take("x", wait=1.0), 7)


class StateField(unittest.TestCase):
    def make(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        f = pathlib.Path(td.name) / "state.json"
        bus = state.StateBus(state_file=f)
        self.addCleanup(bus.close)
        return bus, f

    def test_chips_ride_the_done_transition_and_leave_on_listening(self):
        bus, f = self.make()
        t = bus.begin_turn()
        self.assertIsNone(json.loads(f.read_text())["chips"])
        payload = {"app": "kitty", "asks": ["a?", "b?", "c?"], "seq": 1}
        bus.publish(t, status="done", result="", chips=payload)
        self.assertEqual(json.loads(f.read_text())["chips"], payload)
        t2 = bus.begin_turn()
        bus.publish(t2, status="listening")
        self.assertIsNone(json.loads(f.read_text())["chips"])

    def test_the_contract_documents_chips(self):
        self.assertIn('"chips"', (ROOT / "docs/IPC_CONTRACT.md").read_text())


class TapPath(Fx):
    def setUp(self):
        super().setUp()
        self.w = _wispd()
        self.w.dlog = lambda *_a, **_k: None

    def run_tap(self, held, cfg=None, app="kitty"):
        cfg = cfg or {"chips": {"enabled": "true", "days": "7"}}
        with mock.patch.object(self.w.pipeline, "active_window",
                               return_value={"class": app}):
            return self.w._tap_chips(cfg, held)

    def test_a_quick_tap_returns_chips_for_the_focused_app(self):
        out = self.run_tap(0.1)
        self.assertEqual(out["chips"]["app"], "kitty")
        self.assertEqual(len(out["chips"]["asks"]), 3)

    def test_a_long_press_or_bounce_returns_nothing(self):
        self.assertEqual(self.run_tap(0.3), {})
        self.assertEqual(self.run_tap(2.0), {})

    def test_setting_off_returns_nothing(self):
        self.assertEqual(self.run_tap(0.1, {"chips": {"enabled": "false"}}), {})

    def test_a_failing_window_read_is_not_a_failed_press(self):
        with mock.patch.object(self.w.pipeline, "active_window",
                               side_effect=OSError("no hypr")):
            self.assertEqual(self.w._tap_chips({"chips": {}}, 0.1), {})

    def test_the_tap_path_never_captures_the_screen(self):
        pl = self.w.pipeline
        with mock.patch.object(pl, "capture_screen") as cap:
            self.run_tap(0.1)
        cap.assert_not_called()


class ChipTextIsANormalTurn(unittest.TestCase):
    def test_the_replay_fixture_says_a_real_chip_ask(self):
        fx = json.loads((ROOT / "tests/fixtures/turns/ask_chip.json")
                        .read_text())
        said = fx["endpoints"]["whisper"]["transcript"]
        asks = chips.asks_for("kitty", skills_dir=SEED)
        self.assertIn(said, [a.lower().rstrip("?") for a in asks])
        self.assertEqual(fx["expect"]["statuses"][-1], "done")
        self.assertEqual(fx["expect"]["brain_calls"], 1)


if __name__ == "__main__":
    unittest.main()
