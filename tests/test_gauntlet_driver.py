#!/usr/bin/env python3
"""The gauntlet driver (U6), offline: a fake `systemctl` on a private
PATH, a fake daemon (the fake brain), a sandbox whose spawn, compositor
and kill are fakes, and the real restricted shell run as a subprocess.
Nothing here starts a real service, launches an app or spends money."""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from fakes import BinDir, FakeSystemctl  # noqa: E402
from wisp import config, devreport, gauntlet as gmode, learn  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "gauntlet_script", ROOT / "scripts" / "gauntlet.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["gauntlet_script"] = G
_spec.loader.exec_module(G)
SB = G.sandbox
RSH = ROOT / "scripts" / "gauntlet" / "rsh"
KEY = "sk-eval-test-key"


class FakeProc:
    def __init__(self, pid):
        self.pid, self.terminated = pid, False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


class FakeDesktop:
    """The compositor's client list plus spawn/kill, for the Sandbox."""

    def __init__(self):
        self.clients_, self.spawned, self.next_pid = [], [], 900000
        self.title = {"files": "Projects - Files", "browser": "Index",
                      "terminal": "rsh"}

    def spawn(self, argv, **kw):
        self.next_pid += 1
        app = ("browser" if "--user-data-dir" in " ".join(argv) else
               "files" if "nautilus" in argv[0] else "terminal")
        self.spawned.append({"argv": argv, "env": kw.get("env"),
                             "cwd": kw.get("cwd"), "app": app})
        self.clients_.append({
            "address": f"0x{self.next_pid:x}", "pid": self.next_pid,
            "class": {"browser": "chromium", "files": "org.gnome.Nautilus",
                      "terminal": "Alacritty"}[app],
            "title": self.title[app], "workspace": {"id": 91},
            "at": [0, 0], "size": [800, 600]})
        return FakeProc(self.next_pid)

    def sandbox(self, root):
        which = {"chromium": "/usr/bin/chromium",
                 "nautilus": "/usr/bin/nautilus",
                 "alacritty": "/usr/bin/alacritty"}.get
        return SB.Sandbox(root, spawn=self.spawn,
                          clients=lambda: list(self.clients_),
                          move=lambda a, w: None, focused=lambda: "",
                          which=which, killpg=lambda *a: None,
                          sleep=lambda s: None, tree=lambda p: {p},
                          base_env={"PATH": "/usr/bin", "OPENROUTER_API_KEY":
                                    KEY, "WAYLAND_DISPLAY": "wayland-1",
                                    "XDG_RUNTIME_DIR": "/run/user/1000",
                                    "HOME": "/home/owner"},
                          port=lambda: 9333)


class FakeDeps(G.Deps):
    """The system, faked. `script(goal, arm, n)` -> {steps, ok, usd,
    reused?} drives the fake daemon's rows."""

    def __init__(self, gdir, env=None, ollama=True, script=None):
        super().__init__(env if env is not None
                         else {"OPENROUTER_API_KEY": KEY,
                               "HOME": "/home/owner",
                               "XDG_RUNTIME_DIR": "/run/user/1000"},
                         clock=self._clock, sleep=lambda s: None)
        self.t = 0.0
        self.gdir = pathlib.Path(gdir)
        self.up = ollama
        self.script = script or (lambda goal, arm, n: {})
        self.desktop = FakeDesktop()
        self.daemon_env = None
        self.daemon_up = False
        self.cmds, self.runs, self.n = [], {}, 0
        self.crash_on_run = None
        self.skills_at_run = []

    def _clock(self):
        self.t += 0.01
        return self.t

    def ollama_up(self):
        return self.up

    def spawn_daemon(self, env, log_path):
        self.daemon_env = env
        self.daemon_up = True
        (self.gdir / "data" / "wisp" / "skills").mkdir(parents=True,
                                                       exist_ok=True)
        (self.gdir / "data" / "wisp" / "skills" / "seeded").mkdir(
            exist_ok=True)
        return FakeProc(12345)

    def alive(self):
        return self.daemon_up

    def make_sandbox(self, root):
        return self.desktop.sandbox(root)

    def screenshot(self, path):
        pathlib.Path(path).write_bytes(b"png")
        return True

    @property
    def data(self):
        return self.gdir / "data" / "wisp"

    def send(self, cmd):
        self.cmds.append(cmd)
        c = cmd["cmd"]
        if c == "dev" and cmd.get("op") == "on":
            return {"ok": True}
        if c == "dev":
            return {"ok": True, "run": self.runs.get("last", {})}
        if c == "dev_stop":
            return {"ok": True}
        if c == "dev_run":
            return self._dev_run(cmd)
        raise AssertionError(cmd)

    def _dev_run(self, cmd):
        if self.crash_on_run is not None \
                and self.n >= self.crash_on_run:
            raise self.crash_on_exc
        self.n += 1
        goal = pathlib.Path(cmd["path"]).read_text().strip()
        arm = pathlib.Path(cmd["profiles"][0]).stem
        run_id = f"20261101-00000{self.n}-ab"
        attempt = ("learn" if goal.startswith("learn how to") else
                   2 if self._seen(goal, arm) else 1)
        self.seen.add((goal, arm))
        spec = {"ok": True, "steps": 3, "usd": 0.1, **self.script(
            goal, arm, attempt)}
        skills = sorted(p.name for p in (self.data / "skills").iterdir())
        self.skills_at_run.append((arm, attempt, skills))
        if attempt == "learn":
            (self.data / "skills" / f"learned-{arm}").mkdir()
        turn = f"t{self.n}"
        spend = gmode.Spend(cmd["spend_file"], cmd["cap_usd"])
        remaining = spend.remaining()
        stop = gmode.task_stop_usd(
            gmode.load_profile(cmd["profiles"][0])[1])
        if remaining + 1e-9 < stop:
            self.runs["last"] = {"run_id": run_id, "running": False,
                                 "cap_stop": "spend cap: nothing left"}
            return {"ok": True, "run_id": run_id, "tasks": 1}
        spend.add(spec["usd"], "task")
        spend.add(0.002, "judge")
        row = {"run_id": run_id, "index": 0, "goal": goal, "turn": turn,
               "route": "act", "result": "ACTED (3 steps): ok",
               "steps": [{"tool": "click", "arg": "x", "result": "ok",
                          "ms": 1}] * spec["steps"],
               "outcome": "success" if spec["ok"] else "incomplete",
               "judge": {"outcome": "success" if spec["ok"] else
                         "incomplete", "reason": "r", "cost_usd": 0.002},
               "cost": {"task_usd": spec["usd"], "judge_usd": 0.002,
                        "by_provider": {"openrouter": spec["usd"]}},
               "arm": arm, "model": "m", "provider": "openrouter"}
        d = self.data / "dev_runs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{run_id}.jsonl").write_text(json.dumps(row) + "\n")
        reused = attempt == 2 and spec.get("reused", False)
        if reused:
            with (self.data / "trace.jsonl").open("a") as f:
                f.write(json.dumps({
                    "turn": turn, "step": "app_skill", "kind": "context",
                    "data": {"name": "learned", "matched_by": "window_class",
                             "chars": 120}}) + "\n")
        self.runs["last"] = {"run_id": run_id, "running": False}
        return {"ok": True, "run_id": run_id, "tasks": 1}

    seen: set

    def _seen(self, goal, arm):
        return (goal, arm) in self.seen


def case(cid, **kw):
    c = {"id": cid, "category": "files", "app": "files",
         "goal": f"open the {cid} folder", "setup": {},
         "check": {"type": "judge"}, "learnable": False, "held_out": False,
         "minimal_steps": 2}
    c.update(kw)
    return c


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.gdir = self.tmp / "gauntlet"
        self.bins = BinDir(self.tmp / "bin")
        self.sc = FakeSystemctl(self.bins, {"units": {
            "wispd.service": "active"}})
        p = mock.patch.dict(os.environ, {"PATH": str(self.bins.path)
                                         + os.pathsep + "/usr/bin"})
        p.start()
        self.addCleanup(p.stop)
        self.out = []

    def profiles(self, *names):
        return [(n, n, gmode.load_profile(n)[1]) for n in names]

    def deps(self, **kw):
        d = FakeDeps(self.gdir, **kw)
        d.seen = set()
        return d

    def run_g(self, cases, deps=None, profiles=("hybrid", "openrouter"),
              cap=10.0):
        deps = deps or self.deps()
        g = G.Gauntlet(cases, self.profiles(*profiles), self.gdir, cap,
                       deps, out=self.out.append)
        return g, g.run(), deps


class TestPreconditions(Base):
    def main(self, deps, *argv):
        cf = self.tmp / "cases.jsonl"
        cf.write_text(json.dumps(case("c1")) + "\n")
        return G.main(["--cases", str(cf), "--dir", str(self.gdir), *argv],
                      deps=deps, out=self.out.append)

    def test_without_the_eval_key_it_exits_2_before_stopping_anything(self):
        deps = self.deps(env={"HOME": "/home/owner"})
        self.assertEqual(self.main(deps), 2)
        self.assertEqual(self.sc.commands(), [])
        self.assertEqual(self.sc.state("wispd"), "active")
        self.assertIsNone(deps.daemon_env)
        self.assertTrue(any("orch" in line for line in self.out))

    def test_hybrid_needs_ollama_before_anything_is_stopped(self):
        deps = self.deps(ollama=False)
        self.assertEqual(self.main(deps), 2)
        self.assertEqual(self.sc.commands(), [])
        self.assertIsNone(deps.daemon_env)

    def test_openrouter_alone_does_not_need_ollama(self):
        deps = self.deps(ollama=False)
        self.assertEqual(self.main(deps, "--profiles", "openrouter"), 0)

    def test_bad_arguments_exit_2(self):
        deps = self.deps()
        for argv in (["--profiles", "nope"], ["--cap", "0"],
                     ["--only", "ghost"], ["--profiles", "hybrid,hybrid"]):
            self.assertEqual(self.main(deps, *argv), 2, argv)
        self.assertEqual(self.sc.commands(), [])


class TestServiceSlot(Base):
    def changes(self):
        """The calls that change the service (the probe is not one)."""
        return [c for c in self.sc.commands()
                if not c.startswith("is-active")]

    def test_a_clean_run_stops_then_restores_the_service(self):
        g, code, deps = self.run_g([case("c1")])
        self.assertEqual(code, 0, self.out)
        self.assertEqual(self.changes(),
                         ["stop wispd.service", "start wispd.service"])
        self.assertEqual(self.sc.state("wispd"), "active")
        self.assertEqual(self.sc.violations(), [])

    def test_a_crash_mid_run_still_restarts_the_user_service(self):
        deps = self.deps()
        deps.crash_on_run, deps.crash_on_exc = 1, RuntimeError("boom")
        g, code, _ = self.run_g([case("c1"), case("c2")], deps)
        self.assertEqual(code, 1)
        self.assertEqual(self.changes(),
                         ["stop wispd.service", "start wispd.service"])
        self.assertEqual(self.sc.state("wispd"), "active")
        self.assertIn("boom", g.stopped)
        self.assertTrue((g.rundir / "report.md").exists())

    def test_an_interrupt_restarts_it_too(self):
        deps = self.deps()
        deps.crash_on_run, deps.crash_on_exc = 0, KeyboardInterrupt()
        g, code, _ = self.run_g([case("c1")], deps)
        self.assertEqual(code, 1)
        self.assertEqual(g.stopped, "interrupted")
        self.assertEqual(self.sc.state("wispd"), "active")

    def test_a_service_that_was_off_stays_off(self):
        self.bins.configure("systemctl",
                            {"units": {"wispd.service": "inactive"}})
        (self.bins.path / "systemctl.state.json").unlink(missing_ok=True)
        self.run_g([case("c1")])
        self.assertEqual(self.changes(), [])
        self.assertEqual(self.sc.state("wispd"), "inactive")

    def test_it_will_not_share_a_socket_with_a_live_daemon(self):
        deps = self.deps()
        deps.daemon_up = True
        g, code, _ = self.run_g([case("c1")], deps)
        self.assertEqual(code, 1)
        self.assertIsNone(deps.daemon_env)
        self.assertEqual(self.sc.state("wispd"), "active")


class TestIsolation(Base):
    def test_daemon_env_and_seeded_config_stay_under_the_gauntlet_dir(self):
        g, code, deps = self.run_g([case("c1")])
        env = deps.daemon_env
        for k in ("HOME", "XDG_DATA_HOME", "XDG_CONFIG_HOME",
                  "XDG_STATE_HOME", "XDG_CACHE_HOME"):
            self.assertTrue(env[k].startswith(str(self.gdir)), k)
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(env["OPENROUTER_API_KEY"], KEY)
        cfg = self.gdir / "config" / "wisp" / "config.toml"
        text = cfg.read_text()
        self.assertIn('key_env = "OPENROUTER_API_KEY"', text)
        self.assertNotIn("keyring://", text)
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)

    def test_sandbox_children_see_no_key_and_a_throwaway_home(self):
        g, code, deps = self.run_g([case("c1", app="files"),
                                    case("c2", app="browser",
                                         category="browser"),
                                    case("c3", app="terminal",
                                         category="terminal")],
                                   profiles=("openrouter",))
        self.assertEqual(code, 0, self.out)
        spawned = deps.desktop.spawned
        self.assertEqual({s["app"] for s in spawned},
                         {"files", "browser", "terminal"})
        for s in spawned:
            env = s["env"]
            self.assertNotIn("OPENROUTER_API_KEY", env)
            self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", env)
            self.assertTrue(env["HOME"].startswith(str(self.gdir)),
                            env["HOME"])
            self.assertFalse(any(KEY in v for v in env.values()))
            self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")
            self.assertTrue(s["cwd"].startswith(str(self.gdir)))
        term = next(s for s in spawned if s["app"] == "terminal")
        self.assertIn(str(RSH), term["argv"])
        self.assertTrue(term["env"]["GAUNTLET_ROOT"].startswith(
            str(self.gdir)))
        br = next(s for s in spawned if s["app"] == "browser")
        self.assertTrue(any(a.startswith("--user-data-dir=" + str(self.gdir))
                            for a in br["argv"]))

    def test_the_driver_registers_the_windows_it_spawned(self):
        g, code, deps = self.run_g([case("c1", also=["terminal"])],
                                   profiles=("openrouter",))
        run = next(c for c in deps.cmds if c["cmd"] == "dev_run")
        addrs = [c["address"] for c in deps.desktop.clients_]
        self.assertEqual(run["windows"], addrs)
        self.assertEqual(len(run["windows"]), 2)
        self.assertEqual(run["profiles"], ["openrouter"])
        self.assertEqual(run["spend_file"], str(self.gdir / "spend.jsonl"))

    def test_scrubbed_env_drops_secrets_and_the_session_bus(self):
        env = SB.scrubbed_env(self.tmp / "h", {
            "PATH": "/usr/bin", "OPENROUTER_API_KEY": "x",
            "GITHUB_TOKEN": "y", "DBUS_SESSION_BUS_ADDRESS": "unix:z",
            "HOME": "/home/owner", "WAYLAND_DISPLAY": "wl"})
        self.assertEqual(set(env) & {"OPENROUTER_API_KEY", "GITHUB_TOKEN",
                                     "DBUS_SESSION_BUS_ADDRESS"}, set())
        self.assertEqual(env["HOME"], str(self.tmp / "h"))

    def test_no_window_for_an_app_ends_the_attempt_not_the_run(self):
        deps = self.deps()
        deps.desktop.sandbox = lambda root: SB.Sandbox(
            root, spawn=lambda *a, **k: FakeProc(5), clients=lambda: [],
            move=lambda a, w: None, which=lambda n: "/usr/bin/" + n,
            killpg=lambda *a: None, sleep=lambda s: None,
            clock=iter(range(0, 1000, 10)).__next__, tree=lambda p: {p},
            window_timeout=1)
        g, code, _ = self.run_g([case("c1")], deps, profiles=("openrouter",))
        self.assertEqual(code, 0)
        self.assertIn("no window", g.attempts[0]["error"])


class TestChecksAndEvidence(Base):
    def test_a_title_check_passes_and_a_file_check_fails_with_evidence(self):
        cases = [
            case("c-title", check={"type": "title_regex",
                                   "pattern": "Projects", "app": "files"}),
            case("c-file", check={"type": "file_exists",
                                  "path": "final.txt",
                                  "absent": "draft.txt"},
                 setup={"files": {"draft.txt": "x"}})]
        g, code, deps = self.run_g(cases, profiles=("openrouter",))
        a_title, a_file = g.attempts
        self.assertTrue(a_title["passed"])
        self.assertTrue(a_title["success"])
        self.assertFalse(a_file["passed"])
        self.assertFalse(a_file["success"])      # the judge said success
        for a in (a_title, a_file):
            ev = json.loads(pathlib.Path(a["evidence"]).read_text())
            self.assertEqual(ev["passed"], a["passed"])
            self.assertEqual(ev["case"], a["case"])
            self.assertTrue(pathlib.Path(ev["screenshot"]).exists())
        self.assertFalse(
            json.loads(pathlib.Path(a_file["evidence"]).read_text())
            ["detail"]["exists"])

    def test_the_judge_decides_only_when_there_is_no_check(self):
        g, code, deps = self.run_g(
            [case("c1", check={"type": "judge"})], profiles=("openrouter",))
        self.assertIsNone(g.attempts[0]["passed"])
        self.assertTrue(g.attempts[0]["success"])
        deps2 = self.deps(script=lambda goal, arm, n: {"ok": False})
        g2, _, _ = self.run_g([case("c1")], deps2, profiles=("openrouter",))
        self.assertFalse(g2.attempts[0]["success"])

    def test_a_check_that_cannot_be_read_is_a_failed_check(self):
        box = self.deps().desktop.sandbox(self.gdir / "sb")
        box.prepare({})
        ok, detail = SB.evaluate({"type": "file_exists",
                                  "path": "../outside"}, box)
        self.assertFalse(ok)
        self.assertIn("error", detail)
        self.assertEqual(SB.evaluate({"type": "judge"}, box)[0], None)

    def test_rsh_log_and_window_checks(self):
        d = self.deps()
        box = d.desktop.sandbox(self.gdir / "sb")
        box.prepare({})
        (box.root / "rsh.log").write_text("ok\tls\nrefused\tcurl x\n")
        self.assertTrue(SB.evaluate({"type": "rsh_log",
                                     "pattern": "^ls"}, box)[0])
        self.assertFalse(SB.evaluate({"type": "rsh_log",
                                      "pattern": "^curl"}, box)[0])
        win = box.start("terminal")
        self.assertTrue(SB.evaluate({"type": "window_workspace",
                                     "app": "terminal", "workspace": 1},
                                    box)[0])
        self.assertFalse(SB.evaluate({"type": "window_workspace",
                                      "app": "terminal", "workspace": 2},
                                     box)[0])
        self.assertFalse(SB.evaluate({"type": "geometry_changed",
                                      "app": "terminal", "what": "size"},
                                     box)[0])
        d.desktop.clients_[0]["size"] = [1200, 600]
        self.assertTrue(SB.evaluate({"type": "geometry_changed",
                                     "app": "terminal", "what": "size"},
                                    box)[0])
        self.assertEqual(win.cls, "Alacritty")
        box.close()


class TestSkillAccounting(Base):
    LEARN = dict(learnable=True, minimal_steps=2, skill_seed="nautilus")

    def one(self, r1, r2):
        def script(goal, arm, n):
            return {1: r1, 2: r2}.get(n, {})
        deps = self.deps(script=script)
        g, code, _ = self.run_g([case("c1", **self.LEARN)], deps,
                                profiles=("openrouter",))
        self.assertEqual(code, 0, self.out)
        return g, deps

    def test_a_better_run_2_that_reuses_the_skill_is_a_win(self):
        g, deps = self.one({"ok": False, "steps": 6},
                           {"ok": True, "steps": 3, "reused": True})
        sk = g.attempts[0]["skill"]
        self.assertEqual(sk, {"eligible": True, "win": True,
                              "reason": "won"})
        self.assertEqual(g.summary()["openrouter"]["skill_wins"], 1)
        self.assertEqual(g.attempts[0]["skills_saved"],
                         ["learned-openrouter"])
        # a learn turn ran between the two attempts
        self.assertEqual([a["n"] for a in g.attempts], [1, "learn", 2])
        learn_cmd = [c for c in deps.cmds if c["cmd"] == "dev_run"][1]
        text = pathlib.Path(learn_cmd["path"]).read_text()
        self.assertTrue(text.startswith("learn how to "))

    def test_an_equal_run_2_is_not_a_win(self):
        g, _ = self.one({"ok": True, "steps": 5},
                        {"ok": True, "steps": 5, "reused": True})
        sk = g.attempts[0]["skill"]
        self.assertTrue(sk["eligible"])
        self.assertFalse(sk["win"])
        self.assertEqual(sk["reason"], "no improvement")

    def test_a_better_run_2_that_never_reused_the_skill_is_not_a_win(self):
        g, _ = self.one({"ok": False, "steps": 6},
                        {"ok": True, "steps": 3, "reused": False})
        self.assertEqual(g.attempts[0]["skill"]["reason"],
                         "skill not reused")

    def test_a_run_1_at_minimal_steps_is_left_out_of_the_tally(self):
        g, _ = self.one({"ok": True, "steps": 2},
                        {"ok": True, "steps": 1, "reused": True})
        sk = g.attempts[0]["skill"]
        self.assertEqual((sk["eligible"], sk["win"], sk["reason"]),
                         (False, False, "no headroom"))
        t = g.summary()["openrouter"]
        self.assertEqual((t["skill_eligible"], t["skill_wins"],
                          t["skill_excluded"]), (0, 0, 1))

    def test_pass_or_fail_is_run_1s_check_alone(self):
        g, _ = self.one({"ok": False, "steps": 6},
                        {"ok": True, "steps": 3, "reused": True})
        t = g.summary()["openrouter"]
        self.assertEqual(t["tuning"], [0, 1])      # run 2 does not count

    def test_one_arms_saved_skill_is_gone_before_the_next_arm(self):
        g, _, deps = self.run_g([case("c1", **self.LEARN)],
                                self.deps(),
                                profiles=("hybrid", "openrouter"))
        runs = {(arm, n): sk for arm, n, sk in deps.skills_at_run}
        self.assertEqual(runs[("hybrid", 2)], ["learned-hybrid", "seeded"])
        self.assertEqual(runs[("openrouter", 1)], ["seeded"])

    def test_skill_outcome_is_pure(self):
        c = {"learnable": True, "minimal_steps": 2}
        r = lambda ok, st: {"success": ok, "steps": st}   # noqa: E731
        self.assertTrue(G.skill_outcome(c, r(True, 5), r(True, 4),
                                        True)["win"])
        self.assertFalse(G.skill_outcome(c, r(True, 5), r(True, 4),
                                         False)["win"])
        self.assertFalse(G.skill_outcome(
            {"learnable": False, "minimal_steps": 2}, r(False, 5),
            r(True, 1), True)["eligible"])


class TestCapAndReport(Base):
    def test_with_the_cap_nearly_spent_both_arms_stop_at_the_same_case(self):
        script = lambda goal, arm, n: {"usd": 0.3}      # noqa: E731
        deps = self.deps(script=script)
        cases = [case("c1"), case("c2"), case("c3")]
        # two arms reserve 0.50 a case: 1.0 covers case 1, then 0.40 left
        g, code, _ = self.run_g(cases, deps, cap=1.0)
        self.assertEqual(code, 0)
        per_arm = {arm: [a["case"] for a in g.attempts if a["arm"] == arm]
                   for arm in ("hybrid", "openrouter")}
        self.assertEqual(per_arm["hybrid"], ["c1"])
        self.assertEqual(per_arm["hybrid"], per_arm["openrouter"])
        self.assertIn("spend cap", g.stopped)
        self.assertIn("c2", g.stopped)
        # a later invocation still counts what this one spent
        self.assertAlmostEqual(
            gmode.Spend(self.gdir / "spend.jsonl", 1.0).total(), 0.604,
            places=3)

    def test_the_report_ranks_tuning_failures_and_lists_spend_per_arm(self):
        def script(goal, arm, n):
            return {"ok": "tune-ok" in goal or "held" in goal and
                    arm == "openrouter"}
        cases = [case("tune-ok"), case("tune-bad-1"), case("tune-bad-2"),
                 case("held", held_out=True)]
        g, code, deps = self.run_g(cases, self.deps(script=script))
        ranked = g.ranked_failures()
        self.assertEqual(ranked[0][1].__len__(), 4)   # 2 cases x 2 arms
        flat = {a["case"] for _c, items in ranked for a in items}
        self.assertEqual(flat, {"tune-bad-1", "tune-bad-2"})   # no held-out
        sm = g.summary()
        self.assertEqual(sm["hybrid"]["tuning"], [1, 3])
        self.assertEqual(sm["hybrid"]["held_out"], [0, 1])
        self.assertEqual(sm["openrouter"]["held_out"], [1, 1])
        text = (g.rundir / "report.md").read_text()
        self.assertIn("| hybrid |", text)
        self.assertIn("| openrouter |", text)
        self.assertIn("openrouter $", text)           # spend by provider
        self.assertIn("wispd dev review " + g.run_id, text)
        self.assertIn(f"wispd dev import-labels {g.data}", text)
        self.assertIn("XDG_DATA_HOME=" + str(self.gdir / "data"), text)

    def test_the_merged_run_store_reports_with_named_arms(self):
        g, code, deps = self.run_g([case("c1"), case("c2")])
        for obj, name, val in (
                (config, "DATA_DIR", g.data),
                (config, "DECISIONS", g.data / "decisions.jsonl"),
                (learn, "LABELS_FILE", g.data / "labels.jsonl")):
            p = mock.patch.object(obj, name, val)
            p.start()
            self.addCleanup(p.stop)
        run = devreport.build(g.run_id)["runs"][0]
        self.assertEqual(sorted(run["arms"]), ["hybrid", "openrouter"])
        self.assertEqual(len(run["pairs"]), 2)

    def test_a_spend_stop_inside_the_daemon_ends_the_run(self):
        spend = gmode.Spend(self.gdir / "spend.jsonl", 10.0)
        spend.add(9.9, "task")
        g, code, _ = self.run_g([case("c1")], profiles=("openrouter",))
        self.assertEqual(code, 0)
        self.assertIn("spend cap", g.stopped)
        self.assertTrue((g.rundir / "report.md").exists())


class TestRestrictedShell(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = pathlib.Path(td.name)
        (self.root / "a.txt").write_text("hello\n")
        (self.root / "victim.txt").write_text("keep")

    def rsh(self, line, stdin=None):
        env = {"PATH": "/usr/bin:/bin", "GAUNTLET_ROOT": str(self.root),
               "OPENROUTER_API_KEY": KEY}
        return subprocess.run([sys.executable, str(RSH), "-c", line]
                              if stdin is None else
                              [sys.executable, str(RSH)],
                              input=stdin, capture_output=True, text=True,
                              cwd=self.root, env=env, timeout=30)

    def test_it_runs_ls_and_refuses_curl_env_rm_and_git_push(self):
        r = self.rsh("ls")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a.txt", r.stdout)
        for bad in ("curl https://example.com", "env", "rm victim.txt",
                    "git push", "sh -c ls", "python3 -c 1", "sudo ls"):
            r = self.rsh(bad)
            self.assertEqual(r.returncode, 126, bad)
            self.assertIn("refused", r.stdout, bad)
        self.assertTrue((self.root / "victim.txt").exists())

    def test_shell_syntax_cannot_chain_or_write(self):
        for bad in ("ls; rm victim.txt", "ls && rm victim.txt",
                    "ls | cat", "echo x > pwned", "ls $(id)", "ls `id`",
                    "cat a.txt >> victim.txt", "ls *", "echo $HOME"):
            r = self.rsh(bad)
            self.assertEqual(r.returncode, 126, bad)
        self.assertFalse((self.root / "pwned").exists())
        self.assertEqual((self.root / "victim.txt").read_text(), "keep")

    def test_paths_stay_inside_the_sandbox(self):
        self.assertEqual(self.rsh("cat a.txt").returncode, 0)
        for bad in ("cat /etc/passwd", "cat ../x", "ls /",
                    "ls /home", "head -n 1 /etc/hostname"):
            self.assertEqual(self.rsh(bad).returncode, 126, bad)
        (self.root / "link").symlink_to("/etc")
        self.assertEqual(self.rsh("ls link").returncode, 126)

    def test_it_never_hands_over_the_environment(self):
        for line in ("echo hi", "date +%Y", "pwd", "whoami"):
            self.assertEqual(self.rsh(line).returncode, 0, line)
        self.assertEqual(self.rsh("date -s 1999-01-01").returncode, 126)

    def test_the_log_records_every_line_and_verdict(self):
        self.rsh("ls")
        self.rsh("curl x")
        rows = [ln.split("\t") for ln in
                (self.root / "rsh.log").read_text().splitlines()]
        self.assertEqual(rows, [["ok", "ls"], ["refused", "curl x"]])

    def test_interactive_mode_reads_lines_until_exit(self):
        r = self.rsh(None, stdin="ls\ncurl x\ncd nowhere\nexit\nls\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("a.txt", r.stdout)
        self.assertIn("refused", r.stdout)
        log = (self.root / "rsh.log").read_text().splitlines()
        self.assertEqual(len(log), 3)             # nothing after exit

    def test_cd_stays_inside_and_changes_the_working_directory(self):
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.txt").write_text("b")
        r = self.rsh(None, stdin="cd sub\nls\ncd ..\ncd ..\nexit\n")
        self.assertIn("b.txt", r.stdout)
        self.assertIn("refused", r.stdout)        # cd .. out of the root


if __name__ == "__main__":
    unittest.main()
