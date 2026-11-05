"""`wispd install --ref` hands the install to the exported tree's own
installer, so a running installed copy never imports half-old, half-new
modules (2026-11-03 `refuse_links` ImportError)."""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shorttmp  # noqa: E402
import test_install  # noqa: E402
from test_install import git  # noqa: E402

from wisp.cli import core  # noqa: E402

PROBE = """#!/usr/bin/env python3
import json, os, pathlib, sys
pathlib.Path(os.environ["HANDOFF_OUT"]).write_text(json.dumps(
    {"argv": sys.argv[1:], "deploy": os.environ.get("%s")}))
sys.exit(7)
""" % core.HANDOFF_ENV


class HandoffTest(unittest.TestCase):
    # borrow the fixture, not the base class's tests
    _base = test_install.InstallRefTest
    setUp, env, opt = _base.setUp, _base.env, _base.opt

    def add_handoff_ref(self):
        (self.repo / "wispd").write_text(PROBE)
        (self.repo / "wisp" / "cli").mkdir()
        (self.repo / "wisp" / "cli" / "core.py").write_text(
            f"HANDOFF_ENV = {core.HANDOFF_ENV!r}\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "v2")
        git(self.repo, "tag", "v2")
        return git(self.repo, "rev-parse", "v2")

    def test_new_ref_installs_through_its_own_installer(self):
        v2 = self.add_handoff_ref()
        e = self.env()
        out_file = e.home / "handoff.json"
        e.env["HANDOFF_OUT"] = str(out_file)
        code, out, err = e.run(["install", "--ref", "v2", "--repo",
                                str(self.repo), "--dry-run"])
        self.assertEqual(code, 7, err)  # the child's exit code comes back
        got = json.loads(out_file.read_text())
        self.assertEqual(got["argv"], ["install", "--dry-run"])
        self.assertEqual(json.loads(got["deploy"]),
                         {"repo": str(self.repo), "ref": "v2", "commit": v2})
        self.assertFalse(self.opt(e).exists(), "the parent wrote nothing")

    def test_old_ref_without_handoff_installs_in_process(self):
        self.assertFalse(core._can_hand_off(self.repo))


class HandedDeployTest(unittest.TestCase):
    def deploy(self, raw):
        with mock.patch.dict(os.environ, {core.HANDOFF_ENV: raw}):
            return core._handed_deploy()

    def test_reads_the_record(self):
        rec = {"repo": "/r", "ref": "origin/master", "commit": "abc"}
        self.assertEqual(self.deploy(json.dumps(rec)), rec)

    def test_ignores_junk(self):
        for raw in ("", "not json", "[1]", '{"ref": "x"}'):
            self.assertIsNone(self.deploy(raw), raw)

    def test_unset_is_none(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(core.HANDOFF_ENV, None)
            self.assertIsNone(core._handed_deploy())


if __name__ == "__main__":
    unittest.main()
