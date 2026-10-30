"""`wispd install --ref` and the deploy record (hosted-install U3).

Every run is a subprocess in the hermetic temp HOME from cli_env.py, with
PATH cut to shims plus a real `git`; the source repos are throwaway repos
in a second temp dir. Nothing touches the real home or ~/.local/opt/wisp.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cli_env  # noqa: E402
import shorttmp  # noqa: E402

from wisp import agent_install, agent_pins, cli  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True, text=True,
                       env={**os.environ, **GIT_ENV})
    return r.stdout.strip()


def make_repo(root: pathlib.Path) -> pathlib.Path:
    """A minimal source tree: launcher, a one-file package, desktop template."""
    repo = root / "src"
    (repo / "wisp").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "wispd").write_text("#!/bin/sh\n# v1\n")
    (repo / "wisp" / "marker.py").write_text("VERSION = 'v1'\n")
    (repo / "assets" / "desktop").mkdir(parents=True)
    shutil.copy2(cli_env.ROOT / "assets" / "desktop" / "wisp.desktop",
                 repo / "assets" / "desktop" / "wisp.desktop")
    # the unit template differs from this checkout's, so a test can tell
    # which tree the installed unit came from
    (repo / "scripts" / "units").mkdir(parents=True)
    (repo / "scripts" / "units" / "wispd.service").write_text(
        (cli_env.ROOT / "scripts" / "units" / "wispd.service").read_text()
        + "# from-ref-v1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v1")
    git(repo, "tag", "v1")
    return repo


class InstallRefTest(unittest.TestCase):
    def setUp(self):
        self.src_td = shorttmp.TemporaryDirectory()
        self.addCleanup(self.src_td.cleanup)
        self.repo = make_repo(pathlib.Path(self.src_td.name))
        self.v1 = git(self.repo, "rev-parse", "v1")

    def env(self, daemon=False):
        e = cli_env.CliEnv(daemon=daemon)
        e.__enter__()
        self.addCleanup(e.__exit__, None, None, None)
        for name in ("systemctl", "hyprctl"):
            e.shim(name)
        os.symlink(shutil.which("git"), e.home / "bin" / "git")
        e.env.update(GIT_ENV)
        # install_bind appends to an existing hypr dir (it does not make it)
        (e.home / ".config" / "hypr").mkdir(parents=True)
        return e

    def opt(self, e):
        return e.home / ".local" / "opt" / "wisp"

    def test_ref_installs_that_ref_and_records_commit(self):
        e = self.env()
        code, out, err = e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo)])
        self.assertEqual(code, 0, err)
        self.assertEqual(
            (self.opt(e) / "wisp" / "marker.py").read_text(),
            "VERSION = 'v1'\n")
        rec = json.loads((self.opt(e) / "deploy.json").read_text())
        self.assertEqual(rec["commit"], self.v1)
        self.assertEqual(rec["ref"], "v1")
        self.assertEqual(rec["repo"], str(self.repo))
        self.assertTrue(rec["time"])

    def test_ref_installs_its_own_unit_templates(self):
        e = self.env()
        code, out, err = e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo)])
        self.assertEqual(code, 0, err)
        unit = e.home / ".config" / "systemd" / "user" / "wispd.service"
        self.assertIn("# from-ref-v1", unit.read_text())

    def test_relative_repo_is_recorded_absolute(self):
        e = self.env()
        rel = os.path.relpath(self.repo, e.home)
        p = subprocess.run([sys.executable, str(cli_env.ROOT / "wispd"),
                            "install", "--ref", "v1", "--repo", rel],
                           env=e.env, cwd=e.home, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        rec = json.loads((self.opt(e) / "deploy.json").read_text())
        self.assertEqual(rec["repo"], str(self.repo.resolve()))

    def test_failed_unit_install_does_not_record_the_deploy(self):
        git(self.repo, "rm", "-q", "scripts/units/wispd.service")
        git(self.repo, "commit", "-q", "-m", "no units")
        git(self.repo, "tag", "nounits")
        e = self.env()
        code, out, err = e.run(["install", "--ref", "nounits", "--repo",
                                str(self.repo)])
        self.assertNotEqual(code, 0)
        self.assertFalse((self.opt(e) / "deploy.json").exists())

    def test_uncommitted_and_later_changes_are_not_installed(self):
        (self.repo / "wisp" / "marker.py").write_text("VERSION = 'dirty'\n")
        (self.repo / "wisp" / "extra.py").write_text("x = 1\n")
        e = self.env()
        code, out, err = e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo)])
        self.assertEqual(code, 0, err)
        self.assertEqual(
            (self.opt(e) / "wisp" / "marker.py").read_text(),
            "VERSION = 'v1'\n")
        self.assertFalse((self.opt(e) / "wisp" / "extra.py").exists())

    def test_unknown_ref_errors_and_writes_nothing(self):
        e = self.env()
        code, out, err = e.run(["install", "--ref", "no-such-ref",
                                "--repo", str(self.repo)])
        self.assertEqual(code, 1, err)
        self.assertIn("no-such-ref", err)
        self.assertFalse(self.opt(e).exists())
        self.assertFalse((e.home / ".local" / "bin").exists())

    def test_ref_without_record_or_repo_names_repo_flag(self):
        e = self.env()
        code, out, err = e.run(["install", "--ref", "v1"])
        self.assertEqual(code, 2, err)
        self.assertIn("--repo", err)
        self.assertFalse(self.opt(e).exists())

    def test_repo_comes_from_the_record_on_the_next_ref_install(self):
        e = self.env()
        self.assertEqual(e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo)])[0], 0)
        (self.repo / "wisp" / "marker.py").write_text("VERSION = 'v2'\n")
        git(self.repo, "commit", "-q", "-am", "v2")
        v2 = git(self.repo, "rev-parse", "HEAD")
        code, out, err = e.run(["install", "--ref", "HEAD"])
        self.assertEqual(code, 0, err)
        rec = json.loads((self.opt(e) / "deploy.json").read_text())
        self.assertEqual(rec["commit"], v2)
        self.assertEqual(
            (self.opt(e) / "wisp" / "marker.py").read_text(),
            "VERSION = 'v2'\n")

    def test_dry_run_prints_plan_and_writes_nothing(self):
        e = self.env()
        code, out, err = e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo), "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("dry run: nothing written", out)
        self.assertFalse(self.opt(e).exists())

    def test_plain_install_records_the_checkout_commit(self):
        e = self.env()
        code, out, err = e.run(["install"])
        self.assertEqual(code, 0, err)
        rec = json.loads((self.opt(e) / "deploy.json").read_text())
        head = git(cli_env.ROOT, "rev-parse", "HEAD")
        self.assertEqual(rec["commit"], head)
        self.assertEqual(rec["repo"], str(cli_env.ROOT))

    def test_status_shows_recorded_commit_or_unknown(self):
        e = self.env(daemon=True)
        code, out, err = e.run(["status", "--json"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["data"]["deploy"]["commit"],
                         "unknown")
        self.assertEqual(e.run(["install", "--ref", "v1", "--repo",
                                str(self.repo)])[0], 0)
        code, out, err = e.run(["status", "--json"])
        self.assertEqual(json.loads(out)["data"]["deploy"]["commit"],
                         self.v1)
        code, out, err = e.run(["status"])
        self.assertIn(self.v1[:12], out)


class InstallAgentsTest(unittest.TestCase):
    """`wispd install --agents`: the pinned ori and OpenCode, no network."""

    def run_agents(self, *extra, results=None):
        import contextlib
        import io
        calls = []

        def fake_install(tool, *a, **kw):
            calls.append(tool)
            return (results or {}).get(tool, agent_install.Result("installed"))

        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(agent_install, "install", fake_install), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = cli.main(["install", "--agents", *extra], host=None)
        return code, out.getvalue(), err.getvalue(), calls

    def test_installs_both_tools(self):
        code, out, err, calls = self.run_agents("--json")
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, ["ori", "opencode"])
        data = json.loads(out)["data"]
        self.assertTrue(data["installed"])
        self.assertEqual(data["agents"]["ori"]["status"], "installed")
        self.assertEqual(data["agents"]["opencode"]["status"], "installed")

    def test_dry_run_names_the_pins_and_installs_nothing(self):
        code, out, err, calls = self.run_agents("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, [])
        self.assertIn(agent_pins.ORI_VERSION, out)
        self.assertIn(agent_pins.OPENCODE_VERSION, out)

    def test_a_failed_download_exits_nonzero_with_the_reason(self):
        code, out, err, calls = self.run_agents(
            results={"ori": agent_install.Result("failed", "no network")})
        self.assertNotEqual(code, 0)
        self.assertIn("no network", err)
        self.assertEqual(calls, ["ori"])   # stops at the first failure


if __name__ == "__main__":
    unittest.main()
