#!/usr/bin/env python3
"""Gauntlet mode in dev runs (U5): arm profiles, sandbox typing by
window address, skill create/edit, the cumulative spend file and the
named-arm report. The pipeline, the compositor and the brain are fakes;
nothing here touches the desktop, the network or any key."""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
import test_devrun as td  # noqa: E402
from wisp import (config, context, cua_safety, devjudge, devreport,  # noqa: E402
                  devrun, devsession, gauntlet, ledger, policy, trace)
from wisp.tools import system  # noqa: E402

WIN = "0xaaa1"
OTHER = "0xbbb2"


def grant(td_dir, windows=(WIN,), cap=10.0):
    return {"windows": list(windows),
            "spend_file": str(pathlib.Path(td_dir) / "spend.jsonl"),
            "cap_usd": cap}


class GauntletBase(td.Base):
    def setUp(self):
        super().setUp()
        self.focused = WIN
        for obj, name, val in (
                (gauntlet, "focused_address", lambda: self.focused),
                (cua_safety, "sensitive_surface",
                 lambda cfg=None, state=None, window=None: "")):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        self.grant = grant(self.dir)
        self.rcfg = devrun.run_config(self.cfg, "r1", grant=self.grant)

    def profile(self, name, **agents):
        p = self.dir / f"{name}.toml"
        body = "".join(f'{k} = "{v}"\n' for k, v in agents.items())
        p.write_text(f'[brain]\ndefault = "acme:{name}"\n\n[agents]\n{body}')
        return str(p)

    def start(self, profiles, *lines, g=None):
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl, self.tasks(*lines),
                         run_listen=self.fake_run_listen, judge=self.judge,
                         profiles=profiles, grant=g or self.grant)
        if r.get("ok"):
            self.assertTrue(devrun.wait(10))
        return r


class TestSandboxTyping(GauntletBase):
    def test_typing_into_a_registered_window_is_allowed(self):
        with mock.patch.object(trace, "emit") as emit:
            self.assertIsNone(policy.gate("type_text", "hello",
                                          self.rcfg, None))
            self.assertIsNone(policy.gate("key", "enter", self.rcfg, None))
            emit.assert_not_called()

    def test_a_window_the_driver_did_not_spawn_is_refused_and_stops(self):
        self.focused = OTHER           # same class, different address
        with mock.patch.object(trace, "emit") as emit:
            out = policy.gate("type_text", "hello", self.rcfg, None)
        self.assertTrue(out.startswith("REFUSED (gauntlet sandbox"), out)
        self.assertEqual(emit.call_args[0][1], "gate_stop")
        # the runner reads that stop as the task's outcome
        self.assertEqual(devrun.classify("ACTED", [out]), "stopped")

    def test_no_registered_window_refuses_everything(self):
        cfg = devrun.run_config(self.cfg, "r1",
                                grant=grant(self.dir, windows=()))
        out = policy.gate("type_text", "x", cfg, None)
        self.assertIn("no sandbox window", out)

    def test_unreadable_compositor_fails_closed(self):
        with mock.patch.object(gauntlet, "focused_address",
                               side_effect=OSError("no socket")):
            out = policy.gate("key", "enter", self.rcfg, None)
        self.assertIn("cannot read the focused window", out)

    def test_focus_moving_after_the_gate_stops_before_the_keystroke(self):
        self.assertIsNone(policy.gate("type_text", "secret", self.rcfg,
                                      None))
        self.focused = OTHER           # moves between gate and keystroke
        with mock.patch.object(system._cancel, "run") as run, \
                mock.patch.object(trace, "emit") as emit:
            out = system.type_text("secret", self.rcfg)
            key_out = system.key("enter", self.rcfg)
        run.assert_not_called()
        self.assertTrue(out.startswith("REFUSED (gauntlet sandbox"), out)
        self.assertTrue(key_out.startswith("REFUSED (gauntlet sandbox"))
        self.assertEqual(emit.call_args[0][1], "gate_stop")

    def test_typing_stays_denied_outside_a_gauntlet_run(self):
        plain = devrun.run_config(self.cfg, "r1")
        self.assertIn("REFUSED (dev run denies type_text)",
                      policy.gate("type_text", "x", plain, None))
        self.assertIn("type_text", plain["dev"]["deny_tools"])
        self.assertNotIn("type_text", self.rcfg["dev"]["deny_tools"])

    def test_a_confirm_gate_in_a_gauntlet_run_answers_no(self):
        # a sensitive surface is not pre-approved: it reaches the normal
        # gate, and an unattended run has no one to ask
        with mock.patch.object(cua_safety, "sensitive_surface",
                               lambda *a, **k: "stripe"):
            out = policy.gate("type_text", "x", self.rcfg, None)
        self.assertEqual(out, "SKIPPED (type_text needs user confirmation)")

    def test_shell_and_fill_stay_denied(self):
        for tool in ("fill", "shell", "agent_spawn", "memory", "close"):
            self.assertIn(tool, self.rcfg["dev"]["deny_tools"])
        self.assertEqual(self.rcfg["agent"]["allow_shell"], "false")


class TestSkillManage(GauntletBase):
    def test_create_and_edit_run_without_a_confirm(self):
        for arg in ("create|gimp-notes|body", "edit|gimp-notes|body"):
            self.assertIsNone(policy.gate("skill_manage", arg,
                                          self.rcfg, None), arg)

    def test_delete_and_file_ops_are_refused(self):
        for op in ("delete", "write_file", "remove_file"):
            out = policy.gate("skill_manage", f"{op}|gimp-notes", self.rcfg,
                              None)
            self.assertTrue(out.startswith("REFUSED (gauntlet allows"), op)

    def test_skill_manage_stays_denied_without_gauntlet(self):
        plain = devrun.run_config(self.cfg, "r1")
        self.assertIn("REFUSED", policy.gate(
            "skill_manage", "create|x|y", plain, None))

    def test_trajectories_are_on_only_for_gauntlet(self):
        self.assertEqual(self.rcfg["traj"]["enabled"], "true")
        self.assertEqual(
            devrun.run_config(self.cfg, "r1")["traj"]["enabled"], "false")


class TestProfiles(GauntletBase):
    def test_checked_in_profiles_load_and_set_safety_keys(self):
        for name in ("hybrid", "openrouter"):
            label, prof = gauntlet.load_profile(name)
            self.assertEqual(label, name)
            self.assertEqual(prof["brain.openrouter"]["key_env"],
                             "OPENROUTER_API_KEY")
            self.assertGreater(gauntlet.task_stop_usd(prof), 0)
            self.assertNotIn("jev", prof["ground"]["providers"])
        hybrid = gauntlet.load_profile("hybrid")[1]
        self.assertTrue(hybrid["ground"]["vlm_brain"].startswith("ollama:"))

    def test_a_profile_cannot_touch_the_run_owned_sections(self):
        p = self.dir / "bad.toml"
        p.write_text('[dev]\ngauntlet = "true"\n')
        with self.assertRaises(ValueError):
            gauntlet.load_profile(str(p))
        with self.assertRaises(ValueError):
            gauntlet.load_profile("no-such-profile")

    def test_a_profile_cannot_lift_the_shell_switch_or_deny_list(self):
        prof = {"agent": {"allow_shell": "true"},
                "dev": {"deny_tools": ""}}
        c = devrun.run_config(self.cfg, "r1", profile=prof,
                              grant=self.grant)
        self.assertEqual(c["agent"]["allow_shell"], "false")
        self.assertIn("shell", c["dev"]["deny_tools"])

    def test_owner_config_is_never_changed(self):
        before = json.dumps(self.cfg, sort_keys=True)
        devrun.run_config(self.cfg, "r1",
                          profile=gauntlet.load_profile("hybrid")[1],
                          grant=self.grant)
        self.assertEqual(json.dumps(self.cfg, sort_keys=True), before)

    def test_gauntlet_keys_are_safety_keys(self):
        from wisp import ipc
        for k in ("dev.gauntlet", "dev.sandbox_windows",
                  "dev.spend_file", "dev.spend_cap_usd"):
            self.assertTrue(ipc.is_safety_config_key(k), k)


class TestSpend(GauntletBase):
    def test_spend_recorded_by_one_invocation_counts_in_the_next(self):
        a = gauntlet.Spend(self.dir / "s.jsonl", 10)
        a.add(1.25, "task")
        a.add(0.5, "judge")
        b = gauntlet.Spend(self.dir / "s.jsonl", 10)    # a later process
        self.assertAlmostEqual(b.total(), 1.75)
        self.assertAlmostEqual(b.remaining(), 8.25)

    def _run_with_spent(self, spent):
        sp = gauntlet.Spend(self.grant["spend_file"], 10)
        sp.add(spent, "task")
        prof = self.profile("solo", act_max_usd="0.25")
        return self.start([prof], "open firefox")

    def test_thirty_cents_left_runs_the_next_task(self):
        r = self._run_with_spent(9.70)
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("cap_stop", devrun.last_summary())

    def test_twenty_cents_left_stops_and_says_why(self):
        r = self._run_with_spent(9.80)
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.calls, [])
        s = devrun.last_summary()
        self.assertTrue(s["stopped"])
        self.assertIn("spend cap", s["cap_stop"])

    def test_both_arms_stop_at_the_same_case(self):
        sp = gauntlet.Spend(self.grant["spend_file"], 10)
        sp.add(9.30, "task")           # 0.70 left; two arms need 0.50/case
        a = self.profile("alpha", act_max_usd="0.25")
        b = self.profile("beta", act_max_usd="0.25")

        def spend_one(cfg, state, **kw):
            ledger.note("openrouter", "m", True, {"cost": 0.30})
            return self.fake_run_listen(cfg, state, **kw)
        devsession.turn_on()
        devrun.start(self.cfg, self.st, self.ctl,
                     self.tasks("one", "two", "three"),
                     run_listen=spend_one, judge=self.judge,
                     profiles=[a, b], grant=self.grant)
        self.assertTrue(devrun.wait(10))
        # case one ran for both arms (0.70 -> 0.10); case two never started
        self.assertEqual([c["typed"] for c in self.calls], ["one", "one"])
        self.assertIn("spend cap", devrun.last_summary()["cap_stop"])

    def test_task_and_judge_spend_land_in_the_file(self):
        prof = self.profile("solo", act_max_usd="0.25")

        def spend_one(cfg, state, **kw):
            ledger.note("openrouter", "m", True, {"cost": 0.04})
            return self.fake_run_listen(cfg, state, **kw)
        devsession.turn_on()
        devrun.start(self.cfg, self.st, self.ctl, self.tasks("x"),
                     run_listen=spend_one, judge=self.judge,
                     profiles=[prof], grant=self.grant)
        self.assertTrue(devrun.wait(10))
        kinds = {}
        for line in pathlib.Path(self.grant["spend_file"]).read_text(
                ).splitlines():
            row = json.loads(line)
            kinds[row["kind"]] = kinds.get(row["kind"], 0) + row["usd"]
        self.assertAlmostEqual(kinds["task"], 0.04, places=4)
        self.assertAlmostEqual(kinds["judge"], 0.002, places=4)

    def test_gauntlet_runs_do_not_use_up_the_session(self):
        prof = self.profile("solo", act_max_usd="0.25")
        for _ in range(7):
            self.start([prof], "open firefox")
        self.assertTrue(devsession.is_on())
        self.assertEqual(devsession.status()["runs_done"], 0)

    def test_a_bad_cap_is_refused(self):
        prof = self.profile("solo")
        r = self.start([prof], "x", g={"windows": [], "cap_usd": "lots"})
        self.assertFalse(r["ok"])


class TestReport(GauntletBase):
    def test_named_arms_and_spend_split_by_provider(self):
        def two_providers(cfg, state, **kw):
            ledger.note("openrouter", "m", True, {"cost": 0.03})
            if cfg["ground"]["vlm_brain"].startswith("ollama:"):
                ledger.note("ollama", "q", False, {})
            return self.fake_run_listen(cfg, state, **kw)
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl,
                         self.tasks("open firefox", "pause youtube"),
                         run_listen=two_providers, judge=self.judge,
                         profiles=["hybrid", "openrouter"],
                         grant=self.grant)
        self.assertTrue(r["ok"], r)
        self.assertTrue(devrun.wait(10))
        self.assertEqual(r["tasks"], 4)
        # arms interleave per task: hybrid, openrouter, hybrid, openrouter
        self.assertEqual([c["cfg"]["ground"]["vlm_brain"].split(":")[0]
                          for c in self.calls],
                         ["ollama", "openrouter"] * 2)
        run = devreport.build(r["run_id"])["runs"][0]
        self.assertEqual(sorted(run["arms"]), ["hybrid", "openrouter"])
        self.assertEqual(run["pair_arms"],
                         {"a": "hybrid", "b": "openrouter"})
        self.assertEqual(len(run["pairs"]), 2)
        hyb = run["arms"]["hybrid"]["cost"]["by_provider"]
        self.assertAlmostEqual(hyb["openrouter"], 0.06, places=4)
        self.assertIn("ollama", ledger.provider_totals())
        text = devreport.render({"runs": [run]})
        self.assertIn("arm hybrid:", text)
        self.assertIn("arm openrouter:", text)
        self.assertIn("openrouter $", text)

    def test_profiles_and_vs_do_not_mix(self):
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl, self.tasks("x"),
                         run_listen=self.fake_run_listen, judge=self.judge,
                         profiles=["hybrid"], vs="brain.default=x",
                         grant=self.grant)
        self.assertFalse(r["ok"])
        self.assertEqual(self.calls, [])


class TestJudgeKey(unittest.TestCase):
    def test_judge_resolves_the_env_key_when_omaseal_is_unavailable(self):
        td_ = shorttmp.TemporaryDirectory()
        self.addCleanup(td_.cleanup)
        empty_bin = pathlib.Path(td_.name) / "bin"
        empty_bin.mkdir()
        with mock.patch.object(config, "ENV_FILE",
                               pathlib.Path(td_.name) / "none.env"), \
                mock.patch.dict(os.environ, {
                    "PATH": str(empty_bin),
                    "OPENROUTER_API_KEY": "sk-eval"}, clear=True):
            cfg = devjudge.judge_cfg({}, "m")
            ref = cfg[f"brain.{devjudge.PROVIDER}"]["key_env"]
            self.assertEqual(config.load_env_key(ref), "sk-eval")
        # the default key's keyring entry is never in the judge's list
        self.assertNotIn("keyring://", devjudge.EVAL_KEY)


class TestAppSkillEvent(unittest.TestCase):
    def test_an_injected_app_skill_emits_one_trace_event(self):
        info = {"name": "gimp-basics", "matched_by": "window_class",
                "body": "Use the toolbox.", "path": "/x"}
        cfg = {"act": {"context": "full"}, "agent": {}}
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "gimp", "title": "t"}), \
                mock.patch.object(context, "_last_dayflow",
                                  return_value=""), \
                mock.patch.object(context, "windows_map", return_value=""), \
                mock.patch.object(context, "app_skills", return_value=[]), \
                mock.patch("wisp.inventory.summary", return_value=""), \
                mock.patch("wisp.skills.match_app_skill_info",
                           return_value=info), \
                mock.patch.object(trace, "emit") as emit:
            out = context.snapshot(cfg)
        self.assertIn("[app_skill]\nUse the toolbox.", out)
        evs = [c for c in emit.call_args_list if c[0][1] == "app_skill"]
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0][0][3], {"name": "gimp-basics",
                                        "matched_by": "window_class",
                                        "chars": len("Use the toolbox.")})

    def test_no_match_emits_nothing(self):
        cfg = {"act": {"context": "full"}, "agent": {}}
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "x", "title": "t"}), \
                mock.patch.object(context, "_last_dayflow",
                                  return_value=""), \
                mock.patch.object(context, "windows_map", return_value=""), \
                mock.patch.object(context, "app_skills", return_value=[]), \
                mock.patch("wisp.inventory.summary", return_value=""), \
                mock.patch("wisp.skills.match_app_skill_info",
                           return_value=None), \
                mock.patch.object(trace, "emit") as emit:
            context.snapshot(cfg)
        self.assertFalse([c for c in emit.call_args_list
                          if c[0][1] == "app_skill"])


if __name__ == "__main__":
    unittest.main()
