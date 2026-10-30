"""B31: offline scoreboard, GET-only acquisition and secret-free output."""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "growth_snapshot.py"
FIXTURE = ROOT / "tests" / "fixtures" / "growth" / "github_public.json"


def load_script():
    spec = importlib.util.spec_from_file_location("growth_snapshot", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GrowthSnapshotTest(unittest.TestCase):
    def test_offline_fixture_writes_deterministic_dated_json(self):
        self.assertTrue(SCRIPT.exists(), "offline growth snapshot is missing")
        module = load_script()
        with tempfile.TemporaryDirectory() as d:
            out, err = io.StringIO(), io.StringIO()
            args = ["--fixture", str(FIXTURE), "--output-dir", d]
            with patch("subprocess.run", side_effect=AssertionError("no process")), \
                 patch("socket.socket", side_effect=AssertionError("no network")), \
                 patch.dict(os.environ, {"GH_TOKEN": "env-secret-never-emit"}), \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.assertEqual(module.main(args), 0)
                target = Path(d) / "growth-2026-10-30.json"
                first = target.read_bytes()
                self.assertEqual(module.main(args), 0)
                self.assertEqual(target.read_bytes(), first)
            data = json.loads(first)
            self.assertEqual(data["date"], "2026-10-30")
            self.assertEqual(data["repository"], "duketopceo/wisp")
            self.assertEqual(data["stars"]["value"], 17)
            self.assertEqual(data["forks"]["value"], 4)
            self.assertEqual(data["release_downloads"]["value"], 25)
            self.assertEqual(data["issues"]["value"], 12)
            self.assertEqual(data["discussions"]["value"], 3)
            self.assertEqual(data["traffic"]["clones"]["status"], "unavailable")
            self.assertIsNone(data["traffic"]["clones"]["count"])
            self.assertEqual(data["traffic"]["views"]["count"], 0)
            self.assertEqual(data["traffic"]["views"]["status"], "available")
            all_output = first.decode() + out.getvalue() + err.getvalue()
            self.assertNotIn("secret-never-emit", all_output)

    def test_live_collection_only_reads_github(self):
        module = load_script()
        raw = json.loads(FIXTURE.read_text())
        calls = []

        def gh(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[:2], ["gh", "api"])
            self.assertTrue(kwargs["capture_output"])
            self.assertNotIn("env-secret", " ".join(argv))
            if argv[2] == "graphql":
                query = next(a for a in argv if a.startswith("query="))
                self.assertIn("query(", query)
                self.assertNotIn("mutation", query)
                value = {"data": {"repository": raw["counts"]}}
            else:
                self.assertEqual(argv[2:4], ["--method", "GET"])
                path = argv[4]
                if path.endswith("/traffic/clones"):
                    raise subprocess.TimeoutExpired(argv, 90, stderr="env-secret")
                if path.endswith("/traffic/views"):
                    return SimpleNamespace(returncode=1, stdout="",
                                           stderr="403 env-secret")
                if "/releases/" in path:
                    release_id = path.split("/")[-2]
                    value = [raw["assets"][release_id]]
                elif "/releases?" in path:
                    value = [[raw["releases"][0]], [raw["releases"][1]]]
                else:
                    value = raw["repository"]
            return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")

        with tempfile.TemporaryDirectory() as d, \
             patch("subprocess.run", side_effect=gh), \
             patch("socket.socket", side_effect=AssertionError("no direct network")):
            with contextlib.redirect_stdout(io.StringIO()) as out, \
                 contextlib.redirect_stderr(io.StringIO()) as err:
                code = module.main(["--repo", "duketopceo/wisp", "--date",
                                    "2026-10-30", "--output-dir", d])
            self.assertEqual(code, 0)
            data = json.loads((Path(d) / "growth-2026-10-30.json").read_text())
            self.assertEqual(data["release_downloads"]["value"], 25)
            self.assertIsNone(data["traffic"]["views"]["count"])
            self.assertEqual(data["issues"]["value"], 12)
            self.assertNotIn("env-secret", out.getvalue() + err.getvalue())
            self.assertEqual(len(calls), 7)
