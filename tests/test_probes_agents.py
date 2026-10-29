"""U2: AgentsProbe states over a fake runtime tree; no real ori runs."""
import pathlib
import stat
import tempfile
import unittest

from wisp import agent_pins, probes_agents


def put(root, tool, version, out):
    d = root / tool / version
    d.mkdir(parents=True)
    f = d / tool
    f.write_text(f"#!/bin/sh\necho {out}\n")
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    (root / tool / "current").symlink_to(version)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.root = pathlib.Path(td.name)
        self.auth = (0, {"source": "keyring"})

    def probe(self):
        return probes_agents.AgentsProbe(
            root=self.root, auth_fn=lambda ori: self.auth)

    def both(self, oc="2.2.0"):
        put(self.root, "ori", agent_pins.ORI_VERSION,
            f"ori {agent_pins.ORI_VERSION}")
        put(self.root, "opencode", oc, oc)

    def test_absent(self):
        r = self.probe().check()
        self.assertEqual((r["state"], r["ok"]), ("absent", False))
        self.assertIn("install --agents", r["fix"])

    def test_opencode_v1_names_the_fix(self):
        self.both("1.19.5")
        r = self.probe().check()
        self.assertEqual(r["state"], "opencode_v1")
        self.assertIn("agents", r["fix"])
        self.assertFalse(r["ok"])

    def test_wrong_version(self):
        self.both("2.1.0")
        self.assertEqual(self.probe().check()["state"], "wrong_version")

    def test_ready_with_key_source(self):
        self.both()
        r = self.probe().check()
        self.assertEqual((r["state"], r["ok"]), ("ready", True))

    def test_nonzero_auth_is_not_signed_in(self):
        self.both()
        self.auth = (1, None)
        self.assertEqual(self.probe().check()["state"], "not_signed_in")

    def test_exit_zero_without_source_is_not_signed_in(self):
        self.both()
        self.auth = (0, {})
        self.assertEqual(self.probe().check()["state"], "not_signed_in")

    def test_auth_skipped_reports_installed(self):
        self.both()
        self.auth = (1, None)
        self.assertEqual(self.probe().check(auth=False)["state"],
                         "installed")


if __name__ == "__main__":
    unittest.main()
