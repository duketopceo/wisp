#!/usr/bin/env python3
"""U13: the speech provider seam and its metric harness. Fakes only; no
provider call, no network."""
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from wisp import voice_provider as vp  # noqa: E402
from fakes.voice import FakeClock, FakeProvider  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "voice_provider_eval", ROOT / "scripts" / "voice_provider_eval.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)

WAVS = sorted((ROOT / "tests" / "fixtures" / "turns").glob("*.wav"))
ALT_CFG = {"voice": {"alt_provider": "alt"}}


class Selection(unittest.TestCase):
    def tearDown(self):
        vp.unregister("alt")

    def _sel(self, cfg, direction="tts", key="k"):
        return vp.select(cfg, direction, resolve_key=lambda ref: key)

    def test_off_by_default(self):
        vp.register(FakeProvider("alt"))
        p, why = self._sel({})
        self.assertEqual((p.name, why), ("groq", "default"))

    def test_alt_chosen_only_when_named_and_usable(self):
        vp.register(FakeProvider("alt", key_ref="ALT_KEY"))
        p, why = self._sel(ALT_CFG)
        self.assertEqual((p.name, why), ("alt", "alt: alt"))

    def test_missing_key_falls_back(self):
        vp.register(FakeProvider("alt", key_ref="ALT_KEY"))
        p, why = self._sel(ALT_CFG, key="")
        self.assertEqual(p.name, "groq")
        self.assertIn("no key", why)

    def test_missing_capability_falls_back(self):
        vp.register(FakeProvider("alt", caps=vp.Capabilities(stt=True)))
        p, why = self._sel(ALT_CFG, "tts")
        self.assertEqual(p.name, "groq")
        self.assertIn("no tts", why)
        self.assertEqual(self._sel(ALT_CFG, "stt")[0].name, "alt")

    def test_unregistered_name_falls_back(self):
        p, why = self._sel(ALT_CFG)
        self.assertEqual(p.name, "groq")
        self.assertIn("not registered", why)

    def test_no_alternative_ships(self):
        self.assertEqual(vp._REGISTRY, {})

    def test_default_key_ref_is_the_stt_key(self):
        self.assertEqual(vp.GroqProvider({}).key_ref, "GROQ_API_KEY")

    def test_select_makes_no_provider_call(self):
        alt = FakeProvider("alt")
        vp.register(alt)
        self._sel(ALT_CFG)
        self.assertEqual(alt.calls, [])


class Harness(unittest.TestCase):
    def test_fixtures_exist(self):
        self.assertTrue(WAVS)

    def test_fake_report_fields_and_numbers(self):
        clock = FakeClock()
        rep = ev.run(FakeProvider(stt_ms=100, tts_ms=250, clock=clock),
                     WAVS, clock=clock)
        self.assertEqual(rep["stt"]["n"], len(WAVS))
        self.assertEqual(rep["stt"]["p50_ms"], 100.0)
        self.assertEqual(rep["tts_start"]["p90_ms"], 250.0)
        self.assertEqual(rep["errors"], 0)
        self.assertGreater(rep["audio_s"], 0)

    def test_same_fields_for_any_provider(self):
        clock = FakeClock()
        a = ev.run(FakeProvider("a", clock=clock), WAVS, clock=clock)
        b = ev.run(FakeProvider("b", clock=clock, stt_ms=50), WAVS,
                   clock=clock)
        self.assertEqual(set(a), set(b))
        self.assertEqual(set(a["stt"]), set(b["stt"]))
        self.assertEqual(a["provider"], "a")

    def test_errors_are_counted_not_raised(self):
        rep = ev.run(FakeProvider(fail=True), WAVS)
        self.assertEqual(rep["errors"], len(WAVS) + len(ev.SENTENCES))
        self.assertIsNone(rep["stt"]["p50_ms"])

    def test_cost_needs_both_prices(self):
        clock = FakeClock()
        p = FakeProvider(clock=clock)
        self.assertIsNone(ev.run(p, WAVS, clock=clock)["cost_usd"])
        rep = ev.run(p, WAVS, clock=clock, price={
            "stt_usd_per_audio_min": 0.6, "tts_usd_per_1k_chars": 40.0})
        self.assertGreater(rep["cost_usd"], 0)

    def test_capability_gates_each_direction(self):
        rep = ev.run(FakeProvider(caps=vp.Capabilities(tts=True)), WAVS)
        self.assertEqual(rep["stt"]["n"], 0)
        self.assertGreater(rep["tts_start"]["n"], 0)

    def test_real_provider_needs_live_flag(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(ev.main(["--provider", "groq"]), 2)

    def test_default_cli_runs_the_fake(self):
        with mock.patch("builtins.print") as pr:
            self.assertEqual(ev.main(["--json"]), 0)
        self.assertIn('"provider": "fake"', pr.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
