"""Sense collector + suggestion miner tests."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import agents, sense, suggest


class TestSense(unittest.TestCase):
    def _cfg(self, **kw):
        return {"sense": {"enabled": "true", "interval_s": "300",
                          "dayflow": "true", "dayflow_every": "1",
                          **kw}}

    def test_tick_writes_window_and_dayflow(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "activity.jsonl"
            with mock.patch.object(sense, "_window",
                                   return_value={"app": "discord",
                                                 "title": "#general"}), \
                 mock.patch.object(sense, "_dayflow_tail",
                                   return_value=[{"title": "coding",
                                                  "category": "dev",
                                                  "start": "09:00"}]):
                rec = sense.tick(self._cfg(), {}, path=f)
            self.assertEqual(rec["window"]["app"], "discord")
            self.assertTrue(rec["dayflow"])
            self.assertEqual(len(f.read_text().splitlines()), 1)

    def test_tick_empty_when_no_sources(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "activity.jsonl"
            with mock.patch.object(sense, "_window", return_value={}), \
                 mock.patch.object(sense, "_dayflow_tail",
                                   return_value=[]):
                rec = sense.tick(self._cfg(), {}, path=f)
            self.assertEqual(rec, {})
            self.assertFalse(f.exists())

    def test_dayflow_skipped_when_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "activity.jsonl"
            with mock.patch.object(sense, "_window", return_value={}), \
                 mock.patch.object(sense, "_dayflow_tail") as df:
                sense.tick(self._cfg(dayflow="false"), {}, path=f)
            df.assert_not_called()

    def test_dayflow_runs_every_nth_tick(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "activity.jsonl"
            seen = {}
            with mock.patch.object(sense, "_window", return_value={}), \
                 mock.patch.object(sense, "_dayflow_tail",
                                   return_value=[{"title": "x"}]) as df:
                cfg = self._cfg(dayflow_every="3")
                for _ in range(4):
                    sense.tick(cfg, seen, path=f)
            # first tick always samples, then every 3rd → ticks 1,4 = 2
            self.assertEqual(df.call_count, 2)

    def test_read_window_filters_old(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "activity.jsonl"
            f.write_text(
                json.dumps({"ts": "2000-01-01T00:00:00+00:00"}) + "\n"
                + json.dumps({"ts": "2999-01-01T00:00:00+00:00"}) + "\n")
            out = sense.read_window(hours=1, path=f)
            self.assertEqual(len(out), 1)

    def test_enabled_default_off(self):
        self.assertFalse(sense.enabled({}))
        self.assertTrue(sense.enabled(self._cfg()))


class TestSuggest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sug = pathlib.Path(self.td.name) / "suggestions.jsonl"
        self._patches = [
            mock.patch.object(suggest, "SUGGESTIONS_FILE", self.sug),
            mock.patch.object(suggest, "NEVER_FILE",
                              pathlib.Path(self.td.name) / "never.json"),
            mock.patch.object(suggest, "_BUDGET_FILE",
                              pathlib.Path(self.td.name) / "budget.json"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.td.cleanup()

    def _cfg(self):
        return {"sense": {"window_h": "3", "max_calls_per_day": "48",
                          "model": "openrouter:test/cheap"}}

    def test_sparse_window_never_calls_model(self):
        with mock.patch.object(sense, "read_window", return_value=[]), \
             mock.patch("wisp.brain.chat") as chat:
            self.assertEqual(suggest.mine(self._cfg()), [])
        chat.assert_not_called()

    def test_jev_no_shortcircuits_model(self):
        win = [{"ts": "2999-01-01T00:00:00+00:00",
                "window": {"app": "a", "title": "t"}}] * 6
        with mock.patch.object(sense, "read_window", return_value=win), \
             mock.patch.object(suggest, "_worth_mining",
                               return_value=False), \
             mock.patch("wisp.brain.chat") as chat:
            self.assertEqual(suggest.mine(self._cfg()), [])
        chat.assert_not_called()

    def test_new_suggestion_publishes_state(self):
        win = [{"ts": "2999-01-01T00:00:00+00:00",
                "window": {"app": "a", "title": "t"}}] * 6
        st = mock.Mock()
        payload = json.dumps({"suggestions": [
            {"title": "morning check", "evidence": "daily",
             "routine": "open discord", "confidence": 0.8}]})
        with mock.patch.object(sense, "read_window", return_value=win), \
             mock.patch.object(suggest, "_worth_mining",
                               return_value=True), \
             mock.patch("wisp.brain.chat",
                        return_value={"content": payload}):
            out = suggest.mine(self._cfg(), state=st)
        self.assertEqual(len(out), 1)
        st.transition.assert_called()
        self.assertEqual(st.transition.call_args[0][0], "suggestion")
        self.assertIn("morning check", self.sug.read_text())

    def test_dedup_and_never_suppress(self):
        win = [{"ts": "x"}] * 6
        payload = json.dumps({"suggestions": [
            {"title": "t", "routine": "open discord"}]})
        with mock.patch.object(sense, "read_window", return_value=win), \
             mock.patch.object(suggest, "_worth_mining",
                               return_value=True), \
             mock.patch("wisp.brain.chat",
                        return_value={"content": payload}):
            first = suggest.mine(self._cfg())
            again = suggest.mine(self._cfg())  # same key → deduped
            key = first[0]["key"]
            suggest.suppress(key)
            never = suggest.mine(self._cfg())
        self.assertEqual(len(first), 1)
        self.assertEqual(again, [])
        self.assertEqual(never, [])

    def test_malformed_output_discarded(self):
        win = [{"ts": "x"}] * 6
        with mock.patch.object(sense, "read_window", return_value=win), \
             mock.patch.object(suggest, "_worth_mining",
                               return_value=True), \
             mock.patch("wisp.brain.chat",
                        return_value={"content": "not json"}):
            self.assertEqual(suggest.mine(self._cfg()), [])

    def test_budget_cap(self):
        win = [{"ts": "x"}] * 6
        suggest._BUDGET_FILE.write_text(json.dumps(
            {"day": __import__("datetime").datetime.now()
             .strftime("%Y-%m-%d"), "calls": 48}))
        cfg = self._cfg()
        cfg["sense"]["max_calls_per_day"] = "48"
        with mock.patch.object(sense, "read_window", return_value=win), \
             mock.patch.object(suggest, "_worth_mining",
                               return_value=True), \
             mock.patch("wisp.brain.chat") as chat:
            self.assertEqual(suggest.mine(cfg), [])
        chat.assert_not_called()

    def test_resolve_never_persists(self):
        st = mock.Mock()
        st.suggestion = {"key": "abc", "title": "t"}
        out = suggest.resolve_pick("suggestion:never", self._cfg(),
                                   state=st)
        self.assertIn("never", out)
        self.assertIn("abc",
                      suggest.NEVER_FILE.read_text())

    def test_resolve_automate_returns_routine(self):
        self.sug.write_text(json.dumps(
            {"key": "k1", "title": "t", "routine": "open discord",
             "status": "new"}) + "\n")
        st = mock.Mock()
        st.suggestion = {"key": "k1"}
        out = suggest.resolve_pick("suggestion:automate", self._cfg(),
                                   state=st)
        self.assertTrue(out.startswith("RUN "))
        self.assertIn("open discord", out)


class TestAgentGuards(unittest.TestCase):
    def test_auto_runtime_picks_priority(self):
        with mock.patch.object(
                agents.shutil, "which",
                side_effect=lambda b: "/usr/bin/" + b
                if b == "codex" else None):
            self.assertEqual(
                agents.resolve_runtime({"brain": {"agent_runtime":
                                                  "auto"}}), "codex")

    def test_auto_runtime_none_detected(self):
        with mock.patch.object(agents.shutil, "which",
                               return_value=None):
            self.assertEqual(
                agents.resolve_runtime({"brain": {"agent_runtime":
                                                  "auto"}}), "")

    def test_explicit_runtime_wins(self):
        with mock.patch.object(
                agents.shutil, "which",
                return_value="/usr/bin/claude"):
            self.assertEqual(
                agents.resolve_runtime({"brain": {"agent_runtime":
                                                  "claude"}}), "claude")

    def test_concurrency_cap(self):
        with tempfile.TemporaryDirectory() as td:
            tf = pathlib.Path(td) / "tasks.jsonl"
            # three live-looking pids — init of our own process is alive
            import os
            pid = os.getpid()
            tf.write_text("".join(
                json.dumps({"id": f"t{i}", "name": f"t{i}",
                            "pid": pid, "status": "running",
                            "ts": "2999-01-01T00:00:00+00:00"}) + "\n"
                for i in range(3)))
            cfg = {"agent": {"max_concurrent": "3",
                             "task_timeout_s": "0"}}
            out = agents.spawn("one more", cfg, tasks_file=tf,
                               log_dir=pathlib.Path(td) / "logs")
            self.assertIn("agent limit", out)

    def test_model_flag_position(self):
        # --model lands after 'run': ori opencode run --model X <task>
        cfg = {"brain": {"agent_runtime": "opencode"},
               "agents": {"model": "m/x"}}
        with mock.patch.object(agents.shutil, "which",
                               return_value="/usr/bin/ori"):
            cmd = agents._runtime_cmd(cfg, "do it", "m/x")
        self.assertEqual(cmd[:4], ["ori", "opencode", "run",
                                   "--model"])

    def test_pstart_pins_pid_identity(self):
        import os
        pid = os.getpid()
        real = agents._pstart(pid)
        self.assertTrue(real)
        self.assertTrue(agents._alive(pid, real))
        self.assertFalse(agents._alive(pid, "999999999"))  # reused pid

    def test_automate_after_snooze_finds_routine(self):
        # status-only mark lines must not hide the routine
        self.sug.write_text(
            json.dumps({"key": "k1", "title": "t",
                        "routine": "open discord", "status": "new"})
            + "\n"
            + json.dumps({"key": "k1", "status": "snoozed"}) + "\n")
        st = mock.Mock()
        st.suggestion = {}
        out = suggest.resolve_pick("suggestion:automate:k1",
                                   {"sense": {}}, state=st)
        self.assertIn("open discord", out)


class TestSkillTiers(unittest.TestCase):
    def test_tool_skill_cannot_self_declare_safe(self):
        from wisp import skills
        meta = {"tool": "s.sh", "tier": "safe"}
        with mock.patch.object(skills, "_skill_meta",
                               return_value=meta):
            self.assertEqual(skills.tier_of("skill_x"), "mutating")
        self.assertEqual(skills.tier_of("skill_missing"), "shell")


class TestAgentGuards(unittest.TestCase):
    def test_timeout_reaps_old_task(self):
        with tempfile.TemporaryDirectory() as td:
            tf = pathlib.Path(td) / "tasks.jsonl"
            import os
            tf.write_text(json.dumps(
                {"id": "old", "name": "old", "pid": os.getpid(),
                 "status": "running",
                 "ts": "2000-01-01T00:00:00+00:00"}) + "\n")
            cfg = {"agent": {"task_timeout_s": "60",
                             "max_concurrent": "3"}}
            real_kill = os.kill
            # _alive probes with signal 0 — keep it working; only the
            # SIGTERM in _reap_expired is intercepted
            with mock.patch.object(agents.os, "killpg", create=True), \
                 mock.patch.object(
                     agents.os, "kill",
                     side_effect=lambda p, s: real_kill(p, s)
                     if s == 0 else None):
                reaped = agents._reap_expired(cfg, tf)
            self.assertEqual(reaped, ["old"])
            self.assertIn("timed_out", tf.read_text())


class TestWindowSeam(unittest.TestCase):
    """The collector must read the focused window through the platform
    seam. It used to shell hyprctl directly, so macOS recorded no window
    at all — silently, forever."""

    def test_routes_through_platform(self):
        with mock.patch("wisp.platform.active_window",
                        return_value={"class": "Safari", "title": "Docs"}) as m:
            self.assertEqual(sense._window(),
                             {"class": "Safari", "title": "Docs"})
        m.assert_called_once()

    def test_swallows_backend_errors(self):
        with mock.patch("wisp.platform.active_window",
                        side_effect=RuntimeError("no backend")):
            self.assertEqual(sense._window(), {})


if __name__ == "__main__":
    unittest.main()
