"""CUA safety layer (W9): app lists, rolling rate limits, kill switch,
dry-run, audit log, confirm-once, cancel. No real driver/hyprctl/ydotool:
the dispatch callable is a mock and subprocess is patched where relevant."""
import json
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import act, cancel, cua_safety  # noqa: E402

DRIVE = {"pointer": {"mode": "drive", "backend": "auto"}}


def cfg(**cua):
    c = {"pointer": dict(DRIVE["pointer"]), "cua": {k: str(v) for k, v
                                                    in cua.items()}}
    return c


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Rig:
    def __init__(self, **cua):
        self.td = tempfile.TemporaryDirectory()
        self.audit = pathlib.Path(self.td.name) / "cua.jsonl"
        self.kill = pathlib.Path(self.td.name) / "cua.kill"
        self.clock = Clock()
        self.app = "firefox"
        self.title = "page"
        self.cfg = cfg(**cua)
        self.limiter = cua_safety.Limiter(self.clock)
        self.runner = mock.Mock(return_value="CLICKED(1,2)")

    def guard(self, **kw):
        return cua_safety.Guard(
            self.cfg, window=lambda: {"app": self.app, "title": self.title},
            clock=self.clock, limiter=self.limiter,
            audit_path=self.audit, kill_path=self.kill, turn="t1", **kw)

    def lines(self):
        if not self.audit.exists():
            return []
        return [json.loads(l) for l in self.audit.read_text().splitlines()]

    def close(self):
        self.td.cleanup()


class Policy(unittest.TestCase):
    def setUp(self):
        self.r = Rig()
        self.addCleanup(self.r.close)

    def test_builtin_denied_app_refused_and_not_dispatched(self):
        self.r.app = "1Password"
        out = self.r.guard().run("click", "1,2", self.r.runner)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.r.runner.assert_not_called()
        self.assertEqual(self.r.lines()[0]["decision"], "deny")

    def test_terminal_running_sudo_denied(self):
        self.r.app, self.r.title = "ghostty", "[sudo] password for luke"
        out = self.r.guard().run("type_text", "x", self.r.runner)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.r.runner.assert_not_called()

    def test_plain_terminal_not_denied(self):
        self.r.app, self.r.title = "ghostty", "~/src"
        self.assertEqual(self.r.guard().run("click", "1,2", self.r.runner),
                         "CLICKED(1,2)")

    def test_user_deny_and_allow_lists(self):
        r = Rig(deny="slack, signal", allow="firefox")
        self.addCleanup(r.close)
        r.app = "Slack"
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))
        r.app = "kate"   # not on the allow list
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))
        r.app = "firefox"
        self.assertEqual(r.guard().run("click", "1,2", r.runner),
                         "CLICKED(1,2)")

    def test_deny_beats_allow(self):
        r = Rig(allow="keepassxc")
        self.addCleanup(r.close)
        r.app = "keepassxc"
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))

    def test_unknown_window_fails_closed_only_with_allow_list(self):
        r = Rig(allow="firefox")
        self.addCleanup(r.close)
        r.app = ""
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))
        self.r.app = ""
        self.assertEqual(self.r.guard().run("click", "1,2", self.r.runner),
                         "CLICKED(1,2)")

    def test_guide_mode_and_unguarded_tools_pass_through(self):
        self.r.cfg["pointer"]["mode"] = "guide"
        self.r.app = "1password"
        self.assertEqual(self.r.guard().run("click", "1,2", self.r.runner),
                         "CLICKED(1,2)")
        self.assertEqual(self.r.guard().run("screenshot", "", self.r.runner),
                         "CLICKED(1,2)")
        self.assertEqual(self.r.lines(), [])


class RateLimit(unittest.TestCase):
    def test_window_rollover_with_injected_clock(self):
        r = Rig(max_clicks_per_min=3, max_per_turn=99)
        self.addCleanup(r.close)
        g = r.guard()
        for _ in range(3):
            self.assertEqual(g.run("click", "1,2", r.runner), "CLICKED(1,2)")
        out = g.run("click", "1,2", r.runner)
        self.assertTrue(out.startswith("REFUSED") and "rate" in out, out)
        self.assertEqual(r.runner.call_count, 3)
        r.clock.t += 59
        self.assertTrue(g.run("click", "1,2", r.runner).startswith("REFUSED"))
        r.clock.t += 2          # oldest calls roll out of the 60 s window
        self.assertEqual(g.run("click", "1,2", r.runner), "CLICKED(1,2)")

    def test_limit_is_per_window(self):
        r = Rig(max_clicks_per_min=1, max_per_turn=99)
        self.addCleanup(r.close)
        g = r.guard()
        g.run("click", "1,2", r.runner)
        r.app = "kate"
        self.assertEqual(g.run("click", "1,2", r.runner), "CLICKED(1,2)")

    def test_per_turn_cap(self):
        r = Rig(max_clicks_per_min=99, max_per_turn=2)
        self.addCleanup(r.close)
        g = r.guard()
        g.run("click", "1,2", r.runner)
        g.run("click", "1,2", r.runner)
        r.clock.t += 120
        self.assertTrue(g.run("click", "1,2", r.runner).startswith("REFUSED"))

    def test_move_is_not_counted(self):
        r = Rig(max_clicks_per_min=1, max_per_turn=1)
        self.addCleanup(r.close)
        g = r.guard()
        for _ in range(5):
            g.run("move", "1,2", r.runner)
        self.assertEqual(g.run("click", "1,2", r.runner), "CLICKED(1,2)")

    def test_failed_click_counts_and_is_not_retried(self):
        r = Rig(max_clicks_per_min=5)
        self.addCleanup(r.close)
        r.runner.return_value = "SKIP (click failed via cua)"
        out = r.guard().run("click", "1,2", r.runner)
        self.assertTrue(out.startswith("SKIP"))
        self.assertEqual(r.runner.call_count, 1)


class KillSwitch(unittest.TestCase):
    def test_file_and_config_flag(self):
        r = Rig()
        self.addCleanup(r.close)
        r.kill.write_text("")
        out = r.guard().run("click", "1,2", r.runner)
        self.assertTrue(out.startswith("REFUSED") and "kill" in out, out)
        r.runner.assert_not_called()
        r.kill.unlink()
        r.cfg["cua"]["kill_switch"] = "true"
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))

    def test_kill_resume_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "cua.kill"
            cua_safety.kill(p)
            self.assertTrue(p.exists())
            cua_safety.resume(p)
            self.assertFalse(p.exists())


class Cancel(unittest.TestCase):
    def test_cancel_between_calls(self):
        r = Rig()
        self.addCleanup(r.close)
        g = r.guard()
        tok = cancel.CancelToken()
        with cancel.bind(tok):
            self.assertEqual(g.run("click", "1,2", r.runner), "CLICKED(1,2)")
            tok.cancel()
            with self.assertRaises(cancel.Cancelled):
                g.run("click", "3,4", r.runner)
        self.assertEqual(r.runner.call_count, 1)

    def test_interrupted_callback_stops_before_dispatch(self):
        r = Rig()
        self.addCleanup(r.close)
        g = r.guard(interrupted=lambda: True)
        with self.assertRaises(cancel.Cancelled):
            g.run("click", "1,2", r.runner)
        r.runner.assert_not_called()


class DryRun(unittest.TestCase):
    def test_no_subprocess_and_no_driver(self):
        r = Rig(dry_run="true")
        self.addCleanup(r.close)
        from wisp import cua, pointer
        with mock.patch("subprocess.run") as run, \
                mock.patch("subprocess.Popen") as popen, \
                mock.patch.object(cua.Cua, "call") as call, \
                mock.patch.object(cancel, "run") as crun, \
                mock.patch.object(pointer.Registry, "click") as click:
            out = r.guard().run("click", "10,20", r.runner)
            r.guard().run("type_text", "hello", r.runner)
        self.assertTrue(out.startswith("DRYRUN"), out)
        self.assertIn("10,20", out)
        for m in (run, popen, call, crun, click, r.runner):
            m.assert_not_called()
        self.assertTrue(all(l["dry_run"] for l in r.lines()))
        self.assertEqual(r.lines()[0]["decision"], "dry_run")

    def test_dry_run_still_enforces_deny(self):
        r = Rig(dry_run="true")
        self.addCleanup(r.close)
        r.app = "bitwarden"
        self.assertTrue(r.guard().run("click", "1,2", r.runner)
                        .startswith("REFUSED"))


class Audit(unittest.TestCase):
    SECRET = "hunter2-correct-horse"

    def test_typed_text_never_logged(self):
        r = Rig()
        self.addCleanup(r.close)
        r.runner.return_value = "TYPED"
        r.guard().run("type_text", self.SECRET, r.runner)
        raw = r.audit.read_text()
        self.assertNotIn(self.SECRET, raw)
        self.assertNotIn("hunter", raw)
        rec = json.loads(raw)
        self.assertEqual(rec["len"], len(self.SECRET))
        self.assertEqual(len(rec["sha"]), 12)
        self.assertNotIn("arg", rec)

    def test_plain_key_text_hashed_but_named_key_kept(self):
        r = Rig()
        self.addCleanup(r.close)
        r.guard().run("key", "ctrl+l", r.runner)
        r.guard().run("key", "p", r.runner)
        a, b = r.lines()
        self.assertEqual(a["key"], "ctrl+l")
        self.assertNotIn("key", b)
        self.assertEqual(b["len"], 1)

    def test_click_record_shape_and_target_text_not_logged(self):
        r = Rig()
        self.addCleanup(r.close)
        r.guard().run("click", "10,20@logical", r.runner)
        r.guard().run("click", "the secret vault button", r.runner)
        a, b = r.lines()
        for k in ("ts", "turn", "tool", "app", "x", "y", "decision",
                  "result", "ms", "dry_run"):
            self.assertIn(k, a)
        self.assertEqual((a["x"], a["y"], a["tool"], a["turn"]),
                         (10, 20, "click", "t1"))
        self.assertNotIn("vault", r.audit.read_text())
        self.assertNotIn("x", b)

    def test_result_text_not_echoed(self):
        r = Rig()
        self.addCleanup(r.close)
        r.runner.return_value = "SKIP (typer failed for hunter2)"
        r.guard().run("type_text", "hunter2", r.runner)
        self.assertNotIn("hunter2", r.audit.read_text())

    def test_audit_off_and_unwritable_never_raises(self):
        r = Rig(audit="false")
        self.addCleanup(r.close)
        r.guard().run("click", "1,2", r.runner)
        self.assertEqual(r.lines(), [])
        r2 = Rig()
        self.addCleanup(r2.close)
        g = r2.guard()
        g.audit_path = pathlib.Path("/proc/nope/cua.jsonl")
        self.assertEqual(g.run("click", "1,2", r2.runner), "CLICKED(1,2)")


class ConfirmTier(unittest.TestCase):
    def test_default_tier_unchanged(self):
        self.assertEqual(cua_safety.effective_tier("click", {}), "interactive")
        self.assertEqual(cua_safety.effective_tier("close", {}), "mutating")

    def test_always_promotes_input_tools(self):
        c = cfg(confirm="always")
        self.assertEqual(cua_safety.effective_tier("click", c), "mutating")
        self.assertEqual(cua_safety.effective_tier("type_text", c),
                         "mutating")
        self.assertEqual(cua_safety.effective_tier("launch", c), "safe")

    def test_confirm_once_per_tool_and_app(self):
        c = cfg(confirm="always")
        c["agent"] = {}
        st = types.SimpleNamespace(confirmed=set(), focus={"app": "kate"})
        asks = []

        def confirm(p):
            asks.append(p)
            return True
        self.assertIsNone(act._gate("click", "1,2", c, confirm, state=st))
        self.assertIsNone(act._gate("click", "3,4", c, confirm, state=st))
        self.assertEqual(len(asks), 1)             # once for (click, kate)
        self.assertIsNone(act._gate("type_text", "x", c, confirm, state=st))
        self.assertEqual(len(asks), 2)             # new tool
        st.focus = {"app": "firefox"}
        self.assertIsNone(act._gate("click", "1,2", c, confirm, state=st))
        self.assertEqual(len(asks), 3)             # new app
        self.assertEqual(st.confirmed, {("click", "kate"),
                                        ("type_text", "kate"),
                                        ("click", "firefox")})


class ActWiring(unittest.TestCase):
    def test_loop_dispatches_through_guard_and_denies(self):
        c = cfg()
        c["agent"] = {}
        c["brain"] = {}
        calls = []
        msgs = iter([
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "1", "function": {"name": "click",
                                         "arguments": '{"arg":"1,2"}'}}]},
            {"role": "assistant", "content": "done"}])
        with mock.patch.object(act, "_post", lambda m, cf: next(msgs)), \
                mock.patch.object(act.tools, "run",
                                  lambda *a, **k: calls.append(a) or "X"), \
                mock.patch("wisp.brain.supports_tools", return_value=True), \
                mock.patch("wisp.context.snapshot", return_value=""), \
                mock.patch("wisp.context.focused_app", return_value=""), \
                mock.patch("wisp.platform.active_window",
                           return_value={"class": "KeePassXC"}), \
                mock.patch("wisp.trajectories.context_for",
                           return_value=""), \
                mock.patch("wisp.trajectories.record"), \
                mock.patch("wisp.train.hint_for", return_value=""), \
                mock.patch("wisp.goals.context_text", return_value=""), \
                mock.patch("wisp.goals.record_steps"), \
                mock.patch("wisp.goals.close"), \
                mock.patch.object(cua_safety, "audit_default_path",
                                  lambda: pathlib.Path(os.devnull)):
            steps = []
            act.run_act_loop("click it", c, steps_out=steps)
        self.assertNotIn("click", [c[0] for c in calls])
        self.assertTrue(steps[-1]["result"].startswith("REFUSED"))


if __name__ == "__main__":
    unittest.main()
