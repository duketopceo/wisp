#!/usr/bin/env python3
"""W28: `wispd onboard` and its step engine (wisp/onboard.py).

Every probe is injected (no network, no services, no notifications): the
unit tests drive the engine with fakes inside a temp HOME, the CLI tests
run the real wispd with PATH cut down to an empty shim dir.
"""
import hashlib
import http.server
import json
import pathlib
import socket
import sys
import threading
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import shorttmp  # noqa: E402
from cli_env import CliEnv  # noqa: E402

from wisp import agent_install, agent_pins, config, onboard  # noqa: E402

LADDER_URLS = {u for _n, u in onboard.LADDER}


class Fakes:
    """Injected probes that record every call."""

    def __init__(self, up=None, cua="running", notify="sent", submap=False,
                 recorder=True, model=True, notifier=True, keys=None,
                 secrets=(), agents="ready", smoke=(True, "ok"),
                 browser=(True, "signed in")):
        self.up = set(LADDER_URLS if up is None else up)
        self.fetched = []
        self.sent = 0
        self.cua_state = cua
        self.notify_result = notify
        self.submap_present = submap
        self.recorder = recorder
        self.model = model
        self.notifier = notifier
        self.keys = {"OPENROUTER_API_KEY", "GROQ_API_KEY"} \
            if keys is None else set(keys)
        self.secrets = list(secrets)
        self.stored = []
        self.agents_state = agents
        self.installed = []
        self.logins = []     # ("key", ori, key) or ("browser", ori)
        self.smokes = 0
        self.smoke_result = smoke
        self.browser_result = browser

    def probes(self):
        def agents(cfg):
            ok = self.agents_state in ("installed", "ready")
            return {"state": self.agents_state, "ok": ok,
                    "fix": "wispd install --agents"}

        def install(tool):
            self.installed.append(tool)
            if self.agents_state in ("absent", "opencode_v1",
                                     "wrong_version") \
                    and len(self.installed) % 2 == 0:
                self.agents_state = "not_signed_in"
            return agent_install.Result("installed")

        def login_key(ori, key):
            self.logins.append(("key", str(ori), key))
            self.agents_state = "ready"
            return True, "signed in"

        def login_browser(ori):
            self.logins.append(("browser", str(ori)))
            if self.browser_result[0]:
                self.agents_state = "ready"
            return self.browser_result

        def smoke(cfg):
            self.smokes += 1
            return self.smoke_result

        def fetch(url):
            self.fetched.append(url)
            return url in self.up

        def cua(cfg):
            ok = self.cua_state in ("running", "dry_run")
            return {"state": self.cua_state, "ok": ok, "fix": "wispd cua status"}

        def send(cfg):
            self.sent += 1
            return self.notify_result

        def store(key_env, value):
            self.stored.append((key_env, value))
            self.keys.add(key_env)
            return "fake store"

        def secret(prompt):
            if not self.secrets:
                raise EOFError
            return self.secrets.pop(0)

        return onboard.Probes(
            which=lambda n: "/usr/bin/" + n if self.recorder else None,
            whisper_ok=lambda cfg: self.model,
            fetch=fetch, cua=cua,
            notify_ready=lambda: self.notifier, notify_send=send,
            submap=lambda: self.submap_present,
            key=lambda env: "k" if env in self.keys else "",
            store_key=store, secret=secret, agents=agents,
            agent_install=install, ori_login_key=login_key,
            ori_login_browser=login_browser, acp_smoke=smoke)


def tree(root):
    out = {}
    for p in sorted(pathlib.Path(root).rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha1(
                p.read_bytes()).hexdigest()
    return out


class Scripted:
    """ask() stand-in: pops answers, remembers each prompt."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


class OnboardCase(unittest.TestCase):
    def setUp(self):
        self._td = shorttmp.TemporaryDirectory()
        self.home = pathlib.Path(self._td.name)
        self.data = self.home / ".local" / "share" / "wisp"
        self.cfgdir = self.home / ".config" / "wisp"
        patches = [
            mock.patch.object(config, "DATA_DIR", self.data),
            mock.patch.object(config, "CFG_DIR", self.cfgdir),
            mock.patch.object(config, "CFG_FILE",
                              self.cfgdir / "config.toml"),
            mock.patch("subprocess.run", side_effect=AssertionError(
                "onboarding must not run commands")),
            mock.patch("subprocess.Popen", side_effect=AssertionError(
                "onboarding must not spawn processes")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._td.cleanup)
        self.cfg = {"local": {"enabled": "true"}}
        self.out = []
        self.progress = onboard.Progress()

    def walk(self, fakes, *answers):
        ask = Scripted(*answers)
        res = onboard.walk(self.cfg, fakes.probes(), self.progress, ask,
                           self.out.append)
        return res, ask


class TestSteps(OnboardCase):
    def test_step_order(self):
        self.assertEqual([s.id for s in onboard.STEPS],
                         ["mic", "models", "keys", "agents", "cua",
                          "notifications", "keybinding"])
        self.assertEqual([s.id for s in onboard.STEPS if s.optional],
                         ["agents", "cua", "keybinding"])

    def test_mic_needs_recorder_and_model(self):
        r = onboard.check("mic", self.cfg, Fakes().probes())
        self.assertEqual(r["state"], "ok")
        r = onboard.check("mic", self.cfg, Fakes(recorder=False).probes())
        self.assertEqual(r["state"], "todo")
        self.assertTrue(r["fix"])
        r = onboard.check("mic", self.cfg, Fakes(model=False).probes())
        self.assertEqual(r["state"], "todo")

    def test_models_probe_the_whole_local_ladder_and_nothing_else(self):
        f = Fakes(up={"http://127.0.0.1:8080/v1/models"})
        r = onboard.check("models", self.cfg, f.probes())
        self.assertEqual(sorted(f.fetched), sorted(LADDER_URLS))
        self.assertEqual(r["state"], "ok")
        self.assertIn("ornith up", r["detail"])
        self.assertIn("ollama down", r["detail"])
        names = [n for n, _ in onboard.LADDER]
        self.assertEqual(names, ["ornith", "jev", "jev-shim", "uitars",
                                 "ollama"])
        ports = sorted(u.split(":")[2].split("/")[0]
                       for _n, u in onboard.LADDER)
        self.assertEqual(ports, ["11434", "8080", "8081", "8091", "8931"])
        for _n, u in onboard.LADDER:
            self.assertTrue(u.startswith("http://127.0.0.1:"), u)

    def test_models_local_off_probes_nothing_and_passes(self):
        f = Fakes(up=set())
        r = onboard.check("models", {}, f.probes())
        self.assertEqual(f.fetched, [])
        self.assertEqual(r["state"], "ok")
        self.assertIn("local models off", r["detail"])

    def test_models_none_up_is_todo_with_the_manual_fix(self):
        r = onboard.check("models", self.cfg, Fakes(up=set()).probes())
        self.assertEqual(r["state"], "todo")
        self.assertIn("wispd health start", r["fix"])

    def test_cua_absent_is_not_available_and_broken_is_todo(self):
        self.assertEqual(onboard.check(
            "cua", self.cfg, Fakes(cua="absent").probes())["state"], "na")
        self.assertEqual(onboard.check(
            "cua", self.cfg, Fakes(cua="socket_unresponsive").probes()
        )["state"], "todo")
        self.assertEqual(onboard.check(
            "cua", self.cfg, Fakes(cua="running").probes())["state"], "ok")

    def test_keybinding_is_na_without_the_w24_submap(self):
        r = onboard.check("keybinding", self.cfg, Fakes().probes())
        self.assertEqual(r["state"], "na")
        self.assertIn("submap", r["detail"])
        r = onboard.check("keybinding", self.cfg,
                          Fakes(submap=True).probes())
        self.assertEqual(r["state"], "ok")

    def test_notification_test_send_only_on_explicit_confirm(self):
        f = Fakes()
        r = onboard.run_step("notifications", self.cfg, f.probes(),
                             self.progress, confirm=False)
        self.assertEqual(r["state"], "todo")
        self.assertFalse(r["done"])
        self.assertEqual(f.sent, 0)
        self.assertFalse(self.progress.path.exists())
        r = onboard.run_step("notifications", self.cfg, f.probes(),
                             self.progress, confirm=True)
        self.assertTrue(r["done"])
        self.assertEqual(f.sent, 1)
        self.assertIn("notifications", json.loads(
            self.progress.path.read_text())["done"])

    def test_failed_test_send_is_not_recorded(self):
        f = Fakes(notify="disabled")
        r = onboard.run_step("notifications", self.cfg, f.probes(),
                             self.progress, confirm=True)
        self.assertFalse(r["done"])
        self.assertEqual(r["state"], "todo")
        self.assertFalse(self.progress.path.exists())


ORI = agent_pins.runtime_paths(pathlib.Path("/rt"))["ori"]


class TestAgentsStep(OnboardCase):
    def conf_path(self):
        return (self.data / "agent-runtime" / "home" / "config"
                / "opencode" / "opencode.json")

    def run_agents(self, f):
        return onboard.run_step("agents", self.cfg, f.probes(),
                                self.progress)

    def test_step_is_optional_and_sits_after_keys(self):
        ids = [s.id for s in onboard.STEPS]
        self.assertEqual(ids[ids.index("keys") + 1], "agents")
        self.assertTrue(next(s for s in onboard.STEPS
                             if s.id == "agents").optional)

    def test_all_ready_is_ok_and_run_is_a_noop(self):
        f = Fakes(agents="ready")
        r = self.run_agents(f)
        self.assertEqual((r["state"], r["done"]), ("ok", True))
        self.assertEqual((f.installed, f.logins, f.smokes), ([], [], 0))
        self.assertFalse(self.conf_path().exists())

    def test_absent_installs_signs_in_with_the_key_and_smoke_tests(self):
        f = Fakes(agents="absent")
        r = self.run_agents(f)
        self.assertEqual((r["state"], r["done"]), ("ok", True), r)
        self.assertEqual(f.installed, ["ori", "opencode"])
        self.assertEqual(len(f.logins), 1)
        kind, ori, key = f.logins[0]
        self.assertEqual((kind, key), ("key", "k"))
        self.assertTrue(ori.endswith("agent-runtime/ori/current/ori"), ori)
        self.assertEqual(f.smokes, 1)
        self.assertTrue(self.conf_path().is_file())
        self.assertIn("agents", self.progress.done)

    def test_no_stored_key_takes_the_browser_path(self):
        f = Fakes(agents="not_signed_in", keys=())
        r = self.run_agents(f)
        self.assertEqual(r["state"], "ok", r)
        self.assertEqual(f.installed, [])   # already installed
        self.assertEqual([x[0] for x in f.logins], ["browser"])

    def test_browser_timeout_is_todo_and_marks_nothing(self):
        f = Fakes(agents="not_signed_in", keys=(),
                  browser=(False, "sign-in did not finish"))
        r = self.run_agents(f)
        self.assertEqual((r["state"], r["done"]), ("todo", False))
        self.assertIn("sign-in did not finish", r["detail"])
        self.assertEqual(f.smokes, 0)
        self.assertEqual(self.progress.done, {})
        self.assertFalse(self.conf_path().exists())

    def test_smoke_failure_is_todo_and_writes_no_config(self):
        f = Fakes(agents="not_signed_in", smoke=(False, "no ACP reply"))
        r = self.run_agents(f)
        self.assertEqual((r["state"], r["done"]), ("todo", False))
        self.assertIn("no ACP reply", r["detail"])
        self.assertFalse(self.conf_path().exists())

    def test_opencode_1x_still_installs_the_pinned_2x(self):
        f = Fakes(agents="opencode_v1")
        r = self.run_agents(f)
        self.assertEqual(r["state"], "ok", r)
        self.assertEqual(f.installed, ["ori", "opencode"])

    def test_failed_install_is_todo_with_the_reason(self):
        f = Fakes(agents="absent")
        probes = f.probes()
        probes.agent_install = lambda tool: agent_install.Result(
            "failed", f"{tool} download failed")
        r = onboard.run_step("agents", self.cfg, probes, self.progress)
        self.assertEqual((r["state"], r["done"]), ("todo", False))
        self.assertIn("download failed", r["detail"])
        self.assertEqual(f.logins, [])

    def test_detail_discloses_memory_reads_go_to_openrouter(self):
        for state in ("absent", "not_signed_in", "ready"):
            r = onboard.check("agents", self.cfg,
                              Fakes(agents=state).probes())
            self.assertIn("memory", r["detail"], state)
            self.assertIn("OpenRouter", r["detail"], state)

    def test_check_states(self):
        ck = lambda st: onboard.check(  # noqa: E731
            "agents", self.cfg, Fakes(agents=st).probes())
        self.assertEqual(ck("ready")["state"], "ok")
        for st in ("absent", "opencode_v1", "wrong_version",
                   "not_signed_in"):
            self.assertEqual(ck(st)["state"], "todo", st)
        self.assertIn("1.x", ck("opencode_v1")["detail"])


class TestDoctorAgents(unittest.TestCase):
    class Probe:
        def __init__(self, state, ok):
            self.r = {"state": state, "ok": ok, "code": None,
                      "fix": "wispd install --agents", "ori": "0.16.1",
                      "opencode": "2.2.0"}

        def check(self, auth=True):
            return self.r

    def rows(self, state, ok):
        from wisp.cli import diagnose
        secs = diagnose.doctor_sections(
            {}, agents_probe=self.Probe(state, ok))
        sec = next(x for x in secs if x["name"] == "agents")
        return {r["name"]: r for r in sec["rows"]}

    def test_ready_runtime_row_is_ok(self):
        rows = self.rows("ready", True)
        self.assertTrue(rows["agent runtime"]["ok"])
        self.assertIn("ready", rows["agent runtime"]["value"])

    def test_absent_is_optional_so_not_a_failure(self):
        r = self.rows("absent", False)["agent runtime"]
        self.assertTrue(r["ok"])
        self.assertIn("wispd install --agents", r["value"])

    def test_broken_install_is_a_failure(self):
        for state in ("opencode_v1", "wrong_version", "not_signed_in"):
            r = self.rows(state, False)["agent runtime"]
            self.assertFalse(r["ok"], state)

    def test_says_the_live_permission_gate_check_was_not_run(self):
        g = self.rows("ready", True)["agent permission gate"]
        self.assertIn("not run", g["value"])
        self.assertTrue(g["ok"])


class TestOriLogin(unittest.TestCase):
    """The default login probes against a fake ori (no network)."""

    FAKE = (
        "#!%s\n"
        "import json, os, sys, time\n"
        "d = os.environ['FAKE_ORI_DIR']\n"
        "open(d + '/argv', 'w').write(json.dumps(sys.argv[1:]))\n"
        "if '--with-key' in sys.argv:\n"
        "    open(d + '/stdin', 'w').write(sys.stdin.read())\n"
        "elif '--no-browser' in sys.argv:\n"
        "    print('Open https://openrouter.ai/auth?cb=1 to sign in', "
        "flush=True)\n"
        "    time.sleep(float(os.environ.get('FAKE_ORI_WAIT', '0.2')))\n"
    ) % sys.executable

    def setUp(self):
        self.td = shorttmp.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.dir = pathlib.Path(self.td.name)
        self.ori = self.dir / "ori"
        self.ori.write_text(self.FAKE)
        self.ori.chmod(0o755)
        p = mock.patch.dict("os.environ", {"FAKE_ORI_DIR": str(self.dir)})
        p.start()
        self.addCleanup(p.stop)

    def test_key_goes_on_stdin_and_never_on_argv(self):
        ok, _detail = onboard._ori_login_key(self.ori, "sk-or-test")
        self.assertTrue(ok)
        self.assertEqual(json.loads((self.dir / "argv").read_text()),
                         ["login", "--with-key"])
        self.assertEqual((self.dir / "stdin").read_text(), "sk-or-test\n")
        self.assertNotIn("sk-or-test", (self.dir / "argv").read_text())

    def test_browser_path_opens_the_printed_url(self):
        opened = []
        ok, _d = onboard._ori_login_browser(
            self.ori, opener=opened.append, timeout_s=10)
        self.assertTrue(ok)
        self.assertEqual(opened, ["https://openrouter.ai/auth?cb=1"])
        self.assertEqual(json.loads((self.dir / "argv").read_text()),
                         ["login", "--no-browser"])

    def test_browser_path_gives_up_after_the_timeout(self):
        with mock.patch.dict("os.environ", {"FAKE_ORI_WAIT": "30"}):
            ok, detail = onboard._ori_login_browser(
                self.ori, opener=lambda u: None, timeout_s=1)
        self.assertFalse(ok)
        self.assertIn("sign-in did not finish", detail)


class TestFlow(OnboardCase):
    def test_fresh_home_full_flow_records_every_available_step(self):
        before = tree(self.home)
        self.assertEqual(before, {})
        f = Fakes()
        res, ask = self.walk(f, "y", "y", "y", "y", "y", "y")
        done = json.loads(self.progress.path.read_text())["done"]
        self.assertEqual(sorted(done), ["agents", "cua", "keys", "mic",
                                        "models", "notifications"])
        self.assertEqual(f.sent, 1)
        self.assertEqual(res["done"], ["mic", "models", "keys", "agents",
                                       "cua", "notifications"])
        self.assertEqual(res["na"], ["keybinding"])
        self.assertEqual(len(ask.prompts), 6)  # no prompt for the na step
        # only the progress file was written, no config
        self.assertEqual(sorted(tree(self.home)),
                         [".local/share/wisp/onboard.json"])

    def test_partial_completion_resumes_where_it_stopped(self):
        f = Fakes()
        res, ask = self.walk(f, "y", "q")
        self.assertEqual(res["done"], ["mic"])
        self.assertTrue(res["quit"])
        self.assertEqual(json.loads(self.progress.path.read_text())["done"]
                         .keys(), {"mic"})
        # a new process: fresh Progress object, same file
        self.progress = onboard.Progress()
        f2 = Fakes()
        res, ask = self.walk(f2, "y", "y", "y", "y", "y")
        self.assertEqual(res["resumed"], ["mic"])
        self.assertEqual(res["done"], ["mic", "models", "keys", "agents",
                                       "cua", "notifications"])
        self.assertEqual(len(ask.prompts), 5)
        self.assertFalse(any("mic" in p.lower() for p in ask.prompts))
        self.assertEqual(f2.sent, 1)

    def test_skip_writes_nothing_at_all(self):
        f = Fakes()
        res, ask = self.walk(f, "s", "s", "s", "s", "s", "s")
        self.assertEqual(tree(self.home), {})
        self.assertEqual(sorted(res["skipped"]),
                         ["agents", "cua", "keys", "mic", "models",
                          "notifications"])
        self.assertEqual(res["done"], [])
        self.assertEqual(f.sent, 0)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.cfgdir.exists())

    def test_skip_one_then_finish_the_rest(self):
        res, _ = self.walk(Fakes(), "s", "y", "s", "s", "s", "n")
        self.assertEqual(res["done"], ["models"])
        self.assertEqual(sorted(res["skipped"]),
                         ["agents", "cua", "keys", "mic", "notifications"])
        # skipped steps are asked again next time
        self.progress = onboard.Progress()
        res, ask = self.walk(Fakes(), "q")
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("microphone", ask.prompts[0].lower())

    def test_a_failing_step_is_not_recorded_and_flow_continues(self):
        f = Fakes(up=set())
        res, _ = self.walk(f, "y", "y", "y", "y", "y", "y")
        self.assertNotIn("models", res["done"])
        self.assertIn("models", res["failed"])
        self.assertIn("mic", res["done"])

    def test_eof_on_a_closed_stdin_stops_cleanly(self):
        res, _ = self.walk(Fakes())
        self.assertTrue(res["quit"])
        self.assertEqual(tree(self.home), {})

    def test_every_step_is_reversible(self):
        self.walk(Fakes(), "y", "y", "y", "y", "y", "y")
        for sid in ("mic", "models", "keys", "agents", "cua",
                    "notifications"):
            self.assertTrue(onboard.undo(sid, self.progress)["undone"], sid)
        self.assertEqual(json.loads(self.progress.path.read_text())["done"],
                         {})
        self.assertFalse(onboard.undo("mic", self.progress)["undone"])
        with self.assertRaises(KeyError):
            onboard.undo("nope", self.progress)

    def test_reset_removes_the_progress_file(self):
        self.walk(Fakes(), "y", "q")
        self.assertTrue(self.progress.path.exists())
        self.progress.reset()
        self.assertFalse(self.progress.path.exists())

    def test_finish_marks_setup_done_and_hides_the_card(self):
        st = onboard.status(self.cfg, Fakes().probes(), self.progress)
        self.assertFalse(st["finished"])
        self.progress.finish()
        st = onboard.status(self.cfg, Fakes().probes(), self.progress)
        self.assertTrue(st["finished"])

    def test_all_required_steps_done_finishes_the_run(self):
        self.walk(Fakes(), "y", "y", "y", "y", "n", "y")
        st = onboard.status(self.cfg, Fakes().probes(),
                            onboard.Progress())
        self.assertTrue(st["finished"])  # cua and keybinding are optional

    def test_single_steps_finish_setup_once_the_required_ones_pass(self):
        f = Fakes()
        for sid in ("mic", "models", "keys"):
            onboard.run_step(sid, self.cfg, f.probes(), self.progress)
            self.assertFalse(self.progress.finished, sid)
        onboard.run_step("notifications", self.cfg, f.probes(),
                         self.progress, confirm=True)
        self.assertTrue(self.progress.finished)
        onboard.undo("mic", self.progress)
        self.assertFalse(self.progress.finished)

    def test_corrupt_progress_file_reads_as_empty(self):
        self.data.mkdir(parents=True)
        (self.data / "onboard.json").write_text("{not json")
        self.assertEqual(onboard.Progress().done, {})


class TestStatus(OnboardCase):
    def test_status_shape_for_the_panel_card(self):
        self.walk(Fakes(), "y", "q")
        st = onboard.status(self.cfg, Fakes().probes(), onboard.Progress())
        self.assertEqual([s["id"] for s in st["steps"]],
                         ["mic", "models", "keys", "agents", "cua",
                          "notifications", "keybinding"])
        mic = st["steps"][0]
        self.assertEqual(mic["state"], "done")
        self.assertTrue(mic["done"] and mic["ok"])
        self.assertEqual(st["steps"][1]["state"], "todo")
        self.assertEqual(st["steps"][6]["state"], "na")
        for s in st["steps"]:
            for k in ("id", "name", "optional", "state", "ok", "done",
                      "detail", "try"):
                self.assertIn(k, s)
        self.assertEqual(st["done_count"], 1)
        self.assertEqual(st["total"], 6)  # na steps do not count

    def test_status_writes_nothing(self):
        onboard.status(self.cfg, Fakes().probes(), self.progress)
        self.assertEqual(tree(self.home), {})


class TestKeys(OnboardCase):
    def test_both_keys_resolve_is_ok(self):
        r = onboard.check("keys", self.cfg, Fakes().probes())
        self.assertEqual(r["state"], "ok")

    def test_missing_stt_key_is_todo_naming_it(self):
        f = Fakes(keys={"OPENROUTER_API_KEY"})
        r = onboard.check("keys", self.cfg, f.probes())
        self.assertEqual(r["state"], "todo")
        self.assertIn("GROQ_API_KEY", r["detail"])
        self.assertNotIn("OPENROUTER_API_KEY", r["detail"])

    def test_local_stt_needs_only_the_brain_key(self):
        cfg = {"stt": {"provider": "local"}}
        self.assertEqual(onboard.required_keys(cfg),
                         [("brain", "OPENROUTER_API_KEY")])

    def test_walk_stores_a_pasted_key_and_never_prints_it(self):
        f = Fakes(keys={"OPENROUTER_API_KEY"}, secrets=["gsk-secret-1"])
        res, _ = self.walk(f, "s", "s", "y", "q")
        self.assertEqual(f.stored, [("GROQ_API_KEY", "gsk-secret-1")])
        self.assertIn("keys", res["done"])
        self.assertNotIn("gsk-secret-1", "\n".join(self.out))
        self.assertIn("GROQ_API_KEY", "\n".join(self.out))

    def test_blank_paste_stores_nothing_and_leaves_the_step_todo(self):
        f = Fakes(keys=set(), secrets=["", ""])
        res, _ = self.walk(f, "s", "s", "y", "q")
        self.assertEqual(f.stored, [])
        self.assertIn("keys", res["failed"])


class TestStoreKey(unittest.TestCase):
    def setUp(self):
        self._td = shorttmp.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = pathlib.Path(self._td.name)
        self.env = self.tmp / "cfg" / ".env"
        p = mock.patch.object(config, "ENV_FILE", self.env)
        p.start()
        self.addCleanup(p.stop)

    def _no_omaseal(self):
        p = mock.patch("shutil.which", return_value=None)
        p.start()
        self.addCleanup(p.stop)

    def test_without_omaseal_writes_env_file_0600_and_it_resolves(self):
        self._no_omaseal()
        where = onboard._store_key("GROQ_API_KEY", "gsk-abc")
        self.assertEqual(where, str(self.env))
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(config.load_env_key("GROQ_API_KEY"), "gsk-abc")

    def test_existing_0644_env_becomes_0600_and_keeps_other_keys(self):
        self._no_omaseal()
        self.env.parent.mkdir(parents=True)
        self.env.write_text("OTHER=1\nGROQ_API_KEY=old\n")
        self.env.chmod(0o644)
        onboard._store_key("GROQ_API_KEY", "gsk-new")
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env.read_text(),
                         "OTHER=1\nGROQ_API_KEY=gsk-new\n")

    def test_value_with_newline_or_space_is_refused_and_writes_nothing(self):
        self._no_omaseal()
        for bad in ("a\nb", "a b", "", "a\tb"):
            with self.assertRaises(ValueError):
                onboard._store_key("GROQ_API_KEY", bad)
        self.assertFalse(self.env.exists())

    def test_omaseal_ref_in_the_lookup_list_is_where_it_is_stored(self):
        ring = self.tmp / "ring"
        fake = self.tmp / "bin" / "omaseal"
        fake.parent.mkdir()
        fake.write_text(
            '#!/bin/sh\ncase "$1" in\n'
            f'set) cat > "{ring}.$2.$3" ;;\n'
            f'get) cat "{ring}.$2.$3" ;;\nesac\n')
        fake.chmod(0o755)
        key_env = "omaseal://groq/default,GROQ_API_KEY"
        with mock.patch.dict("os.environ",
                             {"PATH": f"{fake.parent}:/usr/bin:/bin"}):
            where = onboard._store_key(key_env, "gsk-ring")
            self.assertEqual(where, "omaseal groq/default")
            self.assertEqual(config.load_env_key(key_env), "gsk-ring")
        self.assertFalse(self.env.exists())
        self.assertEqual((self.tmp / "ring.groq.default").read_text(),
                         "gsk-ring")

    def _secret_tool(self, body):
        f = self.tmp / "sbin" / "secret-tool"
        f.parent.mkdir(exist_ok=True)
        self.argv_log = self.tmp / "argv.log"
        self.stdin_log = self.tmp / "stdin.log"
        f.write_text(f'#!/bin/sh\necho "$@" >> "{self.argv_log}"\n{body}\n')
        f.chmod(0o755)
        return mock.patch.dict(
            "os.environ", {"PATH": f"{f.parent}:/usr/bin:/bin"})

    def test_keyring_ref_stores_in_secret_tool_value_on_stdin_only(self):
        key_env = "keyring://wisp/openrouter,OPENROUTER_API_KEY"
        with self._secret_tool(f'cat > "{self.tmp}/stdin.log"'):
            where = onboard._store_key(key_env, "sk-or-v1-secret")
        self.assertEqual(where, "desktop keyring")
        self.assertEqual((self.tmp / "stdin.log").read_text(),
                         "sk-or-v1-secret")
        argv = self.argv_log.read_text()
        self.assertNotIn("sk-or-v1-secret", argv)
        self.assertIn("store --label Wisp openrouter service wisp "
                      "account openrouter", argv)
        self.assertFalse(self.env.exists())

    def test_keyring_ref_without_a_working_keyring_writes_env_0600(self):
        key_env = "keyring://wisp/openrouter,OPENROUTER_API_KEY"
        with self._secret_tool("cat >/dev/null; exit 1"):
            where = onboard._store_key(key_env, "sk-or-v1-file")
        self.assertEqual(where, str(self.env))
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.env.read_text(),
                         "OPENROUTER_API_KEY=sk-or-v1-file\n")

    def test_keyring_ref_with_no_secret_tool_writes_env_0600(self):
        self._no_omaseal()
        where = onboard._store_key(
            "keyring://wisp/openrouter,OPENROUTER_API_KEY", "sk-or-v1-f")
        self.assertEqual(where, str(self.env))
        self.assertEqual(self.env.stat().st_mode & 0o777, 0o600)


class TestDefaultFetch(unittest.TestCase):
    def test_http_answer_means_up_and_refused_means_down(self):
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(404 if self.path == "/nope" else 200)
                self.end_headers()

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        port = srv.server_address[1]
        self.assertTrue(onboard.http_up(f"http://127.0.0.1:{port}/x"))
        self.assertTrue(onboard.http_up(f"http://127.0.0.1:{port}/nope"))
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        dead = s.getsockname()[1]
        s.close()
        self.assertFalse(onboard.http_up(f"http://127.0.0.1:{dead}/x"))

    def test_only_loopback_is_probed(self):
        self.assertFalse(onboard.http_up("http://example.com/"))


class TestCli(unittest.TestCase):
    def test_status_json_is_a_fresh_checklist_and_exits_zero(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--status", "--json"])
            self.assertEqual(c, 0, err)
            d = json.loads(out)["data"]
            self.assertFalse(d["finished"])
            self.assertEqual([s["id"] for s in d["steps"]],
                             ["mic", "models", "keys", "agents", "cua",
                              "notifications", "keybinding"])
            self.assertEqual(tree(env.home / ".local"), {})
            # the text table must not create config.toml either
            c, out, err = env.run(["onboard", "--status"])
            self.assertEqual(c, 0, err)
            c, out, err = env.run(["onboard"])
            self.assertEqual(c, 4)
            self.assertEqual(tree(env.home / ".config"), {})

    def test_bare_non_tty_keeps_the_legacy_checklist(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--json"])
            j = json.loads(out)["data"]
            self.assertFalse(j["ready"])
            self.assertTrue(all("try" in s and "ok" in s
                                for s in j["steps"]))
            self.assertEqual(c, 4)
            self.assertIn("E_NOT_READY", out)

    def test_step_mic_records_progress_when_it_passes(self):
        with CliEnv() as env:
            env.shim("pw-record")
            model = env.home / "src" / "whisper.cpp" / "models"
            model.mkdir(parents=True)
            (model / "ggml-small.en.bin").write_text("x")
            c, out, err = env.run(["onboard", "--step", "mic", "--json"])
            self.assertEqual(c, 0, err)
            d = json.loads(out)["data"]
            self.assertTrue(d["done"])
            f = env.home / ".local" / "share" / "wisp" / "onboard.json"
            self.assertIn("mic", json.loads(f.read_text())["done"])
            c, out, err = env.run(["onboard", "--undo", "mic", "--json"])
            self.assertEqual(c, 0, err)
            self.assertEqual(json.loads(f.read_text())["done"], {})

    def test_step_failing_exits_one_and_writes_nothing(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--step", "mic"])
            self.assertEqual(c, 4)
            self.assertIn("E_NOT_READY", err)
            self.assertEqual(tree(env.home / ".local"), {})

    def test_notifications_step_needs_yes(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--step", "notifications"])
            self.assertEqual(c, 4)
            self.assertIn("E_NOT_READY", err)
            self.assertEqual(tree(env.home / ".local"), {})

    def test_unknown_step_is_a_usage_error(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--step", "bogus"])
            self.assertEqual(c, 2)
            self.assertIn("E_USAGE", err)

    def test_finish_then_status_says_finished(self):
        with CliEnv() as env:
            c, _o, err = env.run(["onboard", "--finish"])
            self.assertEqual(c, 0, err)
            c, out, err = env.run(["onboard", "--status", "--json"])
            self.assertTrue(json.loads(out)["data"]["finished"])
            c, _o, err = env.run(["onboard", "--reset"])
            self.assertEqual(c, 0, err)
            c, out, err = env.run(["onboard", "--status", "--json"])
            self.assertFalse(json.loads(out)["data"]["finished"])

    def test_interactive_flow_over_stdin_skip_all_writes_nothing(self):
        with CliEnv() as env:
            c, out, err = env.run(["onboard", "--interactive"],
                                  stdin="s\ns\ns\ns\ns\ns\n")
            self.assertEqual(c, 0, err)
            self.assertEqual(tree(env.home / ".local"), {})
            self.assertEqual(tree(env.home / ".config"), {})


if __name__ == "__main__":
    unittest.main()
