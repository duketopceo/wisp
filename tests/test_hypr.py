"""Hyprland socket layer + bind registry (backend U5).

A fake Hyprland serves the request socket (.socket.sock, one request per
connection, reply then close) and the event socket (.socket2.sock). Nothing
here touches the live session or spawns hyprctl."""
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from wisp import hypr, platform
from wisp.tools import desktop

FIXTURE = json.loads((pathlib.Path(__file__).parent / "fixtures"
                      / "hypr_probe.json").read_text())
INJECT = '"); hl.dsp.exec_cmd("rm -rf ~'


def ok_handler(r):
    """Fixture JSON for queries, 'ok' for every eval."""
    return FIXTURE[r] if r.startswith("j/") and r in FIXTURE else "ok"


class FakeHypr:
    """Unix-socket fake. handler(request) -> reply str, or None to hang."""

    def __init__(self, handler=None):
        self.td = tempfile.TemporaryDirectory()
        self.sig = "SIG1"
        self.dir = pathlib.Path(self.td.name) / "hypr" / self.sig
        self.dir.mkdir(parents=True)
        self.handler = handler or (lambda r: FIXTURE.get(r, "unknown request"))
        self.requests = []
        self.event_chunks = []  # bytes written to each event client
        self._stop = threading.Event()
        self.srv = self._listen(".socket.sock")
        self.srv2 = self._listen(".socket2.sock")
        self.threads = [threading.Thread(target=self._serve, daemon=True),
                        threading.Thread(target=self._serve2, daemon=True)]
        for t in self.threads:
            t.start()
        self.env = mock.patch.dict(os.environ, {
            "XDG_RUNTIME_DIR": self.td.name,
            "HYPRLAND_INSTANCE_SIGNATURE": self.sig})

    def _listen(self, name):
        s = socket.socket(socket.AF_UNIX)
        s.bind(str(self.dir / name))
        s.listen(8)
        s.settimeout(0.05)
        return s

    def _serve(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        c.settimeout(2)
        try:
            req = c.recv(65536).decode()
            self.requests.append(req)
            rep = self.handler(req)
            if rep is None:
                self._stop.wait(2)
            else:
                data = rep.encode()
                # force multi-chunk delivery to exercise reassembly
                for i in range(0, len(data), 4096):
                    c.sendall(data[i:i + 4096])
                    time.sleep(0.001)
        except OSError:
            pass
        finally:
            c.close()

    def _serve2(self):
        while not self._stop.is_set():
            try:
                c, _ = self.srv2.accept()
            except (socket.timeout, OSError):
                continue
            for chunk in self.event_chunks:
                c.sendall(chunk)
                time.sleep(0.01)
            c.close()

    def __enter__(self):
        self.env.start()
        hypr.reset()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self.env.stop()
        for s in (self.srv, self.srv2):
            s.close()
        self.td.cleanup()
        hypr.reset()


# --- tiny Lua string-literal tokenizer: proves payloads stay inside one
# literal. Returns (skeleton-with-literals-masked, [decoded literals]).
_ESC = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "'": "'",
        "a": "\a", "b": "\b", "f": "\f", "v": "\v"}


def lua_literals(src: str):
    out, lits, i = [], [], 0
    while i < len(src):
        ch = src[i]
        if ch in "\"'":
            q, i, buf = ch, i + 1, []
            while True:
                if i >= len(src):
                    raise AssertionError("unterminated Lua string: " + src)
                c = src[i]
                if c == q:
                    i += 1
                    break
                if c == "\n":
                    raise AssertionError("raw newline inside literal")
                if c == "\\":
                    n = src[i + 1]
                    if n.isdigit():
                        m = re.match(r"\d{1,3}", src[i + 1:])
                        buf.append(chr(int(m.group())))
                        i += 1 + len(m.group())
                        continue
                    buf.append(_ESC[n])
                    i += 2
                    continue
                buf.append(c)
                i += 1
            lits.append("".join(buf))
            out.append("S")
        else:
            out.append(ch)
            i += 1
    return "".join(out), lits


class TestLuaStr(unittest.TestCase):
    def test_roundtrip_hostile_values(self):
        for v in [INJECT, 'a"b', "back\\slash", "line1\nline2", "cr\rx",
                  "]] ]=] --[[", "nul\x00byte", "tab\tx", "unié☃",
                  "\\\"", "", "a\\"]:
            skel, lits = lua_literals(hypr.lua_str(v))
            self.assertEqual(skel, "S", v)
            self.assertEqual(lits, [v], v)

    def test_single_line(self):
        self.assertNotIn("\n", hypr.lua_str("a\nb\r\nc"))

    @unittest.skipUnless(shutil.which("lua"), "lua not installed")
    def test_real_lua_agrees(self):
        for v in [INJECT, "a\nb\\c\"d", "]]x", "\x00\x01\x7f", "\u00e9"]:
            code = ("local s = " + hypr.lua_str(v) + "\n"
                    "io.write(table.concat({s:byte(1, -1)}, ','))")
            r = subprocess.run(["lua", "-e", code], capture_output=True,
                               text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout,
                             ",".join(str(b) for b in v.encode()), repr(v))


class TestBuilders(unittest.TestCase):
    def assert_contained(self, lua):
        skel, lits = lua_literals(lua)
        self.assertEqual([l for l in lits if "rm -rf" in l and l != INJECT
                          and INJECT not in l], [])
        self.assertNotIn("rm -rf", skel)
        return skel, lits

    def test_focus_injection(self):
        lua = hypr.focus_class(INJECT)
        skel, lits = self.assert_contained(lua)
        self.assertEqual(skel, "hl.dispatch(hl.dsp.focus({window = S}))")
        self.assertEqual(lits, ["class:^" + INJECT])

    def test_launch_injection(self):
        lua = hypr.exec_cmd(INJECT)
        skel, lits = self.assert_contained(lua)
        self.assertEqual(skel, "hl.dispatch(hl.dsp.exec_cmd(S))")
        self.assertEqual(lits, [INJECT])

    def test_launch_argv_is_shell_quoted_single_literal(self):
        lua = hypr.exec_cmd(["foot", "-e", INJECT])
        skel, lits = lua_literals(lua)
        self.assertEqual(skel, "hl.dispatch(hl.dsp.exec_cmd(S))")
        self.assertEqual(len(lits), 1)
        import shlex
        self.assertEqual(shlex.split(lits[0]), ["foot", "-e", INJECT])

    def test_close_injection_and_active(self):
        skel, lits = lua_literals(hypr.close_window(INJECT))
        self.assertEqual(skel, "hl.dispatch(hl.dsp.window.close({window = S}))")
        self.assertEqual(lits, ["class:^" + INJECT])
        self.assertEqual(hypr.close_window(""),
                         "hl.dispatch(hl.dsp.window.close())")

    def test_workspace_typed(self):
        self.assertEqual(hypr.focus_workspace(3),
                         "hl.dispatch(hl.dsp.focus({workspace = 3}))")
        self.assertEqual(hypr.focus_workspace("4"),
                         "hl.dispatch(hl.dsp.focus({workspace = 4}))")
        for bad in ("3}); os.execute('x')", "x", 1.5, None, True, -1):
            with self.assertRaises((ValueError, TypeError)):
                hypr.focus_workspace(bad)

    def test_pointer_move_is_eval_lua_with_ints(self):
        lua = hypr.cursor_move(10, "20")
        self.assertEqual(
            lua, "hl.dispatch(hl.dsp.cursor.move({x = 10, y = 20}))")
        with self.assertRaises((ValueError, TypeError)):
            hypr.cursor_move("1}) os.exit() --", 2)

    def test_bind_injection(self):
        lua = hypr.bind_lua("wisp:h1", "SUPER + X", INJECT)
        skel, lits = lua_literals(lua)
        self.assertNotIn("rm -rf", skel)
        self.assertIn(INJECT, lits)

    def test_no_dispatch_syntax_in_any_builder(self):
        outs = [hypr.focus_class("a"), hypr.exec_cmd("x"),
                hypr.close_window(""), hypr.close_window("a"),
                hypr.focus_workspace(1), hypr.cursor_move(1, 2),
                hypr.bind_lua("wisp:1", "SUPER + X", "x"),
                hypr.unbind_lua("wisp:1"), hypr.clear_stale_lua()]
        for o in outs:
            self.assertNotRegex(o, r"\bdispatch ")  # legacy "dispatch exec"
        for fn, args in [(platform.focus_cmds, ("a",)),
                         (platform.close_cmds, ("a",)),
                         (platform.workspace_cmds, (2,)),
                         (platform.launch_exec_cmds, ("foot",))]:
            with mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                              "WISP_DESKTOP": "hyprland"}):
                cmds = fn(*args)
            flat = json.dumps([list(c) if isinstance(c, (list, tuple)) else
                               [str(c)] for c in cmds])
            self.assertNotIn("hyprctl", flat)
            self.assertNotIn("dispatch ", flat.replace("hl.dispatch(", ""))


class TestTransport(unittest.TestCase):
    def test_query_parses_json(self):
        with FakeHypr() as f:
            w = hypr.query("activewindow")
        self.assertEqual(w["class"], "foot")
        self.assertEqual(f.requests, ["j/activewindow"])

    def test_large_chunked_reply_reassembled(self):
        big = json.dumps([{"i": i, "pad": "x" * 50} for i in range(2000)])
        with FakeHypr(lambda r: big) as f:
            got = hypr.query("clients")
        self.assertEqual(len(got), 2000)

    def test_eval_framing(self):
        with FakeHypr() as f:
            self.assertEqual(hypr.eval_lua("return 1"), "ok")
        self.assertEqual(f.requests, ["eval return 1"])

    def test_eval_error_reply_raises(self):
        with FakeHypr() as f:
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.eval_lua("hl.nonexistent()")
        self.assertEqual(cm.exception.code, "eval_failed")

    def test_eval_warning_is_returned_not_raised(self):
        with FakeHypr(lambda r: "warning: hl.focus: window not found") as f:
            self.assertTrue(
                hypr.eval_lua("x").startswith("warning:"))

    def test_unknown_query_raises_protocol(self):
        with FakeHypr() as f:
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.query("nonsense")
        self.assertEqual(cm.exception.code, "protocol")

    def test_timeout_300ms(self):
        with FakeHypr(lambda r: None) as f:
            t = time.monotonic()
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.query("activewindow")
            took = time.monotonic() - t
        self.assertEqual(cm.exception.code, "timeout")
        self.assertGreaterEqual(took, 0.28)
        self.assertLess(took, 0.6)

    def test_no_socket_is_unavailable(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": td,
                                          "HYPRLAND_INSTANCE_SIGNATURE": "none"}):
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.query("activewindow")
        self.assertEqual(cm.exception.code, "unavailable")

    def test_stale_socket_file_is_unavailable(self):
        with FakeHypr() as f:
            f.srv.close()  # file remains, nobody listening
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.query("activewindow")
        self.assertEqual(cm.exception.code, "unavailable")

    def test_instance_discovery_without_signature(self):
        with FakeHypr() as f:
            env = {k: v for k, v in os.environ.items()
                   if k != "HYPRLAND_INSTANCE_SIGNATURE"}
            with mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(hypr.query("activewindow")["class"], "foot")

    def test_no_subprocess_for_queries(self):
        with FakeHypr() as f, \
             mock.patch("subprocess.run") as run, \
             mock.patch("subprocess.Popen") as popen:
            hypr.query("activewindow")
            hypr.eval_lua("return 1")
        run.assert_not_called()
        popen.assert_not_called()


class TestProbeAndTools(unittest.TestCase):
    def test_probe_ok(self):
        with FakeHypr() as f:
            self.assertTrue(hypr.probe())
            self.assertEqual(hypr.health(), {"ok": True, "code": None})
        self.assertIn("eval return 1", f.requests)

    def test_failed_probe_publishes_hypr_unavailable(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": td,
                                          "HYPRLAND_INSTANCE_SIGNATURE": "x"}):
            hypr.reset()
            self.assertFalse(hypr.probe())
            self.assertEqual(hypr.health(),
                             {"ok": False, "code": "hypr_unavailable"})

    def test_probe_fails_when_eval_rejected(self):
        h = lambda r: "error: nope" if r.startswith("eval") else "[]"
        with FakeHypr(h) as f:
            self.assertFalse(hypr.probe())

    def test_focus_tool_fails_without_spawning_hyprctl(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": td,
                                          "HYPRLAND_INSTANCE_SIGNATURE": "x",
                                          "WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch("subprocess.run") as run, \
             mock.patch("subprocess.Popen") as popen:
            hypr.reset()
            out = desktop.focus("firefox")
        self.assertTrue(out.startswith("ERROR tool_failed"), out)
        self.assertIn("hypr_unavailable", out)
        run.assert_not_called()
        popen.assert_not_called()

    def test_focus_tool_sends_eval_over_socket(self):
        with FakeHypr(ok_handler) as f, \
             mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch("subprocess.run") as run:
            out = desktop.focus("firefox")
        self.assertEqual(out, "FOCUSED firefox")
        evals = [r for r in f.requests if r.startswith("eval ")]
        self.assertEqual(len(evals), 2)  # probe + focus
        self.assertIn('class:^firefox', evals[-1])
        run.assert_not_called()

    def test_focus_no_match_warning_is_skip(self):
        h = lambda r: ("warning: hl.focus: window not found"
                       if "focus" in r else ok_handler(r))
        with FakeHypr(h) as f, \
             mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}):
            out = desktop.focus("nope")
        self.assertTrue(out.startswith("SKIP"), out)

    def test_clients_and_active_window_and_monitors_via_socket(self):
        h = lambda r: {"j/clients": '[{"class": "a"}]'}.get(
            r, FIXTURE.get(r, "ok"))
        with FakeHypr(h) as f, \
             mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch("subprocess.run") as run:
            self.assertEqual(desktop.clients(), [{"class": "a"}])
            self.assertEqual(platform.active_window(),
                             {"class": "foot", "title": "~"})
            self.assertEqual(platform.monitors()[0]["name"], "eDP-1")
        run.assert_not_called()

    def test_pointer_move_uses_eval(self):
        from wisp.tools import system
        cfg = {"pointer": {"mode": "drive", "backend": "auto"}}
        with FakeHypr(ok_handler) as f, \
             mock.patch.dict(os.environ, {"WISP_OS": "linux",
                                          "WISP_DESKTOP": "hyprland"}), \
             mock.patch.object(platform, "pointer_backend",
                               return_value="ydotool"), \
             mock.patch("subprocess.run") as run:
            out = system.move("5,6@logical", cfg)
        self.assertEqual(out, "MOVED(5,6)")
        self.assertIn("eval hl.dispatch(hl.dsp.cursor.move({x = 5, y = 6}))",
                      f.requests)
        run.assert_not_called()


class TestEvents(unittest.TestCase):
    def test_parse_event(self):
        self.assertEqual(hypr.parse_event("workspace>>2"), ("workspace", "2"))
        self.assertEqual(hypr.parse_event("activewindow>>foot,~"),
                         ("activewindow", "foot,~"))
        # data may itself contain >>
        self.assertEqual(hypr.parse_event("custom>>a>>b"), ("custom", "a>>b"))
        self.assertEqual(hypr.parse_event("submap>>"), ("submap", ""))
        self.assertIsNone(hypr.parse_event(""))
        self.assertIsNone(hypr.parse_event("garbage with no separator"))

    def test_stream_handles_split_and_batched_chunks(self):
        with FakeHypr() as f:
            f.event_chunks = [b"workspace>>1\nactivewi", b"ndow>>foot,~\nfocus",
                              b"edmon>>eDP-1,1\n",
                              "title>>café\n".encode(),
                              b"\xff\xfebad>>x\n"]
            got = list(hypr.events())
        self.assertEqual(got[:4], [("workspace", "1"),
                                   ("activewindow", "foot,~"),
                                   ("focusedmon", "eDP-1,1"),
                                   ("title", "café")])
        self.assertEqual(got[4][1], "x")  # invalid utf-8 tolerated

    def test_stream_stop_event(self):
        stop = threading.Event()
        with FakeHypr() as f:
            f.event_chunks = [b"workspace>>1\n"]
            it = hypr.events(stop=stop, poll=0.02)
            self.assertEqual(next(it), ("workspace", "1"))
            stop.set()
            self.assertEqual(list(it), [])


class TestBindRegistry(unittest.TestCase):
    def binds_handler(self, extra=None):
        def h(r):
            if r == "j/binds":
                return FIXTURE["j/binds"]
            return "ok"
        return h

    def evals(self, f):
        return [r[5:] for r in f.requests if r.startswith("eval ")
                and r != "eval return 1"]

    def test_parse_chord(self):
        self.assertEqual(hypr.parse_chord("super+shift+x"),
                         (65, "X", "SUPER + SHIFT + X"))
        self.assertEqual(hypr.parse_chord("CTRL + ALT + F5")[0], 12)
        self.assertEqual(hypr.parse_chord("SUPER + Escape")[1], "ESCAPE")

    def test_chord_needs_modifier(self):
        for bad in ("X", "F5", "", "ESCAPE"):
            with self.assertRaises(ValueError) as cm:
                hypr.parse_chord(bad)
            self.assertIn("modifier", str(cm.exception))

    def test_chord_rejects_garbage(self):
        for bad in ('SUPER + "); os.exit() --', "SUPER + A B",
                    "SUPER + SHIFT", "SUPER + X) + Y", "SUPER + \n X"):
            with self.assertRaises(ValueError):
                hypr.parse_chord(bad)

    def test_bind_then_unbind_one_create_one_remove(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register"):
            hypr.reset_binds()
            h = hypr.bind("SUPER + CTRL + F9", "wisp-trigger start")
            self.assertTrue(h.startswith("wisp:"))
            hypr.unbind(h)
            hypr.unbind(h)  # idempotent: no second remove
        ev = self.evals(f)
        creates = [e for e in ev if "hl.bind(" in e]
        removes = [e for e in ev if "hl.unbind(" in e]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(removes), 1)
        self.assertIn(h, creates[0])
        self.assertIn(h, removes[0])
        self.assertIn("SUPER + CTRL + F9", creates[0])

    def test_unbind_lua_only_touches_registered_chord(self):
        lua = hypr.unbind_lua("wisp:abc")
        # chord is looked up in the Wisp table, never taken from the caller
        self.assertNotIn("SUPER", lua)
        self.assertIn("wisp_binds", lua)

    def test_clash_detected_against_existing_binds(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register"):
            hypr.reset_binds()
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.bind("SUPER + D", "x")  # SUPER+D exists (modmask 64)
            self.assertEqual(cm.exception.code, "bind_clash")
            with self.assertRaises(hypr.HyprError):
                hypr.bind("super + d", "x")  # case-insensitive
        self.assertEqual([e for e in self.evals(f) if "hl.bind(" in e], [])

    def test_non_clash_other_mods_and_other_submap(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register"):
            hypr.reset_binds()
            hypr.bind("SUPER + SHIFT + D", "x")   # different mods
            hypr.bind("SUPER + CTRL + H", "x")    # 'h' bind is in a submap
        self.assertEqual(len([e for e in self.evals(f) if "hl.bind(" in e]), 2)

    def test_wisp_own_second_bind_same_chord_is_clash(self):
        state = {"binds": json.loads(FIXTURE["j/binds"])}

        def h(r):
            if r == "j/binds":
                return json.dumps(state["binds"])
            if "hl.bind(" in r:
                state["binds"].append({"modmask": 68, "submap": "",
                                       "key": "F9", "description": "wisp:1"})
            return "ok"
        with FakeHypr(h) as f, mock.patch("atexit.register"):
            hypr.reset_binds()
            hypr.bind("SUPER + CTRL + F9", "x")
            with self.assertRaises(hypr.HyprError) as cm:
                hypr.bind("SUPER + CTRL + F9", "y")
        self.assertEqual(cm.exception.code, "bind_clash")

    def test_bind_injection_in_action(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register"):
            hypr.reset_binds()
            hypr.bind("SUPER + CTRL + F8", INJECT)
        create = [e for e in self.evals(f) if "hl.bind(" in e][0]
        skel, lits = lua_literals(create)
        self.assertNotIn("rm -rf", skel)
        self.assertIn(INJECT, lits)

    def test_clear_stale_removes_only_wisp_prefixed(self):
        lua = hypr.clear_stale_lua()
        self.assertIn("wisp_binds", lua)
        self.assertIn('"wisp:"', lua)
        with FakeHypr(self.binds_handler()) as f:
            hypr.clear_stale()
        self.assertEqual(len(self.evals(f)), 1)

    @unittest.skipUnless(shutil.which("lua"), "lua not installed")
    def test_registry_semantics_in_real_lua(self):
        """Run the emitted Lua against a stub `hl`: foreign chords survive
        clear_stale, Wisp chords go, unbind(handle) removes only its own."""
        stub = ("calls = {}\nhl = {bind = function(k) "
                "calls[#calls+1] = 'bind ' .. k end, unbind = function(k) "
                "calls[#calls+1] = 'unbind ' .. k end, dsp = {exec_cmd = "
                "function(c) return c end}}\n")
        script = (stub
                  + hypr.bind_lua("wisp:a", "SUPER + CTRL + F1", "x") + "\n"
                  + hypr.bind_lua("wisp:b", "SUPER + CTRL + F2", "y") + "\n"
                  + "_G.wisp_binds['userthing'] = 'SUPER + Q'\n"
                  + hypr.unbind_lua("wisp:a") + "\n"
                  + hypr.clear_stale_lua() + "\n"
                  + "print(table.concat(calls, '|'))\n"
                  + "print(_G.wisp_binds['userthing'])")
        r = subprocess.run(["lua", "-e", script], capture_output=True,
                           text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.splitlines()
        self.assertEqual(out[0],
                         "bind SUPER + CTRL + F1|bind SUPER + CTRL + F2|"
                         "unbind SUPER + CTRL + F1|unbind SUPER + CTRL + F2")
        self.assertEqual(out[1], "SUPER + Q")

    def test_removed_on_exit(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register") as reg:
            hypr.reset_binds()
            h1 = hypr.bind("SUPER + CTRL + F6", "a")
            h2 = hypr.bind("SUPER + CTRL + F7", "b")
            reg.assert_called_once_with(hypr.shutdown)  # registered once
            hypr.shutdown()
            hypr.shutdown()
        removes = [e for e in self.evals(f) if "hl.unbind(" in e]
        self.assertEqual(len(removes), 2)
        self.assertEqual(hypr.active_binds(), {})

    def test_shutdown_survives_dead_hyprland(self):
        with FakeHypr(self.binds_handler()) as f, \
             mock.patch("atexit.register"):
            hypr.reset_binds()
            hypr.bind("SUPER + CTRL + F6", "a")
            f.handler = lambda r: None  # compositor hangs
            t = time.monotonic()
            hypr.shutdown()  # must not raise
            self.assertLess(time.monotonic() - t, 1.0)


if __name__ == "__main__":
    unittest.main()
