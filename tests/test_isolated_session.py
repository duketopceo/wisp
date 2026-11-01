#!/usr/bin/env python3
"""scripts/isolated_session.py, offline: fake hyprctl/systemctl/process
control and a fake Wayland socket for the virtual pointer. Nothing here
starts a compositor."""
import importlib.util
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import shorttmp  # noqa: E402
from fakes.wayland import FakeWayland  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "isolated_session_script", ROOT / "scripts" / "isolated_session.py")
IS = importlib.util.module_from_spec(_spec)
sys.modules["isolated_session_script"] = IS
_spec.loader.exec_module(IS)

LIVE_SIG = "LIVESIG_1"
INST_SIG = "INSTSIG_9"


class FakeProc:
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.waited = True
        return 0


class FakeSystem(IS.Deps):
    """The whole machine: a live session, an instance, systemctl."""

    def __init__(self, live_rt, **kw):
        env = {"WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": live_rt,
               "HYPRLAND_INSTANCE_SIGNATURE": LIVE_SIG, "DISPLAY": ":0",
               "PATH": "/usr/bin", "HOME": "/home/x"}
        super().__init__(env)
        self.t = 0.0
        self.clock = lambda: self.t
        self.sleep = self._sleep
        self.spawned, self.runs = [], []
        self.alive = {}
        self.sig = kw.get("sig", INST_SIG)
        self.live_cursor = (500, 400)
        self.live_clients_ = [{"address": "0xlive1", "title": "owner"}]
        self.sysenv = b"A=1\nB=2\n"
        self.wispd = b"ActiveState=active\nMainPID=42\n"
        self.monitors_, self.marker = [], None
        self.marker_base = 0
        self.wl = None
        self.move_live_cursor_on_click = False
        self.leak_new_client = False
        self.fail_output_create = False
        self.stale_pid = False
        self.evals, self.exit_dispatched = [], False
        self.aq_backends = False        # this aquamarine has no AQ_BACKENDS
        self.preload_nested_output = False
        self.hide_fails = False
        self.stray_after_start = None   # a live client that shows up later
        self.live_ws = 3

    def aq_supports_backends(self):
        return self.aq_backends

    def _sleep(self, s):
        self.t += s

    # -- processes -----------------------------------------------------
    def spawn(self, argv, env, log_path):
        self.spawned.append((list(argv), dict(env)))
        rd = pathlib.Path(env["XDG_RUNTIME_DIR"])
        (rd / "hypr" / self.sig).mkdir(parents=True)
        (rd / "hypr" / self.sig / ".socket.sock").write_text("")
        (rd / "bus.addr").write_text("unix:path=/iso/bus")
        (rd / "hyprland.pid").write_text("4242")
        if self.preload_nested_output:
            self.monitors_.append({"name": "WAYLAND-1", "x": 0, "y": 0,
                                   "width": 1280, "height": 720,
                                   "scale": 1.0})
        if "AQ_BACKENDS" not in env:      # nested: a window on the LIVE one
            self.live_clients_.append(
                {"address": "0xnest", "pid": 4242, "class": "aquamarine",
                 "title": "Hyprland", "workspace": {"id": 3, "name": "3"}})
        self.wl = FakeWayland(rd / "wayland-iso").start()
        p = FakeProc(777)
        self.alive[777] = True
        return p

    def pid_alive(self, pid):
        return self.alive.get(int(pid), False)

    def pid_is_session(self, pid):
        return self.stale_pid is False

    def kill_group(self, pid, sig):
        if int(pid) == 888:                      # the marker window
            self.marker = None
            return
        self.alive[int(pid)] = False
        if self.wl is not None:
            self.wl.stop()
            self.wl = None

    def spawn_marker(self, env, profile_dir):
        self.marker = {"address": "0xmark", "title": "canary-wait",
                       "at": [0, 0], "size": [1728, 1080]}
        self.marker_base = len(self.wl.requests) if self.wl else 0
        return FakeProc(888)

    def image_nonblack(self, path):
        return True

    def open_sandbox_apps(self, env, state_dir):
        return [("browser", True, "w1"), ("files", True, "w2")]

    # -- commands --------------------------------------------------------
    def run(self, argv, env=None, timeout=15, input=None):
        self.runs.append((list(argv), dict(env or {})))
        out = b""
        if argv[0] == "hyprctl":
            out = self._hyprctl(argv[1:], env or {})
        elif argv[0] == "systemctl":
            out = self.sysenv if "show-environment" in argv else self.wispd
        elif argv[0] == "wtype":
            if self.marker is not None:
                self.marker["title"] = "typed-" + argv[1]
        elif argv[0] == "grim":
            pathlib.Path(argv[3]).write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, out, b"")

    def _is_live(self, env):
        return env.get("HYPRLAND_INSTANCE_SIGNATURE") == LIVE_SIG

    def _hyprctl(self, args, env):
        args = list(args)
        live = self._is_live(env)
        if args[:2] == ["-j", "activeworkspace"]:
            return json.dumps({"id": self.live_ws}).encode()
        if args[:2] == ["-j", "cursorpos"]:
            x, y = self.live_cursor
            return json.dumps({"x": x, "y": y}).encode()
        if args[:2] == ["-j", "clients"]:
            if live:
                cl = list(self.live_clients_)
                if self.stray_after_start and self.wl is not None:
                    cl.append(self.stray_after_start)
                if self.leak_new_client and self._clicked():
                    cl.append({"address": "0xnew", "title": "x"})
                return json.dumps(cl).encode()
            cl = []
            if self.marker is not None:
                m = dict(self.marker)
                if self._clicked() and not m["title"].startswith("typed"):
                    m["title"] = "canary-hit"
                cl.append(m)
            return json.dumps(cl).encode()
        if args[:3] == ["-j", "monitors", "all"]:
            return json.dumps(self.monitors_).encode()
        if args[:2] == ["output", "create"]:
            n = len(self.monitors_) + 2
            self.monitors_.append({"name": f"HEADLESS-{n}", "x": 0, "y": 0,
                                   "width": 1920, "height": 1080,
                                   "scale": 1.0})
            return b"ok"
        if args[0] == "eval":
            import re
            code = args[1]
            self.evals.append((live, code))
            if "dsp.exit" in code:
                self.exit_dispatched = True
                return b"ok"
            if "window.move" in code:
                if live and not self.hide_fails:
                    addr = re.search(r'address:(\w+)', code).group(1)
                    for c in self.live_clients_:
                        if c["address"] == addr:
                            c["workspace"] = {"id": -99, "name": re.search(
                                r'workspace = "([^"]+)"', code).group(1)}
                return b"ok"
            if "disabled = true" in code:
                n = re.search(r'output = "([^"]+)"', code).group(1)
                for m in self.monitors_:
                    if m["name"] == n:
                        m["disabled"] = True
                return b"ok"
            name = re.search(r'output = "([^"]+)"', code).group(1)
            w, h = re.search(r'mode = "(\d+)x(\d+)@', code).groups()
            x, y = re.search(r'position = "(-?\d+)x(-?\d+)"',
                             code).groups()
            sc = re.search(r"scale = (\d+)", code).group(1)
            for m in self.monitors_:
                if m["name"] == name:
                    m.update(width=int(w), height=int(h), x=int(x),
                             y=int(y), scale=float(sc))
            return b"ok"
        return b"ok"

    def _clicked(self):
        if self.wl is None:
            return False
        hit = any(r == "button" and a[2] == 1
                  for _o, r, a in self.wl.requests[self.marker_base:])
        if hit and self.move_live_cursor_on_click:
            self.live_cursor = (self.live_cursor[0] + 5,
                                self.live_cursor[1])
        return hit


class Base(unittest.TestCase):
    def setUp(self):
        td = shorttmp.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.live_rt = self.tmp / "rt"
        self.live_rt.mkdir()
        (self.live_rt / "wayland-1").write_text("")
        self.sysm = FakeSystem(str(self.live_rt))
        self.addCleanup(lambda: self.sysm.wl and self.sysm.wl.stop())
        self.lines = []
        self.state = self.tmp / "state"

    def session(self):
        return IS.Session(self.sysm, self.state, self.lines.append)

    def say(self):
        return "\n".join(self.lines)


class TestStart(Base):
    def test_child_env_differs_from_live_and_drops_display(self):
        s = self.session()
        self.assertEqual(s.start(), 0, self.say())
        argv, env = self.sysm.spawned[0]
        self.assertEqual(argv[0], "dbus-run-session")
        self.assertIn("Hyprland", argv)
        self.assertNotIn("DISPLAY", env)
        # the OUTER env is the instance env, never the live socket
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")
        self.assertFalse(os.path.isabs(env["WAYLAND_DISPLAY"]))
        self.assertNotIn("HYPRLAND_INSTANCE_SIGNATURE", env)
        self.assertNotEqual(env["XDG_RUNTIME_DIR"], str(self.live_rt))
        self.assertEqual(env["HYPRLAND_NO_SD_VARS"], "1")
        self.assertEqual(env["HYPRLAND_NO_SD_NOTIFY"], "1")
        self.assertEqual(env["HYPRLAND_NO_CRASHREPORTER"], "1")
        self.assertNotIn("AQ_BACKENDS", env)
        # the env file differs from the live session on all three
        st = IS.load_env_file(s.env_file)
        self.assertNotEqual(st["HYPRLAND_INSTANCE_SIGNATURE"], LIVE_SIG)
        self.assertNotEqual(st["WAYLAND_DISPLAY"], "wayland-1")
        self.assertNotEqual(st["XDG_RUNTIME_DIR"], str(self.live_rt))
        self.assertEqual(st["WISP_LIVE_SIGNATURE"], LIVE_SIG)
        self.assertEqual(st["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/iso/bus")
        self.assertEqual(s.env_file.stat().st_mode & 0o777, 0o600)

    def test_only_hyprland_gets_the_absolute_live_socket(self):
        self.assertEqual(self.session().start(), 0, self.say())
        argv, env = self.sysm.spawned[0]
        i = argv.index("Hyprland")
        self.assertEqual(argv[i - 1], str(self.live_rt / "wayland-1"))
        self.assertTrue(os.path.isabs(argv[i - 1]))
        for k in ("DBUS_SESSION_BUS_ADDRESS", "NOTIFY_SOCKET",
                  "HYPRLAND_CMD", "DISPLAY"):
            self.assertNotIn(k, env)

    def test_private_bus_has_no_service_dirs(self):
        self.assertEqual(self.session().start(), 0, self.say())
        argv, env = self.sysm.spawned[0]
        conf = [a for a in argv if a.startswith("--config-file=")]
        self.assertEqual(len(conf), 1)
        self.assertEqual(conf[0], "--config-file=" + os.path.join(
            env["XDG_RUNTIME_DIR"], "dbus.conf"))
        # the dir is removed by stop; read the template instead
        for bad in ("servicedir", "includedir", "<include"):
            self.assertNotIn(bad, IS.DBUS_CONF)
        self.assertIn("unix:path=", IS.DBUS_CONF)

    def test_nested_window_is_hidden_by_pid_on_the_live_session(self):
        before = self.sysm.live_ws
        self.assertEqual(self.session().start(), 0, self.say())
        moves = [(live, c) for live, c in self.sysm.evals
                 if "window.move" in c]
        self.assertEqual(len(moves), 1)
        live, code = moves[0]
        self.assertTrue(live)
        self.assertIn("address:0xnest", code)       # found by pid 4242
        self.assertIn("special:wispisolated", code)
        self.assertIn("silent = true", code)
        self.assertNotIn("class:", code)
        self.assertEqual(self.sysm.live_ws, before)

    def test_start_fails_and_cleans_up_when_the_window_cannot_be_hidden(self):
        self.sysm.hide_fails = True
        s = self.session()
        self.assertEqual(s.start(), 1)
        self.assertIn("not on special:wispisolated", self.say())
        self.assertFalse(self.sysm.alive[777])

    def test_the_nested_output_is_disabled_after_the_headless_ones(self):
        self.sysm.preload_nested_output = True
        s = self.session()
        self.assertEqual(s.start(), 0, self.say())
        nested = [m for m in self.sysm.monitors_ if m["name"] == "WAYLAND-1"]
        self.assertTrue(nested[0].get("disabled"))
        st = IS.load_env_file(s.env_file)
        self.assertEqual(len(st["WISP_ISOLATED_OUTPUTS"].split(",")), 2)

    def test_headless_mode_is_refused_without_aq_backends(self):
        s = IS.Session(self.sysm, self.state, self.lines.append,
                       mode="headless")
        self.assertEqual(s.start(), 2)
        self.assertIn("no AQ_BACKENDS", self.say())
        self.assertEqual(self.sysm.spawned, [])     # DRM never reachable

    def test_headless_mode_when_supported_pins_the_backend(self):
        self.sysm.aq_backends = True
        s = IS.Session(self.sysm, self.state, self.lines.append,
                       mode="headless")
        self.assertEqual(s.start(), 0, self.say())
        argv, env = self.sysm.spawned[0]
        self.assertEqual(env["AQ_BACKENDS"], "headless")
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertEqual(argv[argv.index("Hyprland") - 1], "")
        self.assertFalse([c for _l, c in self.sysm.evals
                          if "window.move" in c])

    def test_two_headless_outputs_shaped_like_the_owners_layout(self):
        s = self.session()
        self.assertEqual(s.start(), 0, self.say())
        got = [(m["width"], m["height"], m["scale"])
               for m in self.sysm.monitors_]
        self.assertEqual(got, [(3456, 2160, 2.0), (3440, 1440, 1.0)])
        st = IS.load_env_file(s.env_file)
        self.assertEqual(st["WISP_ISOLATED_OUTPUTS"],
                         "HEADLESS-2,HEADLESS-3")

    def test_hyprctl_always_targets_the_instance(self):
        s = self.session()
        s.start()
        inst = [e for a, e in self.sysm.runs
                if a[0] == "hyprctl" and a[1] in ("output", "eval")
                and "window.move" not in a[-1]]
        self.assertTrue(inst)
        for e in inst:
            self.assertEqual(e["HYPRLAND_INSTANCE_SIGNATURE"], INST_SIG)
            self.assertNotIn("DISPLAY", e)

    def test_refuses_when_the_signature_equals_the_live_one(self):
        self.sysm.sig = LIVE_SIG
        s = self.session()
        self.assertEqual(s.start(), 1)
        self.assertIn("equals the live", self.say())
        self.assertFalse(s.env_file.exists())

    def test_refuses_without_a_live_wayland_parent(self):
        (self.live_rt / "wayland-1").unlink()      # a tty: no parent
        s = self.session()
        self.assertEqual(s.start(), 2)
        self.assertEqual(self.sysm.spawned, [])    # DRM never touched
        self.assertIn("DRM", self.say())

    def test_refuses_under_a_tty_session_type(self):
        self.sysm.environ["XDG_SESSION_TYPE"] = "tty"
        self.assertEqual(self.session().start(), 2)
        self.assertEqual(self.sysm.spawned, [])

    def test_refuses_a_second_start(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.assertEqual(s.start(), 2)
        self.assertEqual(len(self.sysm.spawned), 1)

    def test_a_failed_canary_stops_the_session(self):
        self.sysm.move_live_cursor_on_click = True
        s = self.session()
        self.assertEqual(s.start(), 1)
        self.assertIn("canary failed", self.say())
        self.assertFalse(self.sysm.alive[777])
        self.assertFalse(s.env_file.exists())

    def test_no_systemd_or_dbus_environment_writes(self):
        self.session().start()
        for argv, _e in self.sysm.runs:
            self.assertNotIn("set-environment", argv)
            self.assertNotIn("import-environment", argv)
            self.assertNotEqual(argv[0], "dbus-update-activation-environment")


class TestCanary(Base):
    def test_passes_when_only_the_instance_sees_the_click(self):
        s = self.session()
        s.start()
        # restart-less re-run on the live session
        self.sysm.marker = None
        ok, detail = s.canary()
        self.assertTrue(ok, detail)
        btn = [a for _o, r, a in self.sysm.wl.requests if r == "button"]
        self.assertTrue(btn)

    def test_fails_when_the_live_cursor_moves(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.move_live_cursor_on_click = True
        ok, detail = s.canary()
        self.assertFalse(ok)
        self.assertIn("LIVE cursor moved", detail)

    def test_fails_when_a_new_client_appears_on_the_live_session(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.leak_new_client = True
        self.sysm.marker_base = len(self.sysm.wl.requests)
        ok, detail = s.canary()
        self.assertFalse(ok)
        self.assertIn("new client appeared on the LIVE", detail)

    def test_a_stray_live_window_fails_the_canary_and_is_only_reported(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.stray_after_start = {"address": "0xdlg", "class":
                                       "gcr-prompter", "title": "OmaSeal"}
        before = len(self.sysm.evals)
        ok, detail = s.canary()
        self.assertFalse(ok)
        self.assertIn("gcr-prompter", detail)
        self.assertIn("OmaSeal", detail)
        self.assertIn("not touched", detail)
        # nothing was dispatched at the live session to close it
        self.assertEqual(self.sysm.evals[before:], [])

    def test_fails_when_the_marker_never_sees_the_click(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.wl.requests[:] = []            # forget the old click
        orig = self.sysm._clicked
        self.sysm._clicked = lambda: False
        ok, detail = s.canary()
        self.sysm._clicked = orig
        self.assertFalse(ok)
        self.assertIn("never saw the click", detail)

    def test_canary_without_a_session_reports_the_env_file(self):
        ok, detail = self.session().canary()
        self.assertFalse(ok)
        self.assertIn("isolated_session.py start", detail)


class TestMarkerReadiness(Base):
    def setUp(self):
        super().setUp()
        self.s = self.session()
        self.state_ = {"XDG_RUNTIME_DIR": "/x"}

    def test_a_reused_address_with_a_new_pid_is_the_new_marker(self):
        old = {"address": "0xA", "pid": 1, "title": "canary-wait"}
        new = {"address": "0xA", "pid": 2, "title": "canary-wait",
               "at": [0, 0], "size": [10, 10]}
        seen = iter([[old], [new]])
        self.s.clients = lambda st: next(seen)
        self.s._ienv = lambda st=None: {}
        self.sysm.mkdtemp = lambda parent: "/tmp/unused-profile"
        got = self.s._marker(self.state_, {})
        self.assertEqual(got["pid"], 2)

    def test_closing_the_marker_reaps_it_before_returning(self):
        proc = FakeProc(888)
        self.s._close_marker({"proc": proc})
        self.assertTrue(proc.waited)

    def test_click_waits_until_the_window_is_focused_and_still(self):
        def rec(focus, at):
            return [{"address": "0xM", "at": at, "size": [10, 10],
                     "focusHistoryID": focus}]
        seq = iter([rec(1, [0, 0]), rec(0, [0, 0]), rec(0, [50, 0]),
                    rec(0, [50, 0]), rec(0, [50, 0])])
        self.s.clients = lambda st: next(seq)
        got = self.s._wait_ready(self.state_, {"address": "0xM"})
        self.assertEqual(got["at"], [50, 0])      # the settled geometry


class TestSmoke(Base):
    def test_passes_and_stops_the_session_it_started(self):
        s = self.session()
        self.assertEqual(s.smoke(soak_s=0), 0, self.say())
        self.assertIn("PASS live-environment-unchanged", self.say())
        self.assertIn("PASS wtype-instance-only", self.say())
        self.assertIn("PASS grim:HEADLESS-2", self.say())
        self.assertFalse(self.sysm.alive[777])

    def test_fails_when_the_live_environment_changed(self):
        s = self.session()
        orig = s.snapshot_live
        calls = {"n": 0}

        def snap():
            calls["n"] += 1
            r = orig()
            if calls["n"] > 1:
                r = dict(r)
                r["systemd-env"] = b"A=1\nB=2\nC=leaked\n"
            return r
        s.snapshot_live = snap
        self.assertEqual(s.smoke(soak_s=0), 1)
        self.assertIn("FAIL live-environment-unchanged", self.say())

    def test_soak_fails_when_the_instance_dies(self):
        s = self.session()
        orig = self.sysm._sleep

        def die(sec):
            orig(sec)
            if sec >= IS.SOAK_POLL_S:
                self.sysm.alive[777] = False
        self.sysm.sleep = die
        self.assertEqual(s.smoke(soak_s=120), 1)
        self.assertIn("FAIL soak: the instance process died", self.say())

    def test_black_screenshot_fails(self):
        self.sysm.image_nonblack = lambda p: False
        self.assertEqual(self.session().smoke(soak_s=0), 1)
        self.assertIn("FAIL grim:HEADLESS-2", self.say())

    def test_a_stray_live_window_during_start_fails_closed(self):
        self.sysm.stray_after_start = {"address": "0xdlg", "class":
                                       "gcr-prompter", "title": "OmaSeal"}
        self.assertEqual(self.session().smoke(soak_s=0), 1)
        self.assertIn("gcr-prompter", self.say())
        self.assertIn("FAIL session-start", self.say())

    def test_a_stray_live_window_fails_smoke(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.stray_after_start = {"address": "0xdlg", "class":
                                       "gcr-prompter", "title": "OmaSeal"}
        self.lines.clear()
        self.assertEqual(s.smoke(soak_s=0), 1)
        self.assertIn("FAIL canary", self.say())
        self.assertIn("FAIL live-clients-unchanged", self.say())
        self.assertIn("close them yourself", self.say())

    def test_clean_smoke_checks_bus_and_live_clients(self):
        self.assertEqual(self.session().smoke(soak_s=0), 0, self.say())
        self.assertIn("PASS bus-no-activation", self.say())
        self.assertIn("PASS live-clients-unchanged", self.say())

    def test_failed_start_names_the_fallback(self):
        self.sysm.sig = LIVE_SIG
        self.assertEqual(self.session().smoke(soak_s=0), 1)
        self.assertIn("fallback", self.say())


class TestStop(Base):
    def test_stop_removes_the_runtime_dir_and_is_safe_twice(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        rdir = IS.load_env_file(s.env_file)["XDG_RUNTIME_DIR"]
        self.assertTrue(os.path.isdir(rdir))
        self.assertEqual(s.stop(), 0)
        self.assertFalse(os.path.exists(rdir))
        self.assertFalse(s.env_file.exists())
        self.assertFalse(self.sysm.alive[777])
        self.assertEqual(s.stop(), 0)             # second call: no error
        self.assertEqual(s.status(), 1)

    def test_stop_exits_via_the_instance_socket_then_kills_only_its_group(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        killed = []
        orig = self.sysm.kill_group
        self.sysm.kill_group = lambda pid, sig: (killed.append(pid),
                                                 orig(pid, sig))
        self.sysm.evals.clear()
        s.stop()
        self.assertTrue(self.sysm.exit_dispatched)
        self.assertEqual([live for live, c in self.sysm.evals
                          if "dsp.exit" in c], [False])   # instance only
        self.assertEqual(set(killed), {777})

    def test_status_reports_the_running_instance(self):
        s = self.session()
        s.start()
        self.lines.clear()
        self.assertEqual(s.status(), 0)
        info = json.loads(self.lines[-1])
        self.assertTrue(info["running"])
        self.assertEqual(info["HYPRLAND_INSTANCE_SIGNATURE"], INST_SIG)


class TestSafetyGuards(Base):
    def test_the_runtime_dir_is_short_and_ours(self):
        s = self.session()
        self.assertEqual(s.start(), 0, self.say())
        rd = IS.load_env_file(s.env_file)["XDG_RUNTIME_DIR"]
        self.assertEqual(os.path.dirname(rd), IS.RUNTIME_ROOT)
        self.assertTrue(os.path.basename(rd).startswith(IS.RUNTIME_PREFIX))
        # Hyprland's longest socket path stays under sun_path (107)
        self.assertLess(len(rd + "/hypr/" + "s" * 61 + "/.socket2.sock"),
                        107)

    def test_stop_never_kills_a_pid_that_is_not_our_session(self):
        s = self.session()
        self.assertEqual(s.start(), 0)
        self.sysm.stale_pid = True        # the pid was reused
        self.assertFalse(s.running())
        s.stop()
        self.assertTrue(self.sysm.alive[777])      # not signalled

    def test_stop_will_not_remove_a_directory_it_did_not_make(self):
        s = self.session()
        s.start()
        victim = self.tmp / "keep"
        victim.mkdir()
        meta = json.loads(s.meta_file.read_text())
        meta["runtime_dir"] = str(victim)
        s.meta_file.write_text(json.dumps(meta))
        s.stop()
        self.assertTrue(victim.is_dir())

    def test_canary_without_a_session_record_fails_instead_of_passing(self):
        s = self.session()
        s.start()
        s.meta_file.unlink()
        ok, detail = s.canary()
        self.assertFalse(ok)
        self.assertIn("cannot tell the live session", detail)

    def test_start_refuses_inside_an_isolated_env(self):
        self.sysm.environ["WISP_ISOLATED_SESSION"] = "1"
        self.assertEqual(self.session().start(), 2)
        self.assertEqual(self.sysm.spawned, [])

    def test_a_missing_binary_is_a_clean_failure_with_cleanup(self):
        def boom(argv, env, log):
            raise FileNotFoundError("dbus-run-session")
        self.sysm.spawn = boom
        s = self.session()
        self.assertEqual(s.start(), 1)
        self.assertFalse(s.meta_file.exists())

    def test_overrides_always_mark_the_session_and_drop_the_live_bus(self):
        env = IS.apply_overrides(
            {"DISPLAY": ":0",
             "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"},
            {"HYPRLAND_INSTANCE_SIGNATURE": "s", "WAYLAND_DISPLAY": "w",
             "XDG_RUNTIME_DIR": "/r", "DBUS_SESSION_BUS_ADDRESS": ""})
        self.assertEqual(env["WISP_ISOLATED_SESSION"], "1")
        self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", env)
        self.assertNotIn("DISPLAY", env)


class TestEnvFile(unittest.TestCase):
    def test_round_trip_and_missing_file(self):
        with shorttmp.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "e.env"
            IS.write_env_file(p, {"HYPRLAND_INSTANCE_SIGNATURE": "S",
                                  "WAYLAND_DISPLAY": "w-1",
                                  "XDG_RUNTIME_DIR": "/a b/c"})
            got = IS.load_env_file(p)
            self.assertEqual(got["XDG_RUNTIME_DIR"], "/a b/c")
            with self.assertRaises(IS.SessionError) as cm:
                IS.load_env_file(pathlib.Path(td) / "none.env")
            self.assertIn("isolated_session.py start", str(cm.exception))

    def test_launch_env_helper_is_pure(self):
        env = IS.launch_env({"DISPLAY": ":0", "WAYLAND_DISPLAY": "w",
                             "HYPRLAND_INSTANCE_SIGNATURE": "s",
                             "XDG_RUNTIME_DIR": "/live", "KEEP": "1"},
                            "/priv")
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/priv")
        self.assertEqual(env["KEEP"], "1")
        self.assertNotIn("DISPLAY", env)


if __name__ == "__main__":
    unittest.main()
