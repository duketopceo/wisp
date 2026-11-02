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
        inside = mock.patch.object(gauntlet, "click_refusal",
                                   return_value=None)
        inside.start()
        self.addCleanup(inside.stop)
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


def _client(addr, at, size, ws=91, **kw):
    return dict({"address": addr, "at": list(at), "size": list(size),
                 "mapped": True, "hidden": False,
                 "workspace": {"id": ws}}, **kw)


MONS = [{"x": 0, "y": 0, "width": 3456, "height": 2160, "scale": 2,
         "activeWorkspace": {"id": 91}, "specialWorkspace": {"id": 0}}]
LAYERS = {"eDP-1": {"levels": {
    "0": [{"namespace": "omarchy-background", "x": 0, "y": 0,
           "w": 1728, "h": 1080}],
    "2": [{"namespace": "omarchy-bar", "x": 0, "y": 1054,
           "w": 1728, "h": 26}],
    "3": [{"namespace": "omarchy-notifications", "x": 0, "y": 0,
           "w": 1728, "h": 1080}]}}}


class TestClickGuard(PolicyBase):
    """A gauntlet click runs only on a registered sandbox window."""

    def compositor(self, clients=None, layers=None, mons=None):
        data = {"clients": [_client(tgm.WIN, (100, 100), (400, 300))]
                if clients is None else clients,
                "monitors": MONS if mons is None else mons,
                "layers": LAYERS if layers is None else layers}
        p = mock.patch("wisp.hypr.query", side_effect=lambda n, *a: data[n])
        p.start()
        self.addCleanup(p.stop)

    def click(self, cfg, x=150, y=150):
        tgt = mock.Mock(x=x, y=y, element_backed=False)
        cfg = dict(cfg, pointer={"mode": "drive"})
        with mock.patch.object(system, "_resolve_target", return_value=tgt), \
                mock.patch("wisp.points.monitors", return_value=MONS), \
                mock.patch("wisp.points.on_screen", return_value=True), \
                mock.patch.object(system, "_human_coordinates",
                                  return_value=False), \
                mock.patch("wisp.delivery.resolve_backend",
                           return_value="cua"), \
                mock.patch("wisp.pointer.Registry") as reg:
            reg.return_value.click.return_value = mock.Mock(
                ok=True, delivery="", backend="cua")
            out = system.click(f"{x},{y}", cfg)
        return out, reg.return_value.click

    def test_click_inside_a_sandbox_window_runs(self):
        self.compositor()
        out, clk = self.click(self.rcfg)
        self.assertEqual(out, "CLICKED(150,150)")
        clk.assert_called_once()

    def test_click_outside_every_sandbox_window_is_refused(self):
        self.compositor()
        out, clk = self.click(self.rcfg, 1049, 992)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_click_on_another_window_is_refused(self):
        self.compositor([_client(tgm.OTHER, (100, 100), (400, 300))])
        out, clk = self.click(self.rcfg)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_a_non_sandbox_window_over_the_sandbox_is_refused(self):
        self.compositor([_client(tgm.WIN, (100, 100), (400, 300)),
                         _client(tgm.OTHER, (120, 120), (50, 50))])
        out, clk = self.click(self.rcfg)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_a_window_on_a_hidden_workspace_does_not_count(self):
        self.compositor([_client(tgm.WIN, (100, 100), (400, 300), ws=92)])
        out, clk = self.click(self.rcfg)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_a_layer_surface_over_the_point_refuses(self):
        layers = {"eDP-1": {"levels": {"3": [
            {"namespace": "omarchy-menu", "x": 0, "y": 0,
             "w": 1728, "h": 1080}]}}}
        self.compositor(layers=layers)
        out, clk = self.click(self.rcfg)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_no_registered_windows_refuses(self):
        self.compositor()
        cfg = devrun.run_config(self.cfg, "r1", grant=grant_none(self.dir))
        out, clk = self.click(cfg)
        self.assertEqual(
            out, "REFUSED (gauntlet: no sandbox window is registered)")
        clk.assert_not_called()

    def test_an_unreadable_compositor_refuses(self):
        with mock.patch("wisp.hypr.query", side_effect=OSError("down")):
            out, clk = self.click(self.rcfg)
        self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
        clk.assert_not_called()

    def test_a_refusal_is_traced_as_a_gate_stop(self):
        self.compositor()
        with mock.patch("wisp.trace.emit") as emit:
            self.click(self.rcfg, 1049, 992)
        self.assertEqual(emit.call_args.args[1], "gate_stop")
        self.assertEqual(emit.call_args.args[3]["tool"], "click")

    def test_the_menu_case_gets_no_allowance(self):
        # menu cases register no sandbox window: refused, never executed
        self.compositor()
        cfg = devrun.run_config(self.cfg, "r1", grant=grant_none(self.dir))
        for x, y in ((1049, 992), (920, 500)):
            out, clk = self.click(cfg, x, y)
            self.assertTrue(out.startswith("REFUSED (gauntlet:"), out)
            clk.assert_not_called()

    def test_owner_clicks_are_unaffected(self):
        with mock.patch("wisp.hypr.query",
                        side_effect=AssertionError("queried")), \
                mock.patch("wisp.grounding.target_at_point",
                           return_value=object()):
            out, clk = self.click({}, 5, 5)
        self.assertEqual(out, "CLICKED(5,5)")
        clk.assert_called_once()
        self.assertIsNone(gauntlet.click_guard({}, 5, 5))
        self.assertIsNone(gauntlet.click_guard(
            devrun.run_config(self.cfg, "r1"), 5, 5))


def grant_none(td_dir):
    return tgm.grant(td_dir, windows=())


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
