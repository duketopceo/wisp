"""Self-tests for the W5 fakes (tests/fakes): cua-driver, Hyprland,
notify-send, systemctl --user and the leak guard. Offline, loopback and
temp dirs only; no real cua-driver/Hyprland/systemctl is ever spawned."""
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fakes  # noqa: E402


class Sandbox:
    """Temp root + HOME/run dirs + a BinDir, torn down on exit."""

    def __init__(self):
        self.td = tempfile.TemporaryDirectory(prefix="wisp-fakes-")
        self.root = pathlib.Path(self.td.name)
        self.home = self.root / "home"
        self.run = self.root / "run"
        self.home.mkdir()
        self.run.mkdir()
        self.bins = fakes.BinDir(self.root / "bin")

    def env(self, **extra):
        e = {"PATH": str(self.bins.path), "HOME": str(self.home),
             "XDG_RUNTIME_DIR": str(self.run)}
        e.update(extra)
        return e

    def sh(self, *argv, env=None, timeout=10):
        return subprocess.run(list(argv), capture_output=True, text=True,
                              env=env or self.env(), timeout=timeout)

    def close(self):
        self.td.cleanup()


class CuaTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)

    def make(self, **script):
        cua = fakes.FakeCua(self.sb.home, self.sb.bins, script)
        cua.start()
        self.addCleanup(cua.stop)
        return cua

    def test_socket_at_wisp_path_and_cli_records_call(self):
        cua = self.make()
        sock = self.sb.home / ".cache" / "cua-driver" / "cua-driver.sock"
        self.assertEqual(cua.sock_path, sock)
        self.assertTrue(sock.exists())
        r = self.sb.sh("cua-driver", "call", "click",
                       json.dumps({"x": 10, "y": 20, "scope": "desktop"}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(cua.tools(), ["click"])
        self.assertEqual(cua.calls[0]["args"]["x"], 10)
        self.assertEqual(json.loads(r.stdout)["ok"], True)

    def test_scripted_refusal_exits_nonzero(self):
        cua = self.make(tools={"click": {"ok": False,
                                         "error": "E_CUA_REFUSED"}})
        r = self.sb.sh("cua-driver", "call", "click", "{}")
        self.assertEqual(r.returncode, 1)
        self.assertIn("E_CUA_REFUSED", r.stderr)
        self.assertEqual(cua.tools(), ["click"])
        r = self.sb.sh("cua-driver", "call", "move_cursor", "{}")
        self.assertEqual(r.returncode, 0)

    def test_stale_socket_exists_but_refuses(self):
        cua = self.make(mode="stale")
        self.assertTrue(cua.sock_path.exists())
        r = self.sb.sh("cua-driver", "call", "click", "{}")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("E_CUA_DOWN", r.stderr)
        self.assertEqual(cua.calls, [])

    def test_absent_mode_has_no_binary_and_no_socket(self):
        cua = self.make(mode="absent")
        self.assertFalse(cua.sock_path.exists())
        self.assertIsNone(shutil.which("cua-driver",
                                       path=str(self.sb.bins.path)))

    def test_latency_is_applied(self):
        import time
        cua = self.make(tools={"click": {"latency_ms": 200}})
        t = time.monotonic()
        self.sb.sh("cua-driver", "call", "click", "{}")
        self.assertGreaterEqual(time.monotonic() - t, 0.19)
        self.assertEqual(cua.tools(), ["click"])

    def test_hang_is_killed_by_caller_timeout(self):
        self.make(tools={"click": {"hang": True}})
        with self.assertRaises(subprocess.TimeoutExpired):
            self.sb.sh("cua-driver", "call", "click", "{}", timeout=0.5)


class HyprTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)

    def make(self, **script):
        h = fakes.FakeHypr(runtime_dir=self.sb.run, bins=self.sb.bins,
                           script=script)
        h.start()
        self.addCleanup(h.stop)
        return h

    def test_env_and_socket_layout(self):
        h = self.make()
        self.assertEqual(h.env()["XDG_RUNTIME_DIR"], str(self.sb.run))
        self.assertTrue((self.sb.run / "hypr" / h.sig
                         / ".socket.sock").exists())
        self.assertTrue((self.sb.run / "hypr" / h.sig
                         / ".socket2.sock").exists())

    def test_wisp_hypr_module_talks_to_it(self):
        from wisp import hypr
        h = self.make()
        old = dict(os.environ)
        os.environ.update(h.env())
        try:
            hypr.reset()
            self.assertTrue(hypr.run_lua(hypr.cursor_move(5, 6)))
        finally:
            os.environ.clear()
            os.environ.update(old)
            hypr.reset()
        self.assertTrue(any("cursor.move" in r for r in h.requests))

    def test_scripted_replies_override_probe_defaults(self):
        h = self.make(replies={"j/activewindow": {"class": "firefox"}})
        r = self.sb.sh("hyprctl", "-j", "activewindow",
                       env=self.sb.env(**h.env()))
        self.assertEqual(json.loads(r.stdout)["class"], "firefox")
        self.assertIn("j/activewindow", h.requests)

    def test_hyprctl_shim_forwards_eval(self):
        h = self.make()
        r = self.sb.sh("hyprctl", "eval", "return 1",
                       env=self.sb.env(**h.env()))
        self.assertEqual(r.stdout.strip(), "ok")
        self.assertIn("eval return 1", h.requests)

    def test_event_stream_emit_reaches_connected_client(self):
        h = self.make(hold_events=True)
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(str(self.sb.run / "hypr" / h.sig / ".socket2.sock"))
        h.wait_event_clients(1)
        h.emit("activewindow>>kitty,~")
        self.assertEqual(s.recv(4096), b"activewindow>>kitty,~\n")
        s.close()

    def test_scripted_events_sent_on_connect(self):
        h = self.make(events=["workspace>>2", "openwindow>>a,2,foot,x"])
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(str(self.sb.run / "hypr" / h.sig / ".socket2.sock"))
        data = b""
        while data.count(b"\n") < 2:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        self.assertEqual(data.decode().splitlines(),
                         ["workspace>>2", "openwindow>>a,2,foot,x"])

    def test_hang_reply(self):
        h = self.make(hang=["j/clients"])
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(0.3)
        s.connect(str(self.sb.run / "hypr" / h.sig / ".socket.sock"))
        s.sendall(b"j/clients")
        with self.assertRaises(socket.timeout):
            s.recv(10)
        s.close()


class NotifyTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)
        self.n = fakes.FakeNotify(self.sb.bins)

    def test_records_title_body_and_options(self):
        r = self.sb.sh("notify-send", "-a", "wisp", "-u", "critical",
                       "-t", "5000", "Wisp", "hello there")
        self.assertEqual(r.returncode, 0)
        n = self.n.notifications
        self.assertEqual(len(n), 1)
        self.assertEqual((n[0]["title"], n[0]["body"]), ("Wisp",
                                                          "hello there"))
        self.assertEqual(n[0]["app"], "wisp")
        self.assertEqual(n[0]["urgency"], "critical")
        self.assertEqual(n[0]["timeout"], 5000)

    def test_print_id_and_replace_id(self):
        a = self.sb.sh("notify-send", "-p", "Wisp", "one").stdout.strip()
        b = self.sb.sh("notify-send", "-p", "Wisp", "two").stdout.strip()
        self.assertNotEqual(a, b)
        c = self.sb.sh("notify-send", "-p", "-r", a, "Wisp",
                       "one-again").stdout.strip()
        self.assertEqual(c, a)
        n = self.n.notifications
        self.assertEqual([x["replaces"] for x in n], [0, 0, int(a)])
        self.assertEqual(self.n.live_bodies(), ["one-again", "two"])

    def test_actions_recorded_and_invoked_with_wait(self):
        self.n.script(invoke="yes")
        r = self.sb.sh("notify-send", "-w", "-A", "yes=Allow",
                       "-A", "no=Deny", "Wisp", "run ls?")
        self.assertEqual(r.stdout.strip(), "yes")
        n = self.n.notifications[0]
        self.assertEqual(n["actions"], [{"name": "yes", "label": "Allow"},
                                        {"name": "no", "label": "Deny"}])
        self.assertTrue(n["wait"])

    def test_wait_without_invoke_prints_nothing(self):
        r = self.sb.sh("notify-send", "-w", "-A", "yes=Allow", "W", "b")
        self.assertEqual(r.stdout, "")

    def test_failure_script(self):
        self.n.script(exit=1)
        r = self.sb.sh("notify-send", "W", "b")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(self.n.notifications), 1)


NS = ["--session", "--dest", "org.freedesktop.Notifications",
      "--object-path", "/org/freedesktop/Notifications"]
M = "org.freedesktop.Notifications."


class GdbusNotifyTest(unittest.TestCase):
    """The notification SERVER as wisp's W18 uses it: gdbus call Notify /
    CloseNotification / GetCapabilities and gdbus monitor for signals."""

    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)
        self.n = fakes.FakeNotify(self.sb.bins)

    def notify(self, summary="Wisp", body="hi", rid="0",
               actions="[]", timeout="-1"):
        return self.sb.sh("gdbus", "call", *NS, "--method", M + "Notify",
                          "wisp", rid, "", summary, body, actions, "{}",
                          timeout)

    def test_notify_returns_uint32_id_and_records(self):
        r = self.notify("T", "it's here", timeout="5000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "(uint32 1,)")
        n = self.n.notifications[0]
        self.assertEqual((n["id"], n["title"], n["body"], n["app"],
                          n["timeout"]), (1, "T", "it's here", "wisp",
                                          5000))

    def test_replace_id_reuses_and_records(self):
        self.notify("A", "one")
        r = self.notify("A", "two", rid="1")
        self.assertEqual(r.stdout.strip(), "(uint32 1,)")
        self.assertEqual([x["replaces"] for x in self.n.notifications],
                         [0, 1])
        self.assertEqual(self.n.live_bodies(), ["two"])

    def test_actions_parsed_from_flat_list(self):
        self.notify("A", "b", actions="['yes', 'Allow', 'no', 'Deny']")
        self.assertEqual(self.n.notifications[0]["actions"],
                         [{"name": "yes", "label": "Allow"},
                          {"name": "no", "label": "Deny"}])

    def test_capabilities_match_quickshell(self):
        r = self.sb.sh("gdbus", "call", *NS, "--method",
                       M + "GetCapabilities")
        for cap in ("persistence", "body", "body-markup",
                    "body-hyperlinks", "actions", "icon-static"):
            self.assertIn(f"'{cap}'", r.stdout)
        self.assertNotIn("'sound'", r.stdout)

    def test_server_information(self):
        r = self.sb.sh("gdbus", "call", *NS, "--method",
                       M + "GetServerInformation")
        self.assertIn("quickshell", r.stdout)

    def test_close_notification_emits_closed_signal(self):
        self.notify()
        self.sb.sh("gdbus", "call", *NS, "--method",
                   M + "CloseNotification", "1")
        self.assertEqual(self.n.closed(), [(1, 3)])
        self.assertEqual(self.n.live_bodies(), [])

    def test_monitor_prints_action_invoked(self):
        self.n.script(auto_invoke={"action": "yes", "delay_ms": 50})
        self.notify("A", "b", actions="['yes', 'Allow']")
        p = subprocess.Popen(["gdbus", "monitor", "--session", "--dest",
                              "org.freedesktop.Notifications"],
                             stdout=subprocess.PIPE, text=True,
                             env=self.sb.env())
        self.addCleanup(p.kill)
        line = p.stdout.readline()
        self.assertIn(M + "ActionInvoked", line)
        self.assertIn("uint32 1", line)
        self.assertIn("'yes'", line)

    def test_driver_invoke_and_close_signals(self):
        self.notify("A", "b", actions="['yes', 'Allow']")
        self.n.invoke(1, "yes")
        self.n.close(1, reason=2)
        p = subprocess.Popen(["gdbus", "monitor", "--session"],
                             stdout=subprocess.PIPE, text=True,
                             env=self.sb.env())
        self.addCleanup(p.kill)
        a, b = p.stdout.readline(), p.stdout.readline()
        self.assertIn("ActionInvoked", a)
        self.assertIn("NotificationClosed (uint32 1, uint32 2)", b)

    def test_system_bus_refused(self):
        r = self.sb.sh("gdbus", "call", "--system", *NS[1:], "--method",
                       M + "Notify", "a", "0", "", "t", "b", "[]", "{}",
                       "-1")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.n.notifications, [])

    def test_server_down_script(self):
        self.n.script(server_down=True)
        r = self.notify()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ServiceUnknown", r.stderr)
        self.assertEqual(self.n.notifications, [])


class SystemctlTest(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()
        self.addCleanup(self.sb.close)
        self.sc = fakes.FakeSystemctl(
            self.sb.bins, {"units": {"llama-local.service": "inactive",
                                     "llama-jev.service": "active",
                                     "broken.service": {
                                         "state": "inactive",
                                         "start_ok": False}}})

    def test_start_flips_state_and_is_recorded(self):
        r = self.sb.sh("systemctl", "--user", "start", "llama-local")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sc.state("llama-local"), "active")
        self.assertEqual(self.sc.commands(),
                         ["start llama-local.service"])

    def test_is_active_exit_codes(self):
        a = self.sb.sh("systemctl", "--user", "is-active",
                       "llama-jev.service")
        self.assertEqual((a.returncode, a.stdout.strip()), (0, "active"))
        b = self.sb.sh("systemctl", "--user", "is-active",
                       "llama-local.service")
        self.assertEqual((b.returncode, b.stdout.strip()), (3, "inactive"))

    def test_failed_start_and_stop(self):
        r = self.sb.sh("systemctl", "--user", "start", "broken.service")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.sc.state("broken.service"), "failed")
        self.sb.sh("systemctl", "--user", "stop", "llama-jev")
        self.assertEqual(self.sc.state("llama-jev"), "inactive")

    def test_unknown_unit_fails(self):
        r = self.sb.sh("systemctl", "--user", "start", "nope.service")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not found", r.stderr)

    def test_system_scope_refused_and_flagged(self):
        r = self.sb.sh("systemctl", "start", "llama-local.service")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.sc.state("llama-local"), "inactive")
        self.assertTrue(self.sc.violations())

    def test_matches_wisp_health_start_command(self):
        from wisp import health
        cmd = health.start_command(["llama-local.service"])
        r = self.sb.sh(*cmd)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.sc.state("llama-local"), "active")


class GuardTest(unittest.TestCase):
    def test_blocks_non_loopback_bind_and_outside_unix_path(self):
        with tempfile.TemporaryDirectory() as d:
            g = fakes.LeakGuard(d)
            g.install()
            try:
                s = socket.socket()
                with self.assertRaises(fakes.LeakViolation):
                    s.bind(("0.0.0.0", 0))
                s.close()
                u = socket.socket(socket.AF_UNIX)
                with self.assertRaises(fakes.LeakViolation):
                    u.bind("/tmp/wisp-leak-test.sock")
                u.close()
                ok = socket.socket(socket.AF_UNIX)
                ok.bind(os.path.join(d, "fine.sock"))
                ok.close()
                lo = socket.socket()
                lo.bind(("127.0.0.1", 0))
                lo.close()
            finally:
                g.uninstall()
            self.assertEqual(len(g.violations), 2)
        self.assertFalse(os.path.exists("/tmp/wisp-leak-test.sock"))

    def test_uninstall_restores_socket(self):
        orig = socket.socket.bind
        g = fakes.LeakGuard("/nonexistent")
        g.install()
        g.uninstall()
        self.assertIs(socket.socket.bind, orig)

    def test_check_paths_flags_escapes(self):
        with tempfile.TemporaryDirectory() as d:
            g = fakes.LeakGuard(d)
            self.assertEqual(g.check_paths([d + "/a/b"]), [])
            self.assertEqual(len(g.check_paths(["/etc/passwd",
                                                d + "/../x"])), 2)


class BinDirTest(unittest.TestCase):
    def test_strict_path_resolves_only_fakes(self):
        with tempfile.TemporaryDirectory() as d:
            b = fakes.BinDir(pathlib.Path(d) / "bin")
            fakes.FakeNotify(b)
            p = str(b.path)
            self.assertTrue(shutil.which("notify-send", path=p))
            self.assertIsNone(shutil.which("ls", path=p))
            self.assertEqual(b.names(), ["gdbus", "notify-send"])


if __name__ == "__main__":
    unittest.main()
