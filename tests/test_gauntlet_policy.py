#!/usr/bin/env python3
"""Gauntlet-run policy (shell through rsh, live hit test, click confirm,
driver-error write). Every allowance is on the run's own config copy; the
owner's defaults are asserted unchanged. Offline: fakes only, no desktop,
no network, no model."""
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
import test_gauntlet_driver as tgd  # noqa: E402
import test_gauntlet_mode as tgm  # noqa: E402
from wisp import cua_safety, devrun, gauntlet, ipc, policy  # noqa: E402
from wisp.tools import system  # noqa: E402
from wisp import tools  # noqa: E402


class PolicyBase(tgm.GauntletBase):
    def setUp(self):
        super().setUp()
        t = shorttmp.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.sb = pathlib.Path(t.name) / "workspace"
        self.sb.mkdir()
        (self.sb / "a.txt").write_text("one\ntwo\n")
        self.log = pathlib.Path(t.name) / "rsh.log"
        self.g2 = dict(self.grant, sandbox_root=str(self.sb),
                       sandbox_log=str(self.log))
        self.scfg = devrun.run_config(self.cfg, "r1", grant=self.g2)


class TestShellThroughRsh(PolicyBase):
    def test_gauntlet_with_a_sandbox_root_allows_shell(self):
        self.assertNotIn("shell", self.scfg["dev"]["deny_tools"])
        self.assertEqual(self.scfg["agent"]["allow_shell"], "false")
        self.assertIsNone(policy.gate("shell", "ls", self.scfg, None))

    def test_shell_runs_through_rsh_in_the_sandbox_only(self):
        out = tools.run("shell", "cat a.txt", self.scfg)
        self.assertEqual(out, "SHELL rc=0 one\ntwo")
        self.assertIn("ok\tcat a.txt", self.log.read_text())
        out = tools.run("shell", "cat /etc/hostname", self.scfg)
        self.assertIn("outside the sandbox", out)
        out = tools.run("shell", "rm a.txt", self.scfg)
        self.assertIn("not allowed", out)
        self.assertTrue((self.sb / "a.txt").exists())
        out = tools.run("shell", "ls; id", self.scfg)
        self.assertIn("refused", out)

    def test_the_owners_shell_is_never_reached_in_a_gauntlet_run(self):
        with mock.patch.object(system, "shell") as sh:
            tools.run("shell", "ls", self.scfg)
        sh.assert_not_called()

    def test_denylist_still_applies(self):
        out = policy.gate("shell", "rm -rf /", self.scfg, None)
        self.assertEqual(out, "REFUSED (denylisted command)")

    def test_a_grant_without_a_sandbox_root_keeps_shell_denied(self):
        self.assertIn("shell", self.rcfg["dev"]["deny_tools"])
        self.assertIn("REFUSED", policy.gate("shell", "ls", self.rcfg, None))
        self.assertTrue(tools.run("shell", "ls", self.rcfg)
                        .startswith("REFUSED (gauntlet"))

    def test_owner_defaults_are_unchanged(self):
        owner = {"agent": {"allow_shell": "false"}}
        self.assertEqual(policy.gate("shell", "ls", owner, None),
                         "SKIPPED (shell disabled — set allow_shell=true)")
        plain = devrun.run_config(self.cfg, "r1")
        self.assertIn("shell", plain["dev"]["deny_tools"])
        self.assertEqual(plain["dev"].get("sandbox_root"), None)
        self.assertFalse(gauntlet.shell_sandboxed("shell", owner))
        # a non-gauntlet cfg that merely names a root is not a grant
        fake = {"dev": {"sandbox_root": str(self.sb)},
                "agent": {"allow_shell": "false"}}
        self.assertFalse(gauntlet.shell_sandboxed("shell", fake))
        self.assertTrue(gauntlet.rsh_run("ls", fake).startswith("REFUSED"))

    def test_a_profile_cannot_set_the_sandbox_root(self):
        prof = {"dev": {"sandbox_root": "/"}}
        c = devrun.run_config(self.cfg, "r1", profile=prof, grant=self.grant)
        self.assertEqual(c["dev"]["sandbox_root"], "")
        for k in ("dev.sandbox_root", "dev.sandbox_log"):
            self.assertTrue(ipc.is_safety_config_key(k), k)


class TestHitTest(PolicyBase):
    def click(self, cfg):
        mons = [{"x": 0, "y": 0, "width": 1920, "height": 1080}]
        tgt = mock.Mock(x=100, y=200, element_backed=False)
        with mock.patch.object(system, "_resolve_target", return_value=tgt), \
                mock.patch("wisp.points.monitors", return_value=mons), \
                mock.patch("wisp.points.on_screen", return_value=True), \
                mock.patch.object(system, "_human_coordinates",
                                  return_value=False), \
                mock.patch("wisp.delivery.resolve_backend",
                           return_value="cua"), \
                mock.patch("wisp.grounding.target_at_point",
                           return_value=None) as hit, \
                mock.patch("wisp.pointer.Registry") as reg:
            reg.return_value.click.return_value = mock.Mock(
                ok=True, delivery="", backend="cua")
            out = system.click("100,200", cfg)
        return out, hit

    def test_gauntlet_live_run_skips_the_hit_test(self):
        cfg = dict(self.rcfg, pointer={"mode": "drive"})
        out, hit = self.click(cfg)
        self.assertEqual(out, "CLICKED(100,200)")
        hit.assert_not_called()

    def test_owner_use_keeps_the_hit_test(self):
        out, hit = self.click({"pointer": {"mode": "drive"}})
        self.assertTrue(out.startswith("REFUSED (no element at model"), out)
        hit.assert_called_once()


class TestClickConfirm(PolicyBase):
    def test_click_in_a_sandbox_window_needs_no_confirmation(self):
        with mock.patch.object(cua_safety, "sensitive_surface",
                               lambda *a, **k: "unknown"):
            self.assertIsNone(policy.gate("click", "50,60", self.rcfg, None))

    def test_a_non_sandbox_window_still_asks(self):
        self.focused = tgm.OTHER
        with mock.patch.object(cua_safety, "sensitive_surface",
                               lambda *a, **k: "unknown"):
            out = policy.gate("click", "50,60", self.rcfg, None)
        self.assertEqual(out, "SKIPPED (click needs user confirmation)")

    def test_a_sensitive_surface_still_asks(self):
        with mock.patch.object(cua_safety, "sensitive_surface",
                               lambda *a, **k: "stripe"):
            out = policy.gate("click", "50,60", self.rcfg, None)
        self.assertEqual(out, "SKIPPED (click needs user confirmation)")

    def test_owner_defaults_are_unchanged(self):
        self.assertFalse(gauntlet.pre_approved("click", "1,1", {}, None))
        self.assertFalse(gauntlet.pre_approved(
            "click", "1,1", devrun.run_config(self.cfg, "r1"), None))
        self.assertFalse(gauntlet.pre_approved("shell", "ls", {}, None))


class TestDriver(tgd.Base):
    def test_the_driver_registers_the_sandbox_workspace_and_log(self):
        g, code, deps = self.run_g([tgd.case("c1", also=["terminal"])],
                                   profiles=("openrouter",))
        run = next(c for c in deps.cmds if c["cmd"] == "dev_run")
        self.assertEqual(run["sandbox_root"],
                         str(self.gdir / "sandbox" / "workspace"))
        self.assertEqual(run["sandbox_log"],
                         str(self.gdir / "sandbox" / "rsh.log"))

    def test_driver_error_is_written_even_when_the_rundir_is_missing(self):
        def boom(self_):
            raise RuntimeError("early")
        with mock.patch.object(tgd.G.Gauntlet, "_prepare_dirs", boom):
            g, code, _ = self.run_g([tgd.case("c1")])
        self.assertEqual(code, 1)
        self.assertIn("early", (g.rundir / "driver-error.txt").read_text())

    def test_an_unwritable_driver_error_file_does_not_mask_the_exit(self):
        real = pathlib.Path.write_text

        def picky(p, *a, **k):
            if p.name == "driver-error.txt":
                raise OSError("disk full")
            return real(p, *a, **k)
        deps = self.deps()
        deps.crash_on_run, deps.crash_on_exc = 0, RuntimeError("boom")
        with mock.patch.object(pathlib.Path, "write_text", picky):
            g, code, _ = self.run_g([tgd.case("c1")], deps)
        self.assertEqual(code, 1)
        self.assertIn("boom", g.stopped)
        self.assertFalse((g.rundir / "driver-error.txt").exists())
        self.assertEqual(self.sc.state("wispd"), "active")


if __name__ == "__main__":
    unittest.main()
