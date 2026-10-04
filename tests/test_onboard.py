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

from wisp import config, onboard  # noqa: E402

LADDER_URLS = {u for _n, u in onboard.LADDER}


class Fakes:
    """Injected probes that record every call."""

    def __init__(self, up=None, cua="running", notify="sent", submap=False,
                 recorder=True, model=True, notifier=True):
        self.up = set(LADDER_URLS if up is None else up)
        self.fetched = []
        self.sent = 0
        self.cua_state = cua
        self.notify_result = notify
        self.submap_present = submap
        self.recorder = recorder
        self.model = model
        self.notifier = notifier

    def probes(self):
        def fetch(url):
            self.fetched.append(url)
            return url in self.up

        def cua(cfg):
            ok = self.cua_state in ("running", "dry_run")
            return {"state": self.cua_state, "ok": ok, "fix": "wispd cua status"}

        def send(cfg):
            self.sent += 1
            return self.notify_result

        return onboard.Probes(
            which=lambda n: "/usr/bin/" + n if self.recorder else None,
            whisper_ok=lambda cfg: self.model,
            fetch=fetch, cua=cua,
            notify_ready=lambda: self.notifier, notify_send=send,
            submap=lambda: self.submap_present)


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
        self.cfg = {}
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
                         ["mic", "models", "cua", "notifications",
                          "keybinding"])
        self.assertEqual([s.id for s in onboard.STEPS if s.optional],
                         ["cua", "keybinding"])

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


class TestFlow(OnboardCase):
    def test_fresh_home_full_flow_records_every_available_step(self):
        before = tree(self.home)
        self.assertEqual(before, {})
        f = Fakes()
        res, ask = self.walk(f, "y", "y", "y", "y")
        done = json.loads(self.progress.path.read_text())["done"]
        self.assertEqual(sorted(done),
                         ["cua", "mic", "models", "notifications"])
        self.assertEqual(f.sent, 1)
        self.assertEqual(res["done"], ["mic", "models", "cua",
                                       "notifications"])
        self.assertEqual(res["na"], ["keybinding"])
        self.assertEqual(len(ask.prompts), 4)  # no prompt for the na step
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
        res, ask = self.walk(f2, "y", "y", "y")
        self.assertEqual(res["resumed"], ["mic"])
        self.assertEqual(res["done"], ["mic", "models", "cua",
                                       "notifications"])
        self.assertEqual(len(ask.prompts), 3)
        self.assertFalse(any("mic" in p.lower() for p in ask.prompts))
        self.assertEqual(f2.sent, 1)

    def test_skip_writes_nothing_at_all(self):
        f = Fakes()
        res, ask = self.walk(f, "s", "s", "s", "s")
        self.assertEqual(tree(self.home), {})
        self.assertEqual(sorted(res["skipped"]),
                         ["cua", "mic", "models", "notifications"])
        self.assertEqual(res["done"], [])
        self.assertEqual(f.sent, 0)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.cfgdir.exists())

    def test_skip_one_then_finish_the_rest(self):
        res, _ = self.walk(Fakes(), "s", "y", "s", "n")
        self.assertEqual(res["done"], ["models"])
        self.assertEqual(sorted(res["skipped"]),
                         ["cua", "mic", "notifications"])
        # skipped steps are asked again next time
        self.progress = onboard.Progress()
        res, ask = self.walk(Fakes(), "q")
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("microphone", ask.prompts[0].lower())

    def test_a_failing_step_is_not_recorded_and_flow_continues(self):
        f = Fakes(up=set())
        res, _ = self.walk(f, "y", "y", "y", "y")
        self.assertNotIn("models", res["done"])
        self.assertIn("models", res["failed"])
        self.assertIn("mic", res["done"])

    def test_eof_on_a_closed_stdin_stops_cleanly(self):
        res, _ = self.walk(Fakes())
        self.assertTrue(res["quit"])
        self.assertEqual(tree(self.home), {})

    def test_every_step_is_reversible(self):
        self.walk(Fakes(), "y", "y", "y", "y")
        for sid in ("mic", "models", "cua", "notifications"):
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
        self.walk(Fakes(), "y", "y", "n", "y")
        st = onboard.status(self.cfg, Fakes().probes(),
                            onboard.Progress())
        self.assertTrue(st["finished"])  # cua and keybinding are optional

    def test_single_steps_finish_setup_once_the_required_ones_pass(self):
        f = Fakes()
        for sid in ("mic", "models"):
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
                         ["mic", "models", "cua", "notifications",
                          "keybinding"])
        mic = st["steps"][0]
        self.assertEqual(mic["state"], "done")
        self.assertTrue(mic["done"] and mic["ok"])
        self.assertEqual(st["steps"][1]["state"], "todo")
        self.assertEqual(st["steps"][4]["state"], "na")
        for s in st["steps"]:
            for k in ("id", "name", "optional", "state", "ok", "done",
                      "detail", "try"):
                self.assertIn(k, s)
        self.assertEqual(st["done_count"], 1)
        self.assertEqual(st["total"], 4)  # na steps do not count

    def test_status_writes_nothing(self):
        onboard.status(self.cfg, Fakes().probes(), self.progress)
        self.assertEqual(tree(self.home), {})


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
                             ["mic", "models", "cua", "notifications",
                              "keybinding"])
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
                                  stdin="s\ns\ns\ns\ns\n")
            self.assertEqual(c, 0, err)
            self.assertEqual(tree(env.home / ".local"), {})
            self.assertEqual(tree(env.home / ".config"), {})


if __name__ == "__main__":
    unittest.main()
