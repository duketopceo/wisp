#!/usr/bin/env python3
"""Gauntlet --repeats: per-case pass rate and spread, the report table,
and scripts/gauntlet/remote.sh's argument and secret handling. Offline:
remote.sh runs against a fake `ssh` that records argv and stdin."""
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

_spec = importlib.util.spec_from_file_location(
    "gauntlet_script_rep", ROOT / "scripts" / "gauntlet.py")
G = importlib.util.module_from_spec(_spec)
sys.modules["gauntlet_script_rep"] = G
_spec.loader.exec_module(G)

REMOTE = ROOT / "scripts" / "gauntlet" / "remote.sh"
SECRET = "sk-or-TESTSECRET-0123456789"


def att(case, arm, ok, steps=3, n=1, **kw):
    return dict({"case": case, "arm": arm, "n": n, "success": ok,
                 "steps": steps, "usd": 0.01}, **kw)


CASES = [{"id": "a", "held_out": False}, {"id": "b", "held_out": True}]


class Aggregate(unittest.TestCase):
    def test_pass_rate_and_spread_per_case_and_arm(self):
        xs = [att("a", "x", True, 2), att("a", "x", False, 4),
              att("a", "x", True, 3), att("b", "x", False),
              att("b", "x", False), att("b", "x", False)]
        rows = {(r["case"], r["arm"]): r for r in
                G.aggregate_repeats(xs, CASES)}
        a = rows[("a", "x")]
        self.assertEqual((a["runs"], a["passed"]), (3, 2))
        self.assertAlmostEqual(a["rate"], 2 / 3)
        self.assertAlmostEqual(a["spread"], (2 / 9) ** 0.5)
        self.assertAlmostEqual(a["steps_mean"], 3.0)
        b = rows[("b", "x")]
        self.assertEqual((b["passed"], b["rate"], b["spread"]), (0, 0, 0))
        self.assertTrue(b["held_out"])

    def test_single_run_has_no_spread(self):
        r, = G.aggregate_repeats([att("a", "x", True)], CASES)
        self.assertEqual((r["runs"], r["rate"], r["spread"]), (1, 1.0, 0.0))

    def test_ignores_learn_and_second_runs_and_capped_attempts(self):
        xs = [att("a", "x", True), att("a", "x", False, n=2),
              att("a", "x", False, n="learn"),
              att("a", "x", False, capped=True)]
        r, = G.aggregate_repeats(xs, CASES)
        self.assertEqual((r["runs"], r["passed"]), (1, 1))

    def test_arms_are_kept_apart(self):
        xs = [att("a", "x", True), att("a", "y", False)]
        rows = G.aggregate_repeats(xs, CASES)
        self.assertEqual({(r["arm"], r["passed"]) for r in rows},
                         {("x", 1), ("y", 0)})


class Report(unittest.TestCase):
    def make(self, repeats):
        g = G.Gauntlet(CASES, [("x", "x", {})], tempfile.mkdtemp(), 5.0,
                       deps=None, out=lambda *_: None, repeats=repeats)
        g.attempts = [att("a", "x", True, row=None),
                      att("a", "x", False, row=None),
                      att("b", "x", True, row=None),
                      att("b", "x", True, row=None)]
        return g

    def test_report_shows_per_case_table_with_repeats(self):
        text = self.make(2).render()
        self.assertIn("## Per-case pass rate (2 repeats)", text)
        self.assertIn("| a | x | 1/2 | 50% | 0.50 |", text)
        self.assertIn("flaky (mixed outcomes): a [x]", text)

    def test_single_repeat_report_has_no_table(self):
        self.assertNotIn("Per-case pass rate", self.make(1).render())

    def test_report_writes_stats_rows(self):
        g = self.make(2)
        g.rundir = pathlib.Path(tempfile.mkdtemp())
        g._report()
        rows = [json.loads(x) for x in
                (g.rundir / "stats.jsonl").read_text().splitlines()]
        self.assertEqual({r["case"] for r in rows}, {"a", "b"})

    def test_repeats_clamped_to_one(self):
        self.assertEqual(self.make(0).repeats, 1)

    def test_parser_default_and_bad_value(self):
        self.assertEqual(G.build_parser().parse_args([]).repeats, 1)
        self.assertEqual(
            G.build_parser().parse_args(["--repeats", "3"]).repeats, 3)
        out = []
        rc = G.main(["--repeats", "0", "--dry-run"], out=out.append)
        self.assertEqual(rc, G.EXIT_USAGE)


class RemoteScript(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "log"
        self.log.mkdir()
        # a fake ssh: record argv and stdin of every call
        self.write("ssh", f"""#!/bin/bash
n=$(ls {self.log} | wc -l)
printf '%s\\n' "$@" > {self.log}/$n.argv
cat > {self.log}/$n.stdin
case "$*" in *'ls -1t'*) echo gauntlet-20260101-000000;; esac
exit 0
""")
        self.write("omaseal", f"#!/bin/bash\necho {SECRET}\n")
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        WISP_GAUNTLET_HOST="testhost",
                        WISP_GAUNTLET_LOCAL_RUNS=str(self.tmp / "runs"),
                        HOME=str(self.tmp))

    def write(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    def run_remote(self, *args, env=None):
        return subprocess.run(["bash", str(REMOTE), *args],
                              env=env or self.env, capture_output=True,
                              text=True, timeout=60)

    def calls(self):
        out = []
        for p in sorted(self.log.glob("*.argv"),
                        key=lambda p: int(p.stem)):
            out.append((p.read_text(),
                        p.with_suffix(".stdin").read_text()))
        return out

    def test_key_only_on_stdin_never_argv(self):
        r = self.run_remote("--ref", "feat/x", "--", "--repeats", "3",
                            "--cap", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertTrue(calls)
        for argv, _ in calls:
            self.assertNotIn(SECRET, argv)
        self.assertNotIn(SECRET, r.stdout + r.stderr)
        with_key = [s for _, s in calls if SECRET in s]
        self.assertEqual(len(with_key), 1)
        self.assertEqual(with_key[0], SECRET + "\n")

    def test_secret_never_written_to_a_file(self):
        self.run_remote("--", "--repeats", "2")
        for p in self.tmp.rglob("*"):
            if p.is_file() and p.suffix != ".stdin" and p.parent != self.bin:
                self.assertNotIn(SECRET, p.read_text(errors="ignore"),
                                 str(p))

    def test_gauntlet_args_and_ref_reach_the_host(self):
        import base64
        import re
        self.run_remote("--ref", "feat/x", "--", "--repeats", "3",
                        "--cap", "7", "--profiles", "openrouter")
        scripts = []
        for argv, _ in self.calls():
            for m in re.finditer(r"printf %s (\S+) \| base64", argv):
                scripts.append(base64.b64decode(m.group(1)).decode())
        text = "\n".join(scripts)
        self.assertIn("r='feat/x'", text)
        self.assertIn("--session isolated --repeats 3 --cap 7 "
                      "--profiles openrouter", text)
        self.assertIn("IFS= read -r k", text)
        self.assertNotIn(SECRET, text)

    def test_refuses_without_a_key(self):
        self.write("omaseal", "#!/bin/bash\nexit 1\n")
        r = self.run_remote("--", "--repeats", "1")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])        # nothing reached the host

    def test_refuses_empty_key(self):
        self.write("omaseal", "#!/bin/bash\necho\n")
        self.assertEqual(self.run_remote().returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_refuses_without_a_host(self):
        env = {k: v for k, v in self.env.items()
               if k != "WISP_GAUNTLET_HOST"}
        self.assertEqual(self.run_remote(env=env).returncode, 2)

    def test_rejects_hostile_host_and_ref(self):
        self.assertEqual(self.run_remote("--host", "-oProxyCommand=x")
                         .returncode, 2)
        self.assertEqual(self.run_remote("--ref", "a;b").returncode, 2)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
