#!/usr/bin/env python3
"""Dev tuning mode U2: the task-list runner. The pipeline is stubbed, so
nothing here touches the desktop, the network or any key."""
import json
import pathlib
import sys
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from wisp import config, devrun, devsession, policy, state as state_mod  # noqa: E402
from wisp import trace  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        for name, val in (("DATA_DIR", self.dir),
                          ("DECISIONS", self.dir / "decisions.jsonl")):
            p = mock.patch.object(config, name, val)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(trace, "TRACE_FILE", self.dir / "trace.jsonl")
        p.start()
        self.addCleanup(p.stop)
        self.st = state_mod.StateBus(state_file=self.dir / "state.json",
                                     autostart=False)
        self.addCleanup(self.st.close)
        self.ctl = {"busy": threading.Event(), "interrupt": threading.Event(),
                    "rec": None, "rec_lock": threading.Lock(), "token": None}
        self.cfg = config._default_cfg_dict()
        self.cfg["agent"]["allow_shell"] = "true"
        self.cfg["traj"]["enabled"] = "true"
        self.calls = []
        self.script = {}          # goal -> (result, [trace events])
        self.after = {}           # goal -> callable run after the turn
        self.addCleanup(devrun.reset)

    def tasks(self, *lines):
        p = self.dir / "tasks.txt"
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    def fake_run_listen(self, cfg, state, wait_for_choice=None, wav=None,
                        interrupted=None, spans=None, turn_id=None,
                        cancel=None, speculative=None, typed=""):
        self.calls.append({"cfg": cfg, "wait": wait_for_choice,
                           "turn": turn_id, "typed": typed})
        result, events = self.script.get(typed, ("ACTED (1 steps): ok", []))
        with (self.dir / "trace.jsonl").open("a") as f:
            for ev in events:
                f.write(json.dumps({"ts": "x", "turn": turn_id, "ms": 5,
                                    **ev}) + "\n")
        with (self.dir / "decisions.jsonl").open("a") as f:
            f.write(json.dumps({"ts": "2026-10-30T00:00:00+00:00",
                                "turn": turn_id, "transcript": typed,
                                "answers": {"route": {"choice": "act"}},
                                "result": result,
                                "timing_ms": {"done": 12}}) + "\n")
        if typed in self.after:
            self.after[typed]()
        return 0

    def run_list(self, path, session=True):
        if session:
            devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl, path,
                         run_listen=self.fake_run_listen)
        if r.get("ok"):
            self.assertTrue(devrun.wait(10))
        return r

    def rows(self, run_id):
        p = self.dir / "dev_runs" / f"{run_id}.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines() if x]


class TestRunner(Base):
    def test_three_tasks_run_in_order_with_no_confirmation_channel(self):
        path = self.tasks("# starter", "", "open firefox",
                          "pause youtube", "go to workspace 2")
        r = self.run_list(path)
        self.assertTrue(r["ok"], r)
        self.assertEqual([c["typed"] for c in self.calls],
                         ["open firefox", "pause youtube",
                          "go to workspace 2"])
        self.assertTrue(all(c["wait"] is None for c in self.calls))
        self.assertEqual(len({c["turn"] for c in self.calls}), 3)
        rows = self.rows(r["run_id"])
        self.assertEqual([x["index"] for x in rows], [0, 1, 2])
        self.assertEqual([x["goal"] for x in rows],
                         [c["typed"] for c in self.calls])
        for x in rows:
            self.assertEqual(x["outcome"], "success")
            self.assertEqual(x["run_id"], r["run_id"])
            for k in ("judge", "drift", "cost"):
                self.assertIn(k, x)
                self.assertIsNone(x[k])
            for k in ("turn", "route", "result", "steps", "timing_ms",
                      "started", "ended"):
                self.assertIn(k, x)
        self.assertFalse(self.ctl["busy"].is_set())

    def test_run_config_copy_is_isolated_and_locked_down(self):
        self.run_list(self.tasks("open firefox"))
        run_cfg = self.calls[0]["cfg"]
        self.assertIsNot(run_cfg, self.cfg)
        self.assertEqual(run_cfg["traj"]["enabled"], "false")
        self.assertEqual(run_cfg["agent"]["allow_shell"], "false")
        for t in ("type_text", "key", "shell", "mcp_call", "post_send",
                  "close"):
            self.assertIn(t, run_cfg["dev"]["deny_tools"])
        # the owner's config is untouched
        self.assertEqual(self.cfg["traj"]["enabled"], "true")
        self.assertEqual(self.cfg["agent"]["allow_shell"], "true")
        self.assertNotIn("deny_tools", self.cfg.get("dev", {}))

    def test_confirmation_step_ends_stopped(self):
        self.script["delete the draft"] = (
            "ACTED (2 steps): done",
            [{"step": "gate_stop", "kind": "policy",
              "data": {"tool": "close",
                       "result": "SKIPPED (close needs user confirmation)"}}])
        r = self.run_list(self.tasks("delete the draft"))
        self.assertEqual(self.rows(r["run_id"])[0]["outcome"], "stopped")

    def test_denied_type_text_ends_stopped(self):
        self.script["search youtube for cats"] = (
            "ACTED (3 steps): searched",
            [{"step": "gate_stop", "kind": "policy",
              "data": {"tool": "type_text",
                       "result": "REFUSED (dev run denies type_text)"}}])
        r = self.run_list(self.tasks("search youtube for cats"))
        self.assertEqual(self.rows(r["run_id"])[0]["outcome"], "stopped")

    def test_skipped_and_refused_results_are_stopped(self):
        self.script["a"] = ("SKIPPED (shell needs user confirmation)", [])
        self.script["b"] = ("REFUSED (denylisted command)", [])
        r = self.run_list(self.tasks("a", "b"))
        self.assertEqual([x["outcome"] for x in self.rows(r["run_id"])],
                         ["stopped", "stopped"])

    def test_incomplete_on_budget_interrupt_error_and_no_decision(self):
        self.script["a"] = ("budget: step limit", [])
        self.script["b"] = ("INTERRUPTED", [])
        self.script["c"] = ("ERROR: boom", [])
        r = self.run_list(self.tasks("a", "b", "c"))
        self.assertEqual([x["outcome"] for x in self.rows(r["run_id"])],
                         ["incomplete"] * 3)

    def test_launched_and_answered_are_success(self):
        self.script["a"] = ("LAUNCHED firefox", [])
        self.script["b"] = ("ANSWERED: noon", [])
        r = self.run_list(self.tasks("a", "b"))
        self.assertEqual([x["outcome"] for x in self.rows(r["run_id"])],
                         ["success", "success"])

    def test_pipeline_exception_is_incomplete_and_run_continues(self):
        def boom(*a, **k):
            if k.get("typed") == "a":
                raise RuntimeError("model down")
            return self.fake_run_listen(*a, **k)
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl, self.tasks("a", "b"),
                         run_listen=boom)
        self.assertTrue(devrun.wait(10))
        rows = self.rows(r["run_id"])
        self.assertEqual([x["outcome"] for x in rows],
                         ["incomplete", "success"])

    def test_steps_come_from_the_trace_for_that_turn(self):
        self.script["pause youtube"] = (
            "ACTED (1 steps): paused",
            [{"step": "tool_call", "kind": "tool",
              "data": {"name": "media", "args": "pause"}},
             {"step": "tool_result", "kind": "tool",
              "data": {"name": "media", "result": "paused"}}])
        r = self.run_list(self.tasks("pause youtube", "open firefox"))
        rows = self.rows(r["run_id"])
        self.assertEqual(rows[0]["steps"][0]["tool"], "media")
        self.assertEqual(rows[0]["steps"][0]["arg"], "pause")
        self.assertEqual(rows[0]["steps"][0]["result"], "paused")
        self.assertEqual(rows[1]["steps"], [])


class TestPrescreen(Base):
    def test_agent_routed_task_is_skipped_stopped_and_never_runs(self):
        r = self.run_list(self.tasks("have an agent fix my build",
                                     "open firefox"))
        rows = self.rows(r["run_id"])
        self.assertEqual(rows[0]["outcome"], "stopped")
        self.assertIsNone(rows[0]["turn"])
        self.assertIn("skip", rows[0]["result"].lower())
        self.assertEqual([c["typed"] for c in self.calls], ["open firefox"])

    def test_prescreen_classifies_without_running(self):
        for text in ("have an agent fix my build",
                     "dictate hello world",
                     "remember this as my morning routine",
                     "create a routine for standup"):
            with self.subTest(text=text):
                route, skip = devrun.prescreen(text, self.cfg)
                self.assertTrue(skip, (text, route))
        for text in ("open firefox", "pause youtube", "what time is it",
                     "go to workspace 2"):
            with self.subTest(text=text):
                route, skip = devrun.prescreen(text, self.cfg)
                self.assertFalse(skip, (text, route))


class TestSessionRules(Base):
    def test_run_refused_when_session_off(self):
        r = self.run_list(self.tasks("open firefox"), session=False)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "dev_off")
        self.assertEqual(self.calls, [])

    def test_missing_file_is_an_error(self):
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl,
                         str(self.dir / "nope.txt"),
                         run_listen=self.fake_run_listen)
        self.assertFalse(r["ok"])

    def test_empty_list_is_an_error(self):
        devsession.turn_on()
        r = devrun.start(self.cfg, self.st, self.ctl,
                         self.tasks("# only a comment", ""),
                         run_listen=self.fake_run_listen)
        self.assertFalse(r["ok"])

    def test_completed_run_counts_and_fifth_turns_session_off(self):
        devsession.turn_on()
        for i in range(1, 6):
            r = devrun.start(self.cfg, self.st, self.ctl,
                             self.tasks("open firefox"),
                             run_listen=self.fake_run_listen)
            self.assertTrue(r["ok"], (i, r))
            self.assertTrue(devrun.wait(10))
            self.assertEqual(devsession.status()["runs_done"], i)
            self.assertEqual(self.st.snapshot()["dev"]["on"], i < 5)
        self.assertFalse(devsession.is_on())

    def test_one_run_at_a_time(self):
        gate, started = threading.Event(), threading.Event()

        def slow(*a, **k):
            started.set()
            gate.wait(10)
            return self.fake_run_listen(*a, **k)
        devsession.turn_on()
        r1 = devrun.start(self.cfg, self.st, self.ctl,
                          self.tasks("open firefox"), run_listen=slow)
        self.assertTrue(r1["ok"])
        self.assertTrue(started.wait(5))
        r2 = devrun.start(self.cfg, self.st, self.ctl,
                          self.tasks("open firefox"),
                          run_listen=self.fake_run_listen)
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["error"], "busy")
        gate.set()
        self.assertTrue(devrun.wait(10))

    def test_busy_when_a_turn_is_in_flight(self):
        devsession.turn_on()
        self.ctl["busy"].set()
        r = devrun.start(self.cfg, self.st, self.ctl,
                         self.tasks("open firefox"),
                         run_listen=self.fake_run_listen)
        self.assertEqual(r.get("error"), "busy")

    def test_stop_finishes_the_current_task_then_stops(self):
        self.after["two"] = devrun.stop
        r = self.run_list(self.tasks("one", "two", "three", "four"))
        self.assertEqual([c["typed"] for c in self.calls], ["one", "two"])
        rows = self.rows(r["run_id"])
        self.assertEqual([x["goal"] for x in rows], ["one", "two"])
        self.assertTrue(devrun.last_summary()["stopped"])
        # a stopped run still counts as a run
        self.assertEqual(devsession.status()["runs_done"], 1)

    def test_stop_with_nothing_running(self):
        r = devrun.stop()
        self.assertFalse(r["ok"])


class TestDenyHook(Base):
    def test_policy_refuses_denied_tools_in_a_run_config(self):
        cfg = {"dev": {"run_id": "r1", "deny_tools": ["type_text", "key"]}}
        self.assertIn("type_text",
                      policy.preempted("type_text", "hi", cfg) or "")
        self.assertIsNone(policy.preempted("media", "pause", cfg))
        self.assertIsNone(policy.preempted("type_text", "hi", {}))

    def test_gate_traces_a_stop_only_for_run_configs(self):
        cfg = {"dev": {"run_id": "r1", "deny_tools": ["key"]}}
        with mock.patch.object(trace, "emit") as emit:
            out = policy.gate("key", "Return", cfg, None)
            self.assertTrue(out.startswith("REFUSED"))
            self.assertEqual(emit.call_args[0][1], "gate_stop")
        with mock.patch.object(trace, "emit") as emit:
            policy.gate("key", "Return", {}, None)
            emit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
