"""The browser lane's native messaging transport: the frame protocol, the
0600 Unix socket and its peer check, the relay Chrome starts, the host
installer and the extension manifest snapshot. Nothing here needs a
browser or the network; clients are plain sockets and pipes."""
import io
import json
import os
import pathlib
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from wisp import trace
from wisp.tools import browser, browser_nm

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXT = ROOT / "browser-extension"
CFG = {"browser": {"lane": "extension"}, "cua": {"audit": "false"}}
PNG = "iVBORw0KGgo="
EXPECTED_ABC = "lkhibglpipabmpokebebeanofnkocccd"


def eventually(fn, tries=500):
    """Poll a condition that another thread makes true. Bounded by tries,
    so a failure is a failed assert, never a hang."""
    for _ in range(tries):
        if fn():
            return True
        time.sleep(0.01)
    return fn()


def chunked(data: bytes, size: int):
    """A read(n) that hands back at most `size` bytes at a time."""
    buf = io.BytesIO(data)
    return lambda n: buf.read(min(n, size))


class Frames(unittest.TestCase):
    def test_a_message_round_trips_with_a_native_order_length(self):
        raw = browser_nm.encode_frame({"t": "ping", "n": "é"})
        body = raw[4:]
        self.assertEqual(int.from_bytes(raw[:4], sys.byteorder), len(body))
        self.assertEqual(browser_nm.read_frame(io.BytesIO(raw).read),
                         {"t": "ping", "n": "é"})

    def test_a_frame_split_into_single_bytes_still_reads(self):
        raw = browser_nm.encode_frame({"t": "hello", "v": 1})
        self.assertEqual(browser_nm.read_frame(chunked(raw, 1)),
                         {"t": "hello", "v": 1})

    def test_two_frames_in_a_row(self):
        raw = (browser_nm.encode_frame({"a": 1})
               + browser_nm.encode_frame({"b": 2}))
        read = io.BytesIO(raw).read
        self.assertEqual(browser_nm.read_frame(read), {"a": 1})
        self.assertEqual(browser_nm.read_frame(read), {"b": 2})
        with self.assertRaises(EOFError):
            browser_nm.read_frame(read)

    def test_a_message_to_the_browser_over_one_megabyte_is_refused(self):
        big = {"t": "cmd", "x": "a" * browser_nm.MAX_TO_BROWSER}
        with self.assertRaises(browser_nm.FrameError):
            browser_nm.encode_frame(big)
        # the same message is fine in the other direction
        browser_nm.encode_frame(big, browser_nm.MAX_FROM_BROWSER)

    def test_a_length_over_the_limit_is_refused_before_reading_it(self):
        head = (browser_nm.MAX_FROM_BROWSER + 1).to_bytes(4, sys.byteorder)
        with self.assertRaises(browser_nm.FrameError):
            browser_nm.read_frame(io.BytesIO(head).read)

    def test_a_truncated_frame_is_a_frame_error_not_a_hang(self):
        raw = browser_nm.encode_frame({"t": "ping"})[:-3]
        with self.assertRaises(browser_nm.FrameError):
            browser_nm.read_frame(io.BytesIO(raw).read)

    def test_bad_json_and_non_objects_are_refused(self):
        for body in (b"{nope", b"[1,2]", b"\xff\xfe", b'"s"'):
            raw = len(body).to_bytes(4, sys.byteorder) + body
            with self.assertRaises(browser_nm.FrameError, msg=body):
                browser_nm.read_frame(io.BytesIO(raw).read)

    def test_a_clean_end_of_stream_is_eof(self):
        with self.assertRaises(EOFError):
            browser_nm.read_frame(io.BytesIO(b"").read)


class FakeBrowser:
    """The extension's side of the socket: sends hello, then answers
    commands from a tiny page model, like the real service worker."""

    def __init__(self, path, hang_on=""):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(10)
        self.sock.connect(str(path))
        self.hang_on = hang_on
        self.cmds = []
        self.got_cmd = threading.Event()
        self.epoch = 0

    def send(self, obj):
        self.sock.sendall(browser_nm.encode_frame(
            obj, browser_nm.MAX_FROM_BROWSER))

    def recv(self):
        return browser_nm.read_frame(self.sock.recv)

    def hello(self):
        self.send({"t": "hello", "v": browser_nm.PROTOCOL})
        return self.recv()

    def serve(self):
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        return t

    def _loop(self):
        try:
            while True:
                msg = self.recv()
                if msg.get("t") != "cmd":
                    continue
                cmd = msg["cmd"]
                self.cmds.append(cmd)
                self.got_cmd.set()
                res = self._answer(cmd)
                if res is not None:
                    self.send(dict(res, t="result", id=cmd["id"]))
        except (OSError, EOFError, browser_nm.FrameError):
            return

    def _answer(self, cmd):
        if cmd.get("op") != "batch":
            return {"ok": True, "results": []}
        out = []
        for s in cmd["steps"]:
            op = s["do"]
            if op == self.hang_on:
                return None
            if op == "snapshot":
                self.epoch += 1
                e = self.epoch
                out.append({"ok": True, "epoch": e, "tab": 7,
                            "url": "https://x.test/login", "title": "Sign in",
                            "text": "Sign in", "elements": [
                                {"ref": f"{e}:0", "tag": "input",
                                 "type": "password", "name": "Password",
                                 "sensitive": True, "value": ""}]})
            elif op == "screenshot":
                out.append({"ok": True, "png": PNG})
            else:
                out.append({"ok": True, "tab": 7} if op == "open"
                           else {"ok": True})
        return {"ok": True, "results": out}

    def close(self):
        # shutdown first: close() alone does not wake the reader thread
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(dir="/tmp"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.lane = browser.Lane(0)
        self.addCleanup(self.lane.close)
        self.path = self.tmp / "run" / "browser.sock"
        self.lane.start_native(self.path)
        self.turn = "t1"
        p = mock.patch.object(trace, "current", lambda: self.turn)
        p.start()
        self.addCleanup(p.stop)
        self.out = self.tmp / "out"

    def browser(self, answer=True, **kw):
        """A paired FakeBrowser. With answer=False nothing reads its
        socket, so a test may read it directly."""
        b = FakeBrowser(self.path, **kw)
        self.addCleanup(b.close)
        self.assertEqual(b.hello(), {"t": "hello_ok",
                                     "v": browser_nm.PROTOCOL})
        if answer:
            b.serve()
        return b

    def run_tool(self, arg):
        return browser.run(arg, CFG, lane=self.lane, out_dir=self.out)


class Socket(ServerCase):
    def test_the_socket_is_private(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode),
                         0o700)

    def test_a_peer_of_another_user_is_refused_and_never_pairs(self):
        other = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(shutil.rmtree, other, True)
        lane = browser.Lane(0)
        self.addCleanup(lane.close)
        p = pathlib.Path(other) / "b.sock"
        lane.start_native(p, uid_of=lambda conn: os.getuid() + 1)
        c = FakeBrowser(p)
        self.addCleanup(c.close)
        # the refusal can land before or after the hello: either way the
        # peer sees a closed socket and never an answer
        with self.assertRaises((EOFError, OSError)):
            c.send({"t": "hello", "v": browser_nm.PROTOCOL})
            c.recv()
        self.assertFalse(lane.paired)

    def test_a_hello_with_the_wrong_version_gets_an_error_and_no_pairing(self):
        c = FakeBrowser(self.path)
        self.addCleanup(c.close)
        c.send({"t": "hello", "v": 99})
        self.assertEqual(c.recv()["code"], "bad_hello")
        self.assertFalse(self.lane.paired)

    def test_anything_before_hello_is_refused(self):
        c = FakeBrowser(self.path)
        self.addCleanup(c.close)
        c.send({"t": "result", "id": "c1", "ok": True})
        self.assertEqual(c.recv()["code"], "bad_hello")
        self.assertFalse(self.lane.paired)

    def test_hello_pairs_and_hanging_up_unpairs(self):
        self.assertFalse(self.lane.paired)
        b = self.browser()
        self.assertTrue(self.lane.paired)
        b.close()
        self.assertTrue(eventually(lambda: not self.lane.paired))

    def test_the_newest_browser_replaces_the_older_one(self):
        first = self.browser(answer=False)
        second = self.browser(answer=False)
        with self.assertRaises((EOFError, OSError)):
            first.recv()
        self.assertTrue(self.lane.paired)
        second.send({"t": "ping"})
        self.assertEqual(second.recv(), {"t": "pong"})

    def test_an_unknown_message_is_answered_and_the_link_stays(self):
        c = FakeBrowser(self.path)
        self.addCleanup(c.close)
        c.hello()
        c.send({"t": "launch_missiles"})
        self.assertEqual(c.recv()["code"], "unknown_message")
        c.send({"t": "ping"})
        self.assertEqual(c.recv(), {"t": "pong"})

    def test_an_oversized_frame_drops_the_connection(self):
        c = FakeBrowser(self.path)
        self.addCleanup(c.close)
        c.hello()
        c.sock.sendall((browser_nm.MAX_FROM_BROWSER + 1)
                       .to_bytes(4, sys.byteorder))
        with self.assertRaises((EOFError, OSError)):
            c.recv()
        self.assertTrue(eventually(lambda: not self.lane.paired))

    def test_a_leftover_socket_file_is_replaced(self):
        d = pathlib.Path(tempfile.mkdtemp(dir="/tmp"))
        self.addCleanup(shutil.rmtree, d, True)
        p = d / "b.sock"
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(p))
        s.close()                    # a socket file nobody listens on
        lane = browser.Lane(0)
        self.addCleanup(lane.close)
        lane.start_native(p)
        c = FakeBrowser(p)
        self.addCleanup(c.close)
        self.assertEqual(c.hello()["t"], "hello_ok")

    def test_a_regular_file_at_the_path_is_never_deleted(self):
        d = pathlib.Path(tempfile.mkdtemp(dir="/tmp"))
        self.addCleanup(shutil.rmtree, d, True)
        p = d / "b.sock"
        p.write_text("keep me")
        lane = browser.Lane(0)
        self.addCleanup(lane.close)
        with self.assertRaises(OSError):
            lane.start_native(p)
        self.assertEqual(p.read_text(), "keep me")

    def test_a_second_wispd_does_not_steal_a_live_socket(self):
        lane = browser.Lane(0)
        self.addCleanup(lane.close)
        with self.assertRaises(OSError):
            lane.start_native(self.path)
        self.browser()                    # the first server still answers


class Commands(ServerCase):
    def test_a_batch_runs_through_the_socket(self):
        b = self.browser()
        out = self.run_tool(json.dumps({"steps": [
            {"do": "open", "url": "https://x.test/login"},
            {"do": "snapshot"}]}))
        self.assertTrue(out.startswith("OK (browser, 2 steps)"), out)
        self.assertIn("1:0 input/password 'Password' [never filled]", out)
        self.assertEqual(b.cmds[0]["task"], "t1")

    def test_a_password_ref_is_refused_before_anything_is_sent(self):
        b = self.browser()
        self.run_tool("snapshot")
        sent = len(b.cmds)
        out = self.run_tool("fill 1:0 hunter2")
        self.assertIn("never filled", out)
        self.assertEqual(len(b.cmds), sent)

    def test_the_proof_screenshot_is_saved(self):
        self.browser()
        out = self.run_tool("screenshot")
        self.assertIn("screenshot saved to", out)
        self.assertEqual(len(list(self.out.glob("proof-*.png"))), 1)

    def test_stop_from_the_browser_ends_the_call_in_under_a_second(self):
        b = self.browser(hang_on="wait_for")
        got = {}

        def go():
            got["out"] = self.run_tool(json.dumps({"steps": [
                {"do": "wait_for", "text": "never"}]}))
        th = threading.Thread(target=go)
        th.start()
        self.assertTrue(b.got_cmd.wait(10))
        t0 = time.monotonic()
        b.send({"t": "stop"})
        th.join(10)
        self.assertEqual(got["out"], browser.MSG_STOPPED)
        self.assertLess(time.monotonic() - t0, 1.0)
        sent = len(b.cmds)
        self.assertEqual(self.run_tool("snapshot"), browser.MSG_STOPPED)
        self.assertEqual(len(b.cmds), sent)

    def test_a_browser_that_disconnects_mid_call_fails_it_at_once(self):
        b = self.browser(hang_on="wait_for")
        got = {}

        def go():
            got["out"] = self.run_tool(json.dumps({"steps": [
                {"do": "wait_for", "text": "never"}]}))
        th = threading.Thread(target=go)
        th.start()
        self.assertTrue(b.got_cmd.wait(10))
        t0 = time.monotonic()
        b.close()
        th.join(10)
        self.assertIn("the browser disconnected", got["out"])
        self.assertLess(time.monotonic() - t0, 2.0)

    def test_a_command_that_could_not_be_sent_is_queued_again(self):
        self.lane.requeue({"id": "c9", "op": "batch", "steps": []})
        self.assertEqual(self.lane.next_command(0)["id"], "c9")

    def test_with_nobody_connected_the_tool_does_nothing(self):
        out = self.run_tool("open https://x.test/")
        self.assertTrue(out.startswith("SKIP (the browser lane is not paired"))
        self.assertIn("press Connect", out)
        self.assertIn("Nothing was done", out)
        self.assertTrue(self.lane._cmds.empty())


class Pipe:
    """A pair of file objects over os.pipe, for the relay's stdio."""

    def __init__(self):
        r, w = os.pipe()
        self.r, self.w = os.fdopen(r, "rb", 0), os.fdopen(w, "wb", 0)

    def close(self):
        for f in (self.r, self.w):
            f.close()


class Relay(ServerCase):
    def test_frames_cross_the_relay_both_ways(self):
        to_relay, from_relay = Pipe(), Pipe()
        self.addCleanup(to_relay.close)
        self.addCleanup(from_relay.close)
        done = threading.Event()

        def go():
            browser_nm.relay(to_relay.r, from_relay.w, self.path)
            done.set()
        threading.Thread(target=go, daemon=True).start()
        to_relay.w.write(browser_nm.encode_frame(
            {"t": "hello", "v": browser_nm.PROTOCOL}))
        self.assertEqual(browser_nm.read_frame(from_relay.r.read)["t"],
                         "hello_ok")
        self.assertTrue(self.lane.paired)
        to_relay.w.write(browser_nm.encode_frame({"t": "ping"}))
        self.assertEqual(browser_nm.read_frame(from_relay.r.read),
                         {"t": "pong"})
        to_relay.w.close()           # Chrome closed the port
        self.assertTrue(done.wait(10))
        self.assertTrue(eventually(lambda: not self.lane.paired))

    def test_a_missing_socket_is_reported_to_the_extension(self):
        err = io.BytesIO()
        code = browser_nm.relay(io.BytesIO(b""), err, self.tmp / "none.sock")
        self.assertEqual(code, 0)
        msg = browser_nm.read_frame(io.BytesIO(err.getvalue()).read)
        self.assertEqual((msg["t"], msg["code"]), ("error", "wisp_unavailable"))

    def test_the_real_entrypoint_relays_over_stdio(self):
        env = dict(os.environ, XDG_RUNTIME_DIR=str(self.tmp / "rt"))
        (self.tmp / "rt" / "wisp").mkdir(parents=True)
        lane = browser.Lane(0)
        self.addCleanup(lane.close)
        lane.start_native(self.tmp / "rt" / "wisp" / browser_nm.SOCKET_NAME)
        p = subprocess.Popen(
            [sys.executable, str(ROOT / "wispd"), "nmhost",
             "chrome-extension://" + browser_nm.DEV_EXTENSION_ID + "/"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.kill)
        p.stdin.write(browser_nm.encode_frame(
            {"t": "hello", "v": browser_nm.PROTOCOL}))
        p.stdin.flush()
        self.assertEqual(browser_nm.read_frame(p.stdout.read)["t"],
                         "hello_ok")
        p.stdin.close()
        self.assertEqual(p.wait(30), 0)


class Installer(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.data = self.home / ".local" / "share" / "wisp"
        (self.home / ".config" / "chromium").mkdir(parents=True)
        (self.home / ".config" / "google-chrome").mkdir(parents=True)
        self.ids = [browser_nm.DEV_EXTENSION_ID]

    def install(self, **kw):
        return browser_nm.install_host(
            self.home, self.data, "/usr/bin/python3", "/opt/wisp/wispd",
            kw.get("ids", self.ids), kw.get("browsers"))

    def test_it_writes_a_private_launcher_and_a_manifest_per_browser(self):
        r = self.install()
        self.assertEqual({m["browser"] for m in r["manifests"]},
                         {"chromium", "chrome"})
        launcher = pathlib.Path(r["launcher"])
        self.assertEqual(stat.S_IMODE(launcher.stat().st_mode), 0o700)
        self.assertEqual(launcher.read_text(),
                         "#!/bin/sh\nexec /usr/bin/python3 /opt/wisp/wispd "
                         'nmhost "$@"\n')
        for m in r["manifests"]:
            path = pathlib.Path(m["path"])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            doc = json.loads(path.read_text())
            self.assertEqual(doc["name"], "com.wisp.browser")
            self.assertEqual(doc["type"], "stdio")
            self.assertEqual(doc["path"], str(launcher))
            self.assertEqual(doc["allowed_origins"], [
                f"chrome-extension://{browser_nm.DEV_EXTENSION_ID}/"])

    def test_only_browsers_that_exist_are_touched(self):
        shutil.rmtree(self.home / ".config" / "google-chrome")
        r = self.install()
        self.assertEqual([m["browser"] for m in r["manifests"]], ["chromium"])
        self.assertFalse((self.home / ".config" / "BraveSoftware").exists())

    def test_it_is_idempotent(self):
        first = self.install()
        again = self.install()
        self.assertEqual(first, again)

    def test_origins_are_exact_ids_never_wildcards(self):
        other = "a" * 32
        r = self.install(ids=[browser_nm.DEV_EXTENSION_ID, other])
        doc = json.loads(pathlib.Path(r["manifests"][0]["path"]).read_text())
        self.assertEqual(len(doc["allowed_origins"]), 2)
        for o in doc["allowed_origins"]:
            self.assertRegex(o, r"^chrome-extension://[a-p]{32}/$")

    def test_bad_requests_say_why_and_write_nothing(self):
        for kw, why in (({"ids": []}, "no extension id"),
                        ({"ids": ["*"]}, "not an extension id"),
                        ({"ids": ["z" * 32]}, "not an extension id"),
                        ({"browsers": ["netscape"]}, "unknown browser")):
            with self.assertRaises(ValueError, msg=kw) as cx:
                self.install(**kw)
            self.assertIn(why, str(cx.exception))
        self.assertFalse(self.data.exists())

    def test_no_supported_browser_is_an_error(self):
        shutil.rmtree(self.home / ".config")
        with self.assertRaises(ValueError):
            self.install()

    def test_uninstall_removes_only_what_was_recorded(self):
        r = self.install()
        bystander = pathlib.Path(r["manifests"][0]["path"]).with_name(
            "com.other.host.json")
        bystander.write_text("{}")
        removed = browser_nm.uninstall_host(self.data)
        self.assertEqual(len(removed), 3)         # two manifests + launcher
        self.assertTrue(bystander.exists())
        for m in r["manifests"]:
            self.assertFalse(pathlib.Path(m["path"]).exists())
        self.assertEqual(browser_nm.uninstall_host(self.data), [])

    def test_uninstall_skips_a_manifest_that_is_no_longer_ours(self):
        r = self.install()
        path = pathlib.Path(r["manifests"][0]["path"])
        path.write_text(json.dumps({"name": "com.someone.else"}))
        browser_nm.uninstall_host(self.data)
        self.assertTrue(path.exists())

    def test_status_reports_what_is_installed(self):
        sock = self.home / "none.sock"
        self.assertFalse(any(b["installed"] for b in browser_nm.status(
            self.home, self.data, sock)["browsers"]))
        self.install()
        st = browser_nm.status(self.home, self.data, sock)
        installed = {b["browser"] for b in st["browsers"] if b["installed"]}
        self.assertEqual(installed, {"chromium", "chrome"})
        self.assertTrue(st["launcher_ok"])
        self.assertFalse(st["socket_live"])

    def test_the_cli_installs_into_the_given_home_only(self):
        env = dict(os.environ, HOME=str(self.home),
                   XDG_DATA_HOME=str(self.home / ".local" / "share"),
                   XDG_CONFIG_HOME=str(self.home / ".config"),
                   XDG_RUNTIME_DIR=str(self.home / "rt"))
        p = subprocess.run(
            [sys.executable, str(ROOT / "wispd"), "browser", "install-host",
             "--dev", "--json"], env=env, capture_output=True, text=True,
            timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads(p.stdout)["data"]
        for m in data["manifests"]:
            self.assertTrue(m["path"].startswith(str(self.home)))
        s = subprocess.run(
            [sys.executable, str(ROOT / "wispd"), "browser", "status",
             "--json"], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertTrue(json.loads(s.stdout)["data"]["launcher_ok"])

    def test_the_cli_needs_an_id_or_dev(self):
        env = dict(os.environ, HOME=str(self.home),
                   XDG_DATA_HOME=str(self.home / ".local" / "share"))
        p = subprocess.run(
            [sys.executable, str(ROOT / "wispd"), "browser", "install-host"],
            env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertFalse(self.data.exists())


class ExtensionIdentity(unittest.TestCase):
    def test_the_dev_id_is_the_id_of_the_key_pinned_in_the_config(self):
        cfg = (EXT / "wxt.config.ts").read_text()
        key = re.search(r"DEV_KEY\s*=\s*['\"]([A-Za-z0-9+/=]+)['\"]", cfg)
        self.assertIsNotNone(key, "wxt.config.ts pins no key")
        self.assertEqual(browser_nm.extension_id_from_key(key.group(1)),
                         browser_nm.DEV_EXTENSION_ID)
        # and the committed manifest snapshot carries that same key
        self.assertEqual(ManifestSnapshot.SNAP["key"], key.group(1))

    def test_the_id_algorithm_matches_an_independent_computation(self):
        # base64 of b"abc"; the expected id came from
        # `printf abc | sha256sum | cut -c1-32 | tr '0-9a-f' 'a-p'`
        self.assertEqual(browser_nm.extension_id_from_key("YWJj"),
                         EXPECTED_ABC)


class ManifestSnapshot(unittest.TestCase):
    """The shipped manifest's permissions are pinned twice on purpose: the
    snapshot file (compared with the real build in the extension's tests)
    and the allowlists below, which an edit to the snapshot cannot move."""

    SNAP = json.loads((EXT / "tests" / "manifest.snapshot.json").read_text())
    ALLOWED = {"tabs", "tabGroups", "scripting", "nativeMessaging",
               "storage", "sidePanel"}
    FORBIDDEN = {"debugger", "cookies", "history", "webRequest",
                 "webNavigation", "downloads", "management", "activeTab",
                 "clipboardRead", "clipboardWrite", "alarms", "bookmarks",
                 "declarativeNetRequest", "proxy", "identity", "tabCapture",
                 "desktopCapture", "pageCapture", "privacy", "contentSettings"}

    def test_permissions_are_exactly_the_allowed_set(self):
        self.assertEqual(set(self.SNAP["permissions"]), self.ALLOWED)

    def test_no_debugger_or_other_forbidden_permission_anywhere(self):
        every = (set(self.SNAP.get("permissions", []))
                 | set(self.SNAP.get("optional_permissions", [])))
        self.assertFalse(every & self.FORBIDDEN, every & self.FORBIDDEN)

    def test_host_access_is_optional_not_required(self):
        self.assertNotIn("host_permissions", self.SNAP)
        self.assertEqual(self.SNAP["optional_host_permissions"],
                         ["<all_urls>"])
        for p in self.SNAP["permissions"]:
            self.assertNotIn("://", p)
            self.assertNotEqual(p, "<all_urls>")

    def test_nothing_that_lets_a_page_reach_the_extension(self):
        for key in ("content_scripts", "externally_connectable",
                    "web_accessible_resources", "devtools_page",
                    "chrome_url_overrides", "content_security_policy"):
            self.assertNotIn(key, self.SNAP, key)
        self.assertEqual(self.SNAP["incognito"], "not_allowed")
        self.assertEqual(self.SNAP["manifest_version"], 3)

    def test_the_snapshot_pins_the_dev_key(self):
        self.assertEqual(browser_nm.extension_id_from_key(self.SNAP["key"]),
                         browser_nm.DEV_EXTENSION_ID)


if __name__ == "__main__":
    unittest.main()
