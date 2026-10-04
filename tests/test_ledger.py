#!/usr/bin/env python3
"""W14: usage ledger, spend caps, brain fail-closed, state field, CLI.
Loopback fakes only: no network, no paid call, no live daemon."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import fakes  # noqa: E402
from wisp import brain, errors_codes, ledger, state as state_mod  # noqa: E402
from cli_env import CliEnv  # noqa: E402

D1 = dt.datetime(2026, 10, 4, 10, 0, 0)
D1_LATE = dt.datetime(2026, 10, 4, 23, 59, 59)
D2 = dt.datetime(2026, 10, 5, 0, 0, 1)
NEXT_MONTH = dt.datetime(2026, 11, 1, 9, 0, 0)
ASK = [{"role": "user", "content": "hi"}]


def chat_calls(fake):
    return len([c for c in fake.calls
                if c["path"].endswith("/chat/completions")])


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.path = pathlib.Path(self._td.name) / "usage.jsonl"

    def rec(self, usd, now=D1, **kw):
        kw.setdefault("provider", "openrouter")
        kw.setdefault("model", "m")
        kw.setdefault("paid", True)
        return ledger.record(usd=usd, tokens_in=10, tokens_out=5,
                             now=now, path=self.path, **kw)


class TestAccounting(LedgerCase):
    def test_local_counted_at_zero_cost(self):
        row = ledger.record("mlx", "ornith", 100, 40, paid=False,
                            now=D1, path=self.path)
        self.assertEqual(row["usd"], 0.0)
        t = ledger.totals(now=D1, path=self.path)
        self.assertEqual(t["today_usd"], 0.0)
        self.assertEqual(t["calls_today"], 1)
        self.assertEqual(t["tokens_in"], 100)
        self.assertEqual(t["tokens_out"], 40)

    def test_reported_cost_wins_over_price_table(self):
        row = ledger.record("openrouter", "google/gemini-2.5-flash",
                            1_000_000, 0, usd=0.0123, paid=True,
                            now=D1, path=self.path)
        self.assertAlmostEqual(row["usd"], 0.0123)

    def test_price_table_when_no_reported_cost(self):
        want = ledger.PRICES["meta-llama/llama-4-maverick"]
        row = ledger.record("openrouter", "meta-llama/llama-4-maverick",
                            1_000_000, 1_000_000, paid=True, now=D1,
                            path=self.path)
        self.assertAlmostEqual(row["usd"], want[0] + want[1])

    def test_unknown_paid_model_priced_at_max(self):
        row = ledger.record("openrouter", "who/knows", 1_000_000, 0,
                            paid=True, now=D1, path=self.path)
        self.assertAlmostEqual(row["usd"], ledger.UNKNOWN_PRICE[0])
        self.assertGreaterEqual(
            ledger.UNKNOWN_PRICE[0],
            max(p[0] for p in ledger.PRICES.values()))

    def test_per_model_breakdown(self):
        self.rec(0.5, model="a")
        self.rec(0.25, model="a")
        self.rec(0.0, model="ornith", provider="mlx", paid=False)
        by = ledger.totals(now=D1, path=self.path)["by_model"]
        self.assertAlmostEqual(by["openrouter:a"]["usd"], 0.75)
        self.assertEqual(by["openrouter:a"]["calls"], 2)
        self.assertEqual(by["mlx:ornith"]["calls"], 1)

    def test_malformed_lines_ignored(self):
        self.rec(0.1)
        with self.path.open("a") as f:
            f.write("not json\n[1]\n")
        self.assertAlmostEqual(
            ledger.totals(now=D1, path=self.path)["today_usd"], 0.1)

    def test_concurrent_writers_lose_nothing(self):
        def work():
            for _ in range(25):
                self.rec(0.01)
        ts = [threading.Thread(target=work) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        t = ledger.totals(now=D1, path=self.path)
        self.assertEqual(t["calls_today"], 200)
        self.assertAlmostEqual(t["today_usd"], 2.0, places=6)

    def test_record_is_inert_until_activated(self):
        self.assertFalse(ledger.ACTIVE)
        self.assertIsNone(ledger.note("mlx", "m", False, {}))


class TestRollover(LedgerCase):
    def test_new_local_day_resets_today_not_month(self):
        self.rec(1.0, now=D1_LATE)
        t = ledger.totals(now=D2, path=self.path)
        self.assertEqual(t["today_usd"], 0.0)
        self.assertAlmostEqual(t["month_usd"], 1.0)

    def test_new_month_resets_month(self):
        self.rec(1.0, now=D1)
        t = ledger.totals(now=NEXT_MONTH, path=self.path)
        self.assertEqual(t["month_usd"], 0.0)

    def test_cap_reopens_at_midnight(self):
        cfg = {"budget": {"daily_usd": "1.00"}}
        self.rec(1.0, now=D1_LATE)
        self.assertFalse(ledger.paid_allowed(cfg, D1_LATE, self.path))
        self.assertTrue(ledger.paid_allowed(cfg, D2, self.path))


class TestCaps(LedgerCase):
    cfg = {"budget": {"daily_usd": "1.00", "monthly_usd": "5.00"}}

    def test_under_at_over_daily(self):
        self.rec(0.99)
        self.assertTrue(ledger.paid_allowed(self.cfg, D1, self.path))
        self.rec(0.01)  # exactly at the cap
        self.assertFalse(ledger.paid_allowed(self.cfg, D1, self.path))
        self.rec(0.5)   # over
        self.assertFalse(ledger.paid_allowed(self.cfg, D1, self.path))

    def test_monthly_cap_blocks_after_daily_reset(self):
        for day in range(1, 5):
            self.rec(1.25, now=dt.datetime(2026, 10, day, 12))
        st = ledger.status(self.cfg, D2, self.path)
        self.assertEqual(st["today_usd"], 0.0)
        self.assertTrue(st["blocked"])
        self.assertEqual(st["reason"], "monthly_cap")

    def test_no_cap_means_unlimited(self):
        self.rec(1000.0)
        cfg = {"budget": {"daily_usd": "", "monthly_usd": ""}}
        self.assertTrue(ledger.paid_allowed(cfg, D1, self.path))

    def test_defaults_are_8_daily_160_monthly(self):
        self.assertEqual(ledger.caps({}), (8.0, 160.0))
        self.rec(7.99)
        self.assertTrue(ledger.paid_allowed({}, D1, self.path))
        self.rec(0.01)
        self.assertFalse(ledger.paid_allowed({}, D1, self.path))

    def test_brain_daily_cap_alias_and_precedence(self):
        self.assertEqual(ledger.caps({"brain": {"daily_cap_usd": "10"}}),
                         (10.0, 160.0))
        both = {"brain": {"daily_cap_usd": "10"},
                "budget": {"daily_usd": "3"}}
        self.assertEqual(ledger.caps(both)[0], 3.0)

    def test_primary_policy(self):
        self.rec(1.0)
        cfg = {"budget": {"daily_usd": "1.00"}}
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path))
        self.assertTrue(ledger.paid_allowed(cfg, D1, self.path,
                                            primary=True))
        cfg["budget"]["gate_primary"] = "true"
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path,
                                             primary=True))

    def test_unreadable_ledger_primary_allowed_unless_gated(self):
        self.path.mkdir()
        cfg = {"budget": {"daily_usd": "1"}}
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path))
        self.assertTrue(ledger.paid_allowed(cfg, D1, self.path,
                                            primary=True))
        cfg["budget"]["gate_primary"] = "true"
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path,
                                             primary=True))

    def test_legacy_spend_jsonl_counts(self):
        legacy = self.path.with_name("spend.jsonl")
        legacy.write_text(json.dumps(
            {"ts": D1.timestamp(), "model": "g", "cost": 0.75,
             "prompt_tokens": 100, "completion_tokens": 10}) + "\n"
            + json.dumps({"ts": D2.timestamp(), "cost": 5}) + "\n")
        self.rec(0.25)
        t = ledger.totals(now=D1, path=self.path)
        self.assertAlmostEqual(t["today_usd"], 1.0)
        self.assertEqual(t["calls_today"], 2)
        self.assertEqual(t["tokens_in"], 110)
        cfg = {"budget": {"daily_usd": "1.00"}}
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path))

    def test_gate_primary_key_accepted_by_schema(self):
        from wisp import settings_schema as S
        self.assertEqual(S.problem("budget.gate_primary", "true"), "")
        self.assertEqual(S.problem("budget.gate_primary", "x"), "choice")
        # the legacy alias is not a Panel field but is writable
        self.assertEqual(S.problem("brain.daily_cap_usd", "10"), "")
        self.assertIsNone(S.field("brain.daily_cap_usd"))

    def test_zero_cap_blocks_all_paid(self):
        cfg = {"budget": {"daily_usd": "0"}}
        self.assertFalse(ledger.paid_allowed(cfg, D1, self.path))

    def test_unreadable_ledger_fails_closed(self):
        self.path.mkdir()  # a directory: open() raises, not ENOENT
        self.assertFalse(ledger.paid_allowed(self.cfg, D1, self.path))

    def test_missing_ledger_is_fine(self):
        self.assertTrue(ledger.paid_allowed(self.cfg, D1, self.path))

    def test_local_spend_never_counts(self):
        for _ in range(5):
            ledger.record("mlx", "ornith", 9000, 9000, usd=9.0,
                          paid=False, now=D1, path=self.path)
        self.assertTrue(ledger.paid_allowed(self.cfg, D1, self.path))

    def test_bad_cap_value_ignored(self):
        cfg = {"budget": {"daily_usd": "lots"}}
        self.assertEqual(ledger.caps(cfg), (None, 160.0))


class TestStateField(LedgerCase):
    def test_shape_matches_w23(self):
        self.rec(0.12)
        f = ledger.spend_field({"budget": {"daily_usd": "5"}}, D1,
                               self.path)
        self.assertAlmostEqual(f["today_usd"], 0.12)
        self.assertEqual(f["cap_usd"], 5.0)
        self.assertFalse(f["blocked"])

    def test_cap_null_when_unset(self):
        f = ledger.spend_field({"budget": {"daily_usd": ""}}, D1, self.path)
        self.assertIsNone(f["cap_usd"])

    def test_state_snapshot_carries_spend(self):
        with tempfile.TemporaryDirectory() as td:
            bus = state_mod.StateBus(
                state_file=pathlib.Path(td) / "s.json", autostart=False)
            self.assertEqual(bus.snapshot()["spend"], {})
            bus.publish(None, spend={"today_usd": 0.5, "cap_usd": 2.0})
            raw = json.loads((pathlib.Path(td) / "s.json").read_text())
            self.assertEqual(raw["spend"]["today_usd"], 0.5)
            self.assertEqual(raw["spend"]["cap_usd"], 2.0)
            bus.close()

    def test_health_hook_reports_cap(self):
        cfg = {"budget": {"daily_usd": "1"}}
        hook = ledger.health_hook(cfg, path=self.path, clock=lambda: D1)
        self.assertEqual(hook()["ok"], True)
        self.rec(1.0)
        res = hook()
        self.assertFalse(res["ok"])
        self.assertEqual(res["code"], "budget_exceeded")

    def test_publisher_pushes_on_record(self):
        seen = []

        class Bus:
            def publish(self, tid, **f):
                seen.append(f)
        cfg = {"budget": {"daily_usd": "5"}}
        with mock.patch.object(ledger, "ACTIVE", True), \
                mock.patch.object(ledger, "path", lambda: self.path):
            ledger.attach(Bus(), cfg)
            self.addCleanup(ledger.attach, None, None)
            ledger.note("openrouter", "m", True, {"cost": 0.4,
                        "prompt_tokens": 3, "completion_tokens": 2})
        self.assertAlmostEqual(seen[-1]["spend"]["today_usd"], 0.4)


class TestBrainIntegration(LedgerCase):
    def cfg(self, local_url, paid_url, **budget):
        return {"brain": {"default": "paid:m1", "fallback": "loc:m0",
                          "allow_paid": "true"},
                "budget": budget,
                "brain.paid": {"kind": "openai_compat", "paid": "true",
                               "base_url": paid_url + "/v1",
                               "key_env": "", "tools": "true"},
                "brain.loc": {"kind": "openai_compat",
                              "base_url": local_url + "/v1",
                              "key_env": "", "tools": "true"}}

    def run_chat(self, cfg, paid, loc):
        with mock.patch.object(ledger, "ACTIVE", True), \
                mock.patch.object(ledger, "path", lambda: self.path):
            return brain.chat(ASK, cfg)

    def test_local_call_recorded_with_usage(self):
        usage = {"prompt_tokens": 12, "completion_tokens": 7}
        with fakes.FakeBrain({"responses": [
                {"content": "ok", "usage": usage}]}) as loc, \
                fakes.FakeBrain() as paid:
            cfg = self.cfg(loc.url, paid.url)
            cfg["brain"]["default"] = "loc:m0"
            self.run_chat(cfg, paid, loc)
        t = ledger.totals(path=self.path)
        self.assertEqual(t["tokens_in"], 12)
        self.assertEqual(t["tokens_out"], 7)
        self.assertEqual(t["month_usd"], 0.0)

    def test_paid_cost_taken_from_response(self):
        usage = {"prompt_tokens": 1, "completion_tokens": 1,
                 "cost": 0.0042}
        with fakes.FakeBrain() as loc, fakes.FakeBrain({"responses": [
                {"content": "ok", "usage": usage}]}) as paid:
            self.run_chat(self.cfg(loc.url, paid.url, daily_usd="1"),
                          paid, loc)
        self.assertAlmostEqual(
            ledger.totals(path=self.path)["month_usd"], 0.0042)

    def test_cap_reached_primary_still_runs_by_default(self):
        self.rec(1.0, now=dt.datetime.now())
        with fakes.FakeBrain() as loc, fakes.FakeBrain({"responses": [
                {"content": "paid"}]}) as paid:
            res = self.run_chat(
                self.cfg(loc.url, paid.url, daily_usd="1.00"), paid, loc)
            self.assertEqual(res["provider"], "paid")

    def test_cap_reached_skips_paid_fallback(self):
        self.rec(1.0, now=dt.datetime.now())
        with fakes.FakeBrain({"responses": [{"content": "local"}]}) as loc, \
                fakes.FakeBrain() as paid:
            cfg = self.cfg(loc.url, paid.url, daily_usd="1.00")
            cfg["brain"]["default"] = "loc:m0"
            cfg["brain"]["fallback"] = "paid:m1"
            self.run_chat(cfg, paid, loc)
            self.assertEqual(chat_calls(paid), 0)

    def test_gate_primary_skips_paid_primary_local_still_answers(self):
        self.rec(1.0, now=dt.datetime.now())
        with fakes.FakeBrain({"responses": [{"content": "local"}]}) as loc, \
                fakes.FakeBrain() as paid:
            res = self.run_chat(
                self.cfg(loc.url, paid.url, daily_usd="1.00",
                         gate_primary="true"), paid, loc)
            self.assertEqual(res["content"], "local")
            self.assertEqual(res["provider"], "loc")
            self.assertEqual(chat_calls(paid), 0)

    def test_under_cap_paid_is_used(self):
        self.rec(0.5, now=dt.datetime.now())
        with fakes.FakeBrain() as loc, fakes.FakeBrain({"responses": [
                {"content": "paid"}]}) as paid:
            res = self.run_chat(
                self.cfg(loc.url, paid.url, daily_usd="1.00"), paid, loc)
            self.assertEqual(res["provider"], "paid")

    def test_only_paid_chain_at_cap_raises_budget_exceeded(self):
        self.rec(1.0, now=dt.datetime.now())
        with fakes.FakeBrain() as loc, fakes.FakeBrain() as paid:
            cfg = self.cfg(loc.url, paid.url, daily_usd="1.00",
                           gate_primary="true")
            cfg["brain"]["fallback"] = ""
            with self.assertRaises(errors_codes.WispError) as cm:
                self.run_chat(cfg, paid, loc)
            self.assertEqual(cm.exception.code, "budget_exceeded")
            self.assertEqual(chat_calls(paid), 0)

    def test_one_ledger_row_per_call(self):
        with fakes.FakeBrain() as loc, fakes.FakeBrain({"responses": [
                {"content": "ok", "usage": {"prompt_tokens": 1,
                                            "completion_tokens": 1,
                                            "cost": 0.01}}]}) as paid:
            self.run_chat(self.cfg(loc.url, paid.url, daily_usd="1"),
                          paid, loc)
        self.assertEqual(
            ledger.totals(path=self.path)["calls_today"], 1)

    def test_budget_ok_hook_uses_ledger(self):
        self.rec(2.0, now=dt.datetime.now())
        with mock.patch.object(ledger, "path", lambda: self.path):
            self.assertFalse(brain.budget_ok(
                {"budget": {"daily_usd": "1"}}))
            self.assertTrue(brain.budget_ok({}))


class TestCli(unittest.TestCase):
    def seed(self, env, rows):
        env.data.mkdir(parents=True, exist_ok=True)
        (env.data / "usage.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def test_json_shape_and_values(self):
        today = dt.date.today().isoformat()
        with CliEnv() as env:
            self.seed(env, [
                {"ts": today + "T10:00:00", "provider": "openrouter",
                 "model": "a", "in": 10, "out": 5, "usd": 0.25,
                 "paid": True},
                {"ts": today + "T11:00:00", "provider": "mlx",
                 "model": "ornith", "in": 100, "out": 50, "usd": 0.0,
                 "paid": False}])
            code, out, err = env.run(["spend", "--json"])
            self.assertEqual(code, 0, err)
            j = json.loads(out)["data"]
            self.assertAlmostEqual(j["today_usd"], 0.25)
            self.assertEqual(j["calls_today"], 2)
            self.assertIn("month_usd", j)
            self.assertIn("monthly_cap_usd", j)
            self.assertIn("models", j)
            self.assertFalse(j["blocked"])

    def test_text_output_lists_models_and_caps(self):
        today = dt.date.today().isoformat()
        with CliEnv() as env:
            self.seed(env, [{"ts": today + "T10:00:00",
                             "provider": "openrouter", "model": "a",
                             "in": 1, "out": 1, "usd": 0.5,
                             "paid": True}])
            code, out, err = env.run(["spend"])
            self.assertEqual(code, 0, err)
            self.assertIn("openrouter:a", out)
            self.assertIn("$0.50", out)
            self.assertIn("daily cap", out)

    def test_blocked_when_cap_reached(self):
        today = dt.date.today().isoformat()
        with CliEnv() as env:
            cfgdir = env.home / ".config" / "wisp"
            cfgdir.mkdir(parents=True, exist_ok=True)
            (cfgdir / "config.toml").write_text(
                '[budget]\ndaily_usd = "0.50"\n')
            self.seed(env, [{"ts": today + "T10:00:00", "usd": 0.5,
                             "model": "a", "paid": True}])
            j = json.loads(env.run(["spend", "--json"])[1])["data"]
            self.assertTrue(j["blocked"])
            self.assertEqual(j["cap_usd"], 0.5)

    def test_help_mentions_spend(self):
        with CliEnv() as env:
            code, out, err = env.run(["spend", "--help"])
            self.assertEqual(code, 0)
            self.assertIn("spend", out)


if __name__ == "__main__":
    unittest.main()
