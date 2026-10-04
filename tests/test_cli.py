#!/usr/bin/env python3
"""W19: the wispd command registry, help, JSON, exit codes, aliases."""
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import cli_env  # noqa: E402
from cli_env import CliEnv, SCENARIOS  # noqa: E402

from wisp import cli  # noqa: E402
from wisp.cli import registry, output, strings  # noqa: E402

GOLDEN = json.loads((HERE / "golden" / "cli_transcripts.json").read_text())
HELP_DIR = HERE / "golden" / "cli_help"
ERR_RE = re.compile(r"\AE_[A-Z_]+: .+\nTry: .+\n\Z")


def run_inproc(argv, **patches):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv), host=None)
    return code, out.getvalue(), err.getvalue()


class TestAliasParity(unittest.TestCase):
    """Old argv and the new canonical argv reproduce the transcripts
    recorded from the pre-W19 sys.argv wispd (stdout, exit, IPC)."""

    def _check(self, name, argv, daemon, seed):
        want = GOLDEN[name]
        with CliEnv(daemon=daemon) as env:
            if seed:
                env.seed_tasks()
            code, out, err = env.run(argv)
            self.assertEqual(out, want["stdout"], f"{name} {argv}: {err}")
            self.assertEqual(code, want["code"], f"{name} {argv}: {err}")
            self.assertEqual(env.ipc, want["ipc"], f"{name} {argv}")

    def test_legacy_syntax_matches_golden(self):
        for name, legacy, _c, daemon, seed in SCENARIOS:
            with self.subTest(name):
                self._check(name, legacy, daemon, seed)

    def test_canonical_syntax_matches_golden(self):
        for name, legacy, canon, daemon, seed in SCENARIOS:
            if canon == "skip":
                continue
            with self.subTest(name):
                self._check(name, canon or legacy, daemon, seed)

    def test_every_alias_resolves_to_a_registered_command(self):
        cmds = registry.commands()
        for legacy, fn in cli.ALIASES.items():
            with self.subTest(legacy):
                tokens = fn([])
                path = " ".join(tokens[:2]) if " ".join(tokens[:2]) in cmds \
                    else tokens[0]
                self.assertIn(path, cmds)

    def test_alias_table_covers_old_command_names(self):
        old = {"daemon", "install", "trigger", "status", "interrupt",
               "watch", "subscribe", "stop", "choice", "label", "tasks",
               "train", "review", "learn", "config", "harness",
               "inventory", "connect", "context", "task_status",
               "task_cancel", "memory-write", "agent", "memory", "trace",
               "doctor", "models", "tui", "skills", "suggestions",
               "theme", "fails", "tele", "eval", "sync", "recipes"}
        known = set(cli.ALIASES) | {c.split()[0] for c in
                                    registry.commands()}
        self.assertEqual(old - known, set())


_METAVAR_OPT = re.compile(r"^( +)(-\w), (--[\w-]+) ([A-Z][A-Z_]*)", re.M)


def _norm_help(text: str) -> str:
    """argparse 3.13 prints `-n, --lines N` where 3.11/3.12 print
    `-n N, --lines N`, and the column alignment shifts with it. Compare
    the two spellings as equal: rewrite to the long form, then collapse
    runs of spaces so the shifted alignment doesn't matter."""
    text = _METAVAR_OPT.sub(r"\1\2 \4, \3 \4", text)
    return re.sub(r" {2,}", " ", text)


class TestHelp(unittest.TestCase):
    def test_every_command_has_summary_and_examples(self):
        for path, c in registry.commands().items():
            with self.subTest(path):
                self.assertTrue(c.summary and "\n" not in c.summary)
                self.assertTrue(c.examples, path)
                self.assertNotIn("—", c.summary)

    def test_help_exits_zero_and_matches_golden(self):
        update = os.environ.get("WISP_UPDATE_GOLDEN")
        paths = [""] + list(registry.commands())
        for path in paths:
            with self.subTest(path or "wispd"):
                argv = path.split() + ["--help"]
                os.environ["COLUMNS"] = "80"
                code, out, err = run_inproc(argv)
                self.assertEqual(code, 0, err)
                self.assertIn("usage:", out)
                if path:
                    self.assertIn("Examples:", out)
                    self.assertIn(registry.commands()[path].summary, out)
                f = HELP_DIR / ((path or "wispd").replace(" ", "_")
                                + ".txt")
                if update:
                    HELP_DIR.mkdir(parents=True, exist_ok=True)
                    f.write_text(out)
                self.assertEqual(_norm_help(out), _norm_help(f.read_text()),
                                 f.name)

    def test_group_help_exists_for_every_group(self):
        groups = {p.split()[0] for p in registry.commands() if " " in p}
        for g in groups:
            with self.subTest(g):
                code, out, _ = run_inproc([g, "--help"])
                self.assertEqual(code, 0)

    def test_top_level_help_is_short(self):
        p = subprocess.run([sys.executable, str(ROOT / "wispd"), "--help"],
                           capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, COLUMNS="80"))
        self.assertEqual(p.returncode, 0)
        self.assertLess(len(p.stdout.splitlines()), 60)
        for word in ("--json", "--quiet", "--no-color", "doctor",
                     "completion"):
            self.assertIn(word, p.stdout)

    def test_no_emoji_or_em_dash_in_cli_strings(self):
        for v in vars(strings).values():
            if isinstance(v, str):
                self.assertNotIn("—", v)
        for code, (msg, hint) in strings.ERRORS.items():
            self.assertNotIn("—", msg + hint)
            self.assertTrue(msg[0].isupper() and msg.endswith("."), code)


class TestExitCodes(unittest.TestCase):
    def assertErr(self, err, code):
        self.assertRegex(err, ERR_RE)
        self.assertTrue(err.startswith(code + ":"), err)

    def test_usage_errors_exit_2(self):
        with CliEnv() as env:
            for argv in (["bogus"], ["choice", "--index", "x"],
                         ["config", "set", "nokey", "1"],
                         ["task"], ["completion", "tcsh"],
                         ["latency", "--nope"]):
                with self.subTest(argv):
                    code, out, err = env.run(argv)
                    self.assertEqual(code, 2, err)
                    self.assertErr(err, "E_USAGE")

    def test_daemon_down_exits_3(self):
        with CliEnv() as env:
            for argv in (["status"], ["stop"], ["interrupt"], ["context"],
                         ["choice", "x"], ["task", "status", "a"],
                         ["task", "cancel", "a"], ["task", "run", "x"],
                         ["suggest", "list"], ["memory", "edit", "a|b|c|d"],
                         ["status", "--json"]):
                with self.subTest(argv):
                    code, out, err = env.run(argv)
                    self.assertEqual(code, 3, err)
                    if "--json" in argv:
                        j = json.loads(out)
                        self.assertFalse(j["ok"])
                        self.assertEqual(j["error"]["code"],
                                         "E_DAEMON_DOWN")
                        self.assertTrue(j["error"]["try"])
                    else:
                        self.assertErr(err, "E_DAEMON_DOWN")

    def test_failure_exits_1_with_code(self):
        with CliEnv(daemon=True) as env:
            code, out, err = env.run(["choice", "stale"])
            self.assertEqual(code, 1)
            self.assertErr(err, "E_STALE_PROMPT")

    def test_unhealthy_dependency_exits_4(self):
        with CliEnv() as env:  # Jev endpoint points at a closed port
            code, out, err = env.run(["health"])
            self.assertEqual(code, 4, err)
            self.assertIn("jev", out)
            self.assertErr(err, "E_UNHEALTHY")

    def test_error_codes_map_to_exit_codes(self):
        self.assertEqual(registry.EXIT_OK, 0)
        self.assertEqual(registry.EXIT_FAIL, 1)
        self.assertEqual(registry.EXIT_USAGE, 2)
        self.assertEqual(registry.EXIT_DOWN, 3)
        self.assertEqual(registry.EXIT_UNHEALTHY, 4)
        for wisp_code in ("jev_down", "brain_down", "stt_down",
                          "ground_down"):
            self.assertEqual(registry.from_wisp_code(wisp_code).exit, 4)
        self.assertEqual(registry.from_wisp_code("busy").exit, 1)
        for code in strings.ERRORS:
            self.assertTrue(code.startswith("E_"))


class TestJson(unittest.TestCase):
    MATRIX = [
        (["status"], True), (["stop"], True), (["interrupt"], True),
        (["choice", "a"], True), (["context"], True),
        (["label", "set", "correct"], True), (["label", "report"], False),
        (["task", "list"], False), (["task", "status", "a"], True),
        (["task", "cancel", "a"], True), (["task", "run", "x"], True),
        (["memory", "edit", "a|b|c|d"], True),
        (["memory", "write", "user", cli_env.B64], True),
        (["suggest", "list"], True), (["config", "show"], True),
        (["config", "set", "audio.seconds", "30"], True),
        (["train", "stats"], False), (["review", "list"], False),
        (["learn", "weekly"], False), (["learn", "fails"], False),
        (["skills", "list"], False), (["recipes", "draft"], False),
        (["trace", "digest"], False), (["trace", "show"], False),
        (["theme", "show"], False), (["theme", "set", "light"], False),
        (["health"], False), (["latency"], False), (["spend"], False),
        (["binds"], False), (["onboard"], False), (["doctor"], False),
        (["cua", "status"], False), (["cua", "test"], False),
        (["cua", "log"], False), (["cua", "enable"], False),
        (["cua", "disable"], False), (["notify", "test"], False),
        (["cua", "kill"], False), (["cua", "resume"], False),
        (["completion", "bash"], False),
    ]
    TYPES = {"str": str, "int": int, "float": (int, float), "bool": bool,
             "list": list, "dict": dict, "any": object,
             "str|null": (str, type(None)),
             "float|null": (int, float, type(None))}

    def test_envelope_and_schema_for_every_command(self):
        cmds = registry.commands()
        for argv, daemon in self.MATRIX:
            with self.subTest(argv):
                with CliEnv(daemon=daemon) as env:
                    env.shim("notify-send")
                    code, out, err = env.run(argv + ["--json"])
                    j = json.loads(out)
                    self.assertLessEqual(set(j), {"ok", "command", "data",
                                                  "error"}, out)
                    self.assertIn(j["command"], cmds)
                    self.assertIsInstance(j["ok"], bool)
                    if j["ok"]:
                        self.assertEqual(code, 0, (out, err))
                    else:  # dependency checks may fail in the sandbox
                        self.assertEqual(code, 4, (out, err))
                        self.assertEqual(set(j["error"]),
                                         {"code", "message", "try"})
                    schema = cmds[j["command"]].schema
                    self.assertEqual(set(j.get("data", schema)),
                                     set(schema), out)
                    for key, typ in schema.items():
                        if key in j.get("data", {}):
                            self.assertIsInstance(j["data"][key],
                                                  self.TYPES[typ], key)

    def test_quiet_and_json_flags_work_after_the_verb_too(self):
        with CliEnv(daemon=True) as env:
            a = env.run(["--json", "status"])
            b = env.run(["status", "--json"])
            self.assertEqual(a[1], b[1])
            self.assertEqual(env.run(["context", "--quiet"])[1], "")


class TestGlobalFlags(unittest.TestCase):
    def test_no_color_and_plain_when_not_a_tty(self):
        with CliEnv() as env:
            env.env.pop("NO_COLOR")
            code, out, err = env.run(["health"])
            self.assertNotIn("\x1b[", out)
            code, out, err = env.run(["health", "--no-color"])
            self.assertNotIn("\x1b[", out)

    def test_quiet_silences_stdout_but_not_errors(self):
        with CliEnv() as env:
            code, out, err = env.run(["health", "--quiet"])
            self.assertEqual(out, "")
            self.assertEqual(code, 4)
            self.assertIn("E_UNHEALTHY", err)


class TestTable(unittest.TestCase):
    def test_plain_alignment_and_no_escapes(self):
        t = output.table(["name", "status"],
                         [["jev", "ok"], ["brain-long", "DOWN"]],
                         color=False)
        lines = t.splitlines()
        self.assertEqual(lines[0].split(), ["name", "status"])
        self.assertEqual(len({l.index(l.split()[1]) for l in lines}), 1)
        self.assertNotIn("\x1b", t)

    def test_color_uses_theme_tokens(self):
        from wisp import theme
        t = output.table(["name", "status"], [["jev", "ok"]],
                         tones=[[None, "ok"]], color=True, cfg={})
        self.assertIn("\x1b[38;2;", t)
        r, g, b = output.hex_rgb(theme.load(None, {})["tokens"]["ok"])
        self.assertIn(f"\x1b[38;2;{r};{g};{b}m", t)

    def test_color_decision(self):
        self.assertFalse(output.use_color(False, tty=True,
                                          env={"NO_COLOR": "1"}))
        self.assertFalse(output.use_color(False, tty=False, env={}))
        self.assertFalse(output.use_color(True, tty=True, env={}))
        self.assertTrue(output.use_color(False, tty=True, env={}))


class TestNewCommands(unittest.TestCase):
    def test_doctor_json_sections(self):
        with CliEnv() as env:
            code, out, err = env.run(["doctor", "--json"])
            j = json.loads(out)
            self.assertIn(code, (0, 4))
            names = {s["name"] for s in j["data"]["sections"]}
            self.assertTrue({"stt / audio", "pointer",
                             "health"} <= names, names)

    def test_latency_reads_spans(self):
        import datetime as dt
        with CliEnv() as env:
            env.data.mkdir(parents=True)
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            rows = [{"ts": now, "turn": "t1", "step": "stt",
                     "kind": "span", "ms": 400, "data": {}},
                    {"ts": now, "turn": "t1", "step": "route",
                     "kind": "span", "ms": 100, "data": {}},
                    {"ts": now, "turn": "t1", "step": "first_token",
                     "kind": "span", "ms": 300, "data": {}}]
            (env.data / "trace.jsonl").write_text(
                "".join(json.dumps(r) + "\n" for r in rows))
            code, out, err = env.run(["latency", "--json"])
            j = json.loads(out)["data"]
            self.assertEqual(j["turns"], 1)
            e2e = [r for r in j["rows"] if r["id"] == "E2E"][0]
            self.assertEqual(e2e["p50"], 800)
            code, out, err = env.run(["latency"])
            self.assertIn("E2E", out)

    def test_spend_reads_ledger_when_present(self):
        with CliEnv() as env:
            env.data.mkdir(parents=True)
            import datetime as dt
            today = dt.date.today().isoformat()
            (env.data / "usage.jsonl").write_text(
                json.dumps({"ts": today + "T10:00:00", "usd": 0.25,
                            "model": "m", "paid": True}) + "\n"
                + json.dumps({"ts": "2001-01-01T00:00:00", "usd": 9,
                              "model": "m", "paid": True}) + "\n")
            code, out, err = env.run(["spend", "--json"])
            j = json.loads(out)["data"]
            self.assertEqual(j["calls_today"], 1)
            self.assertAlmostEqual(j["today_usd"], 0.25)
            self.assertEqual(j["source"], "usage.jsonl")

    def test_spend_without_ledger_is_zero(self):
        with CliEnv() as env:
            j = json.loads(env.run(["spend", "--json"])[1])["data"]
            self.assertEqual(j["today_usd"], 0)
            self.assertEqual(j["source"], "none")

    def test_binds_reports_configured_chord(self):
        with CliEnv() as env:
            j = json.loads(env.run(["binds", "--json"])[1])["data"]
            self.assertEqual(j["hotkey"]["chord"], "SUPER+D")
            self.assertFalse(j["hyprland"])

    def test_onboard_lists_steps_with_try_lines(self):
        with CliEnv() as env:
            code, out, err = env.run(["onboard", "--json"])
            j = json.loads(out)["data"]
            self.assertFalse(j["ready"])
            self.assertTrue(all("try" in s and "ok" in s
                                for s in j["steps"]))

    def test_cua_status_with_fake_driver_and_socket(self):
        with CliEnv() as env:
            env.shim("cua-driver")
            sock = env.home / ".cache" / "cua-driver" / "cua-driver.sock"
            sock.parent.mkdir(parents=True)
            import socket
            s = socket.socket(socket.AF_UNIX)
            s.bind(str(sock))
            # nobody accepts, and two probes connect (status, test): a
            # backlog of 1 admits only one pending connection on macOS
            s.listen(8)
            try:
                j = json.loads(env.run(["cua", "status", "--json"])[1])
                self.assertTrue(j["data"]["live"])
                self.assertTrue(j["data"]["binary"])
                j = json.loads(env.run(["cua", "test", "--json"])[1])
                self.assertTrue(j["data"]["ok"])
            finally:
                s.close()
            # driver never invoked by status/test: only a socket connect
            self.assertEqual(env.shim_calls(), [])

    def test_cua_not_installed_exits_4_on_test(self):
        with CliEnv() as env:
            code, out, err = env.run(["cua", "test"])
            self.assertEqual(code, 4)
            self.assertRegex(err, ERR_RE)
            self.assertIn("E_CUA_DOWN", err)

    def test_cua_enable_disable_only_edit_config(self):
        with CliEnv() as env:
            env.shim("systemctl")
            env.shim("journalctl")
            env.shim("cua-driver")
            self.assertEqual(env.run(["cua", "enable"])[0], 0)
            cfg = (env.home / ".config" / "wisp" / "config.toml")
            self.assertIn('backend = "cua"', cfg.read_text())
            self.assertEqual(env.run(["cua", "disable"])[0], 0)
            self.assertNotIn('backend = "cua"', cfg.read_text())
            self.assertEqual(env.shim_calls(), [])  # no systemctl, nothing

    def test_cua_log_reads_journal_only(self):
        with CliEnv() as env:
            env.shim("journalctl", "echo line-a; echo line-b")
            code, out, err = env.run(["cua", "log", "-n", "5"])
            self.assertEqual(code, 0, err)
            self.assertIn("line-b", out)
            calls = env.shim_calls()
            self.assertEqual(len(calls), 1)
            self.assertIn("-u cua-driver", calls[0])
            self.assertNotIn("start", calls[0])
            self.assertNotIn("restart", calls[0])

    def test_notify_test_uses_fake_notify_send_only(self):
        with CliEnv() as env:
            env.shim("notify-send")
            code, out, err = env.run(["notify", "test"])
            self.assertEqual(code, 0, err)
            calls = env.shim_calls()
            self.assertEqual(len(calls), 1)
            self.assertIn("Wisp", calls[0])

    def test_notify_test_prefers_wisp_notify_send_when_present(self):
        import types
        fake = types.ModuleType("wisp.notify")
        fake.send = mock.Mock(return_value=True)
        with mock.patch.dict(sys.modules, {"wisp.notify": fake}):
            code, out, err = run_inproc(["notify", "test", "--json"])
        self.assertEqual(code, 0, err)
        fake.send.assert_called_once()
        self.assertEqual(json.loads(out)["data"]["via"], "wisp.notify")

    def test_completion_scripts(self):
        for shell in ("bash", "zsh", "fish"):
            script = cli.completion.generate(shell)
            for word in ("daemon", "doctor", "cua", "completion",
                         "json"):
                self.assertIn(word, script, shell)
        bash = cli.completion.generate("bash")
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d) / "c.bash"
            f.write_text(bash)
            r = subprocess.run(["bash", "-n", str(f)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            # loads and completes
            r = subprocess.run(
                ["bash", "-c",
                 f"source {f}; COMP_WORDS=(wispd cu); COMP_CWORD=1; "
                 "_wispd; echo ${COMPREPLY[@]}"],
                capture_output=True, text=True)
            self.assertIn("cua", r.stdout)
        for sh, flag in (("zsh", "-n"), ("fish", "--no-execute")):
            exe = shutil.which(sh)
            if exe:
                f = pathlib.Path(tempfile.mkdtemp()) / "c"
                f.write_text(cli.completion.generate(sh))
                r = subprocess.run([exe, flag, str(f)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_watch_reuses_ipc_watch_and_alias_subscribe(self):
        evs = [{"event": "hello"}, {"event": "snapshot"}]
        with mock.patch("wisp.ipc.watch", return_value=iter(evs)) as w:
            code, out, err = run_inproc(["watch", "state", "tasks"])
            w.assert_called_once_with(["state", "tasks"])
            code2, out2, _ = run_inproc(["subscribe"])
        self.assertEqual(code, 0)
        self.assertEqual([json.loads(l) for l in out.splitlines()], evs)

    def test_choice_and_interrupt_wire_messages(self):
        with CliEnv(daemon=True) as env:
            env.run(["choice", "--prompt-id", "p9", "--index", "3", "yes"])
            env.run(["interrupt"])
            self.assertEqual(env.ipc[0], {"cmd": "choice", "pick": "yes",
                                          "prompt_id": "p9", "index": 3})
            self.assertEqual(env.ipc[1], {"cmd": "interrupt"})

    def test_health_start_prints_and_never_runs(self):
        with CliEnv(extra_env={"WISP_JEV_ENDPOINT":
                               "http://127.0.0.1:9/x"}) as env:
            env.shim("systemctl")
            cfgdir = env.home / ".config" / "wisp"
            cfgdir.mkdir(parents=True)
            (cfgdir / "config.toml").write_text(
                '[brain]\nrouter = "jev"\ndefault = "openrouter:x"\n'
                '[health.units]\njev = "llama-jev,jev-shim"\n')
            code, out, err = env.run(["health", "start"])
            self.assertEqual(code, 0, err)
            self.assertIn("systemctl --user start llama-jev.service", out)
            self.assertIn("--run", out)
            self.assertEqual(env.shim_calls(), [])


class TestRegistryUnits(unittest.TestCase):
    def test_register_requires_summary_and_examples(self):
        with self.assertRaises(ValueError):
            registry.Command(path="x y", summary="", examples=["a"],
                             handler=lambda ctx, a: 0, schema={})

    def test_flags_extracted_anywhere(self):
        argv, flags = registry.extract_globals(
            ["--json", "status", "--quiet", "--no-color"])
        self.assertEqual(argv, ["status"])
        self.assertTrue(flags.json and flags.quiet and flags.no_color)

    def test_double_dash_stops_flag_extraction(self):
        argv, flags = registry.extract_globals(["agent", "--", "--json"])
        self.assertEqual(argv, ["agent", "--", "--json"])
        self.assertFalse(flags.json)


if __name__ == "__main__":
    unittest.main()
