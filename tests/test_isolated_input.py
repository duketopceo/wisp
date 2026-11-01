"""`[dev] isolated_session`: every input path is instance-scoped or
refused (KTD6, R5). Offline: a fake Wayland socket for the virtual
pointer and a recorder in place of every spawned tool."""
import os
import pathlib
import subprocess
import unittest
from unittest import mock

import shorttmp  # tests/ is on sys.path (unittest discover -s tests)

from fakes.wayland import FakeWayland
from wisp import devrun, ipc, pointer, platform, realinput, vpointer
from wisp.tools import system

ISO = {"dev": {"isolated_session": "true"},
       "pointer": {"mode": "drive", "backend": "auto"},
       "cua": {"delivery": "background"}}
MON = [{"x": 0, "y": 0, "width": 3456, "height": 2160, "scale": 2},
       {"x": 1728, "y": 0, "width": 3440, "height": 1440, "scale": 1}]


class Recorder:
    """Stands in for `_cancel.run`: records argv + env, never spawns."""

    def __init__(self, rc=0):
        self.calls, self.rc = [], rc

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw.get("env"), kw.get("input")))
        return subprocess.CompletedProcess(argv, self.rc, b"", b"")

    def bins(self):
        return [c[0][0] for c in self.calls]


class Base(unittest.TestCase):
    def setUp(self):
        realinput._stop_for_test()
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        self.sock = self.dir / "wayland-iso"
        self.wl = FakeWayland(self.sock).start()
        self.addCleanup(self.wl.stop)
        env = {"WISP_ISOLATED_SESSION": "1",
               "WAYLAND_DISPLAY": "wayland-iso",
               "XDG_RUNTIME_DIR": str(self.dir),
               "HYPRLAND_INSTANCE_SIGNATURE": "ISO"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("DISPLAY", None)
        self.rec = Recorder()
        for target in ("wisp.tools.system._cancel.run",
                       "wisp.pointer._cancel.run"):
            p = mock.patch(target, self.rec)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("wisp.points.monitors", return_value=MON)
        p.start()
        self.addCleanup(p.stop)


class Backend(Base):
    def test_auto_picks_vpointer_even_with_every_uinput_tool_present(self):
        with mock.patch("wisp.platform._which", return_value=True), \
             mock.patch("wisp.platform._cua_live", return_value="/live/cua"):
            reg = pointer.Registry(ISO)
            self.assertEqual(reg.names(), ["vpointer", "guide"])
            self.assertEqual(reg.select().name, "vpointer")
            self.assertEqual(platform.pointer_backend(ISO), "vpointer")

    def test_a_pin_on_a_refused_injector_never_falls_through(self):
        for pin in ("ydotool", "cua", "hyprcursor", "wlrctl"):
            cfg = {**ISO, "pointer": {"mode": "drive", "backend": pin}}
            with mock.patch("wisp.platform._which", return_value=True):
                self.assertIsNone(pointer.Registry(cfg).select(), pin)

    def test_normal_mode_is_unchanged(self):
        cfg = {"pointer": {"mode": "drive", "backend": "auto"}}
        reg = pointer.Registry(cfg)
        self.assertEqual(reg.names(),
                         ["cua", "hyprcursor", "ydotool", "wlrctl",
                          "guide"])
        with mock.patch("wisp.platform._which", return_value=True), \
             mock.patch("wisp.platform._cua_live", return_value="/s"):
            self.assertEqual(reg.select().name, "cua")
        with mock.patch("wisp.platform._which",
                        side_effect=lambda b: b in ("hyprctl", "ydotool")), \
             mock.patch("wisp.platform._cua_live", return_value=None):
            self.assertEqual(reg.select().name, "hyprcursor")
        with mock.patch("wisp.platform._which",
                        side_effect=lambda b: b == "ydotool"), \
             mock.patch("wisp.platform._cua_live", return_value=None):
            self.assertEqual(reg.select().name, "ydotool")

    def test_unavailable_without_the_instance_socket(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "gone"}):
            self.assertIsNone(pointer.Registry(ISO).select())

    def test_click_goes_through_the_virtual_pointer_only(self):
        with mock.patch("wisp.grounding.target_at_point",
                        return_value={"title": "x"}):
            out = system.click("100,200@logical", ISO)
        self.assertEqual(out, "CLICKED(100,200)")
        ma = [a for o, r, a in self.wl.requests if r == "motion_absolute"]
        # extent = bounding box of the two logical outputs
        self.assertEqual(ma[0][1:3], (100, 200))
        self.assertEqual(self.rec.calls, [])      # nothing spawned at all
        buttons = [a for o, r, a in self.wl.requests if r == "button"]
        self.assertEqual([b[2] for b in buttons], [1, 0])

    def test_click_does_not_arm_the_real_input_watch(self):
        with mock.patch("wisp.grounding.target_at_point",
                        return_value={"title": "x"}), \
             mock.patch("wisp.realinput.arm") as arm:
            system.click("10,10@logical", ISO)
            system.move("10,10@logical", ISO)
        arm.assert_not_called()

    def test_no_socket_refuses_instead_of_guiding(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "gone"}):
            out = system.click("10,10@logical", ISO)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertEqual(self.rec.calls, [])


class KeysAndText(Base):
    def test_key_chord_uses_wtype_with_the_instance_env(self):
        with mock.patch("wisp.platform._which", return_value=True):
            out = system.key("ctrl+s", ISO)
        self.assertEqual(out, "KEY")
        argv, env, _ = self.rec.calls[0]
        self.assertEqual(argv, ["wtype", "-M", "ctrl", "-k", "s",
                                "-m", "ctrl"])
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-iso")
        self.assertNotIn("DISPLAY", env)
        self.assertNotIn("ydotool", self.rec.bins())

    def test_multi_modifier_chords_and_the_unknown_key_path(self):
        with mock.patch("wisp.platform._which", return_value=True):
            system.key("ctrl+shift+v", ISO)
            system.key("super+1", ISO)
            out = system.key("hyper+x", ISO)
        self.assertEqual(self.rec.calls[0][0],
                         ["wtype", "-M", "ctrl", "-M", "shift", "-k", "v",
                          "-m", "shift", "-m", "ctrl"])
        self.assertEqual(self.rec.calls[1][0],
                         ["wtype", "-M", "logo", "-k", "1", "-m", "logo"])
        self.assertTrue(out.startswith("SKIP"), out)
        self.assertEqual(len(self.rec.calls), 2)

    def test_bare_key_uses_wtype(self):
        with mock.patch("wisp.platform._which", return_value=True):
            system.key("enter", ISO)
            system.key("pagedown", ISO)
        self.assertEqual([c[0] for c in self.rec.calls],
                         [["wtype", "-k", "Return"],
                          ["wtype", "-k", "Next"]])

    def test_key_without_wtype_is_refused_not_ydotool(self):
        with mock.patch("wisp.platform._which",
                        side_effect=lambda b: b == "ydotool"):
            for k in ("ctrl+s", "enter"):
                out = system.key(k, ISO)
                self.assertTrue(out.startswith("REFUSED"), out)
        self.assertEqual(self.rec.calls, [])

    def test_type_text_without_wtype_raises_the_refusal(self):
        with mock.patch("wisp.platform._which",
                        side_effect=lambda b: b == "ydotool"):
            with self.assertRaises(vpointer.UinputRefused):
                platform.type_text_cmd(isolated=True)
            out = system.type_text("hello", ISO)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertEqual(self.rec.calls, [])

    def test_type_text_uses_wtype_on_stdin(self):
        with mock.patch("wisp.platform._which", return_value=True), \
             mock.patch("wisp.gauntlet.keystroke_guard",
                        return_value=None):
            out = system.type_text("hello", ISO)
        self.assertEqual(out, "TYPED")
        argv, env, stdin = self.rec.calls[0]
        self.assertEqual(argv, ["wtype", "-"])
        self.assertEqual(stdin, b"hello")
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-iso")

    def test_scroll_emits_axis_events_and_no_ydotool(self):
        out = system.scroll("down 120", ISO)
        self.assertEqual(out, "SCROLLED")
        axes = [a for o, r, a in self.wl.requests if r == "axis_discrete"]
        self.assertTrue(axes)
        self.assertTrue(all(a[2] > 0 for a in axes))
        self.assertEqual(self.rec.calls, [])

    def test_scroll_up_is_negative(self):
        system.scroll("up 60", ISO)
        axes = [a for o, r, a in self.wl.requests if r == "axis_discrete"]
        self.assertTrue(all(a[2] < 0 for a in axes))

    def test_normal_mode_key_and_scroll_still_use_ydotool(self):
        cfg = {"pointer": {"mode": "drive"}}
        with mock.patch("wisp.platform._which", return_value=True):
            system.key("ctrl+s", cfg)
            system.key("enter", cfg)
            system.scroll("down", cfg)
        self.assertEqual(self.rec.bins(), ["ydotool"] * 3)
        self.assertEqual(self.wl.requests, [])

    def test_missing_instance_env_is_a_refusal(self):
        env = {k: v for k, v in os.environ.items()
               if k != "WAYLAND_DISPLAY"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("wisp.platform._which", return_value=True):
            out = system.key("enter", ISO)
        self.assertTrue(out.startswith("REFUSED"), out)
        self.assertEqual(self.rec.calls, [])


class RunConfig(unittest.TestCase):
    def test_peer_cannot_set_isolated_session(self):
        self.assertTrue(ipc.is_safety_config_key("dev.isolated_session"))
        cmd = {"cmd": "config", "set": {"dev.isolated_session": "false"}}
        peer = {"pid": 1, "uid": 1000}
        with mock.patch("wisp.agents.classify_peer",
                        return_value={"marked": True, "task_id": "t1"}), \
             mock.patch("wisp.agents.record_refusal"):
            out = ipc.check_peer_authz(cmd, peer)
        self.assertEqual(out["reason"], "safety_key")

    def test_vs_cannot_set_it(self):
        with self.assertRaises(ValueError):
            devrun.parse_vs("dev.isolated_session=true")

    def test_run_config_forces_it_on_with_background_delivery(self):
        owner = {"cua": {"delivery": "pointer"}}
        c = devrun.run_config(owner, "r1", isolated=True)
        self.assertEqual(c["dev"]["isolated_session"], "true")
        self.assertEqual(c["cua"]["delivery"], "background")
        self.assertEqual(owner, {"cua": {"delivery": "pointer"}})
        g = devrun.run_config(owner, "r3", profile={}, grant={
            "windows": [], "spend_file": "", "cap_usd": 1,
            "isolated": True})
        self.assertEqual(g["dev"]["isolated_session"], "true")
        self.assertEqual(g["cua"]["delivery"], "background")
        plain_g = devrun.run_config(owner, "r4", grant={
            "windows": [], "spend_file": "", "cap_usd": 1})
        self.assertNotIn("isolated_session", plain_g["dev"])
        plain = devrun.run_config(owner, "r2")
        self.assertNotIn("isolated_session", plain["dev"])
        self.assertEqual(plain["cua"]["delivery"], "pointer")


if __name__ == "__main__":
    unittest.main()
