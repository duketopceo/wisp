"""Control-channel capability lane (U3, KTD3).

A fake JSON-lines server on a loopback TCP port stands in for
FilmCraft's `--control 9876` channel — offline, no real app. The suite
covers the client bounds (connect/read timeouts, malformed lines never
crash), the app->endpoint registry (built-in FilmCraft + `control.<app>`
config), element->rect resolution validated against compositor-derived
window bounds (spoofed rects rejected), the grounding provider, and the
verify rung's landed/missed/abstain votes.
"""
import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import control, grounding as g  # noqa: E402
from wisp import trace as _trace  # noqa: E402
import wisp.verify as verify  # noqa: E402


CLOSE = "close"          # handler token: drop the connection, no reply
SILENT = "silent"        # handler token: hold the request unanswered


class CtrlServer:
    """Loopback JSON-lines server. `handler(method, params, conn_no)`
    -> a reply dict sent as one JSON line, or a list mixing reply dicts
    and raw bytes sent in order. CLOSE/SILENT steer the connection."""

    def __init__(self, handler):
        self.handler = handler
        self.conns = 0
        self.requests = []
        self._accepted = []
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(8)
        self.port = self._srv.getsockname()[1]
        self._t = threading.Thread(target=self._accept, daemon=True)
        self._t.start()

    def _accept(self):
        try:
            while True:
                conn, _ = self._srv.accept()
                self._accepted.append(conn)
                self.conns += 1
                threading.Thread(target=self._serve,
                                 args=(conn, self.conns),
                                 daemon=True).start()
        except OSError:
            return

    def _serve(self, conn, conn_no):
        try:
            f = conn.makefile("rb")
            while True:
                line = f.readline(8 * 1024 * 1024)
                if not line:
                    return
                if not line.strip():
                    continue
                try:
                    req = json.loads(line)
                except ValueError:
                    conn.sendall(b'{"ok":false,"error":"bad json"}\n')
                    return
                self.requests.append((req.get("method"),
                                      req.get("params") or {}))
                r = self.handler(req.get("method", ""),
                                 req.get("params") or {}, conn_no)
                if r is CLOSE:
                    return
                if r is SILENT:
                    continue
                for part in (r if isinstance(r, list) else [r]):
                    if isinstance(part, bytes):
                        conn.sendall(part)
                    elif isinstance(part, str):
                        conn.sendall(part.encode())
                    else:
                        # real replies echo the request id — anything
                        # needing a wrong/missing id goes out as bytes
                        d = dict(part)
                        d.setdefault("id", req.get("id"))
                        conn.sendall(json.dumps(d).encode() + b"\n")
        except OSError:
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def close(self):
        # shutdown() first: a thread blocked in accept() keeps a closed
        # listener serving on Linux — refuse new conns, then close
        try:
            self._srv.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._srv.close()
        except OSError:
            pass
        for c in self._accepted:
            try:
                c.close()
            except OSError:
                pass


def ok(result):
    return {"ok": True, "result": result}


def dead_port() -> int:
    """A port nothing listens on (bound-then-closed plain socket —
    never under a live accept thread)."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


ELEMENTS = [
    {"id": "project.item.4", "label": "Audio bin",
     "rect": [10, 20, 30, 40]},
    {"id": "tools.Razor", "label": "Razor",
     "rect": [50, 60, 20, 20]},
]
INSPECT = {"window": [1280, 720], "pixelsPerPoint": 1.0, "fps": 60.1,
           "ui": {"tool": "select", "workspace": "Editing"},
           "playback": {"playing": False, "audioClock": 0.0},
           "selection": [], "dialog": None, "elements": 2}

# the focused FilmCraft window, compositor-derived: hypr `clients`
# carries at/size; `activewindow` carries identity + a bounds copy
WIN_BOUNDS = (100.0, 50.0, 800.0, 600.0)
AW = {"class": "ai.storyteller.filmcraft", "title": "FilmCraft — seq",
      "address": "0xabc", "pid": 4242,
      "at": [100, 50], "size": [800, 600]}
CLIENTS = [{"address": "0xabc", "class": "ai.storyteller.filmcraft",
            "initialClass": "ai.storyteller.filmcraft",
            "title": "FilmCraft — seq", "pid": 4242, "mapped": True,
            "at": [100, 50], "size": [800, 600],
            "workspace": {"id": 1, "name": "1"}}]


def _win():
    with mock.patch.object(control, "_clients", return_value=CLIENTS), \
            mock.patch.object(control, "_activewindow",
                              return_value=AW):
        return control.focused_window()


class ClientTransport(unittest.TestCase):
    def test_roundtrip(self):
        srv = CtrlServer(lambda m, p, c: ok(ELEMENTS))
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            els = c.elements()
        self.assertEqual([e["id"] for e in els],
                         ["project.item.4", "tools.Razor"])
        self.assertEqual(els[0]["rect"], (10.0, 20.0, 30.0, 40.0))
        self.assertEqual(srv.requests[0][0], "ui.elements")

    def test_malformed_reply_lines_are_skipped_and_counted(self):
        def h(m, p, c):
            return [b"garbage not json\n",
                    b'{"id": 99, "ok": true, "result": {}}\n',
                    ok(ELEMENTS)]
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            els = c.elements()
            self.assertEqual(len(els), 2)
            self.assertEqual(c.malformed, 2)

    def test_read_timeout_then_timeout_again(self):
        srv = CtrlServer(lambda m, p, c: SILENT)
        self.addCleanup(srv.close)
        c = control.ControlClient("127.0.0.1", srv.port, read_s=0.2)
        with self.assertRaises(control.ControlError) as cm:
            c.call("ui.elements")
        self.assertEqual(cm.exception.code, "timeout")
        # reconnect-once: exactly two connections attempted
        self.assertEqual(srv.conns, 2)

    def test_connect_refused_is_down(self):
        c = control.ControlClient("127.0.0.1", dead_port(),
                                  connect_s=0.1)
        with self.assertRaises(control.ControlError) as cm:
            c.call("ui.inspect")
        self.assertEqual(cm.exception.code, "down")

    def test_server_close_reconnects_once_then_succeeds(self):
        def h(m, p, c):
            return CLOSE if c == 1 else ok({"window": [1, 2]})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            out = c.inspect()
        self.assertEqual(out["window"], [1, 2])
        self.assertEqual(srv.conns, 2)

    def test_always_closing_fails_after_one_retry(self):
        srv = CtrlServer(lambda m, p, c: CLOSE)
        self.addCleanup(srv.close)
        c = control.ControlClient("127.0.0.1", srv.port)
        with self.assertRaises(control.ControlError) as cm:
            c.call("ui.inspect")
        self.assertEqual(cm.exception.code, "down")
        self.assertEqual(srv.conns, 2)

    def test_ok_false_is_refused_never_retried(self):
        srv = CtrlServer(
            lambda m, p, c: {"id": 1, "ok": False,
                             "error": "no element `x`"})
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            with self.assertRaises(control.ControlError) as cm:
                c.elements()
        self.assertEqual(cm.exception.code, "refused")
        self.assertIn("no element", str(cm.exception))
        self.assertEqual(srv.conns, 1)

    def test_garbage_forever_is_protocol_error(self):
        srv = CtrlServer(lambda m, p, c: [b"junk!\n"] * 6)
        self.addCleanup(srv.close)
        c = control.ControlClient("127.0.0.1", srv.port, max_skip=3)
        with self.assertRaises(control.ControlError) as cm:
            c.call("ui.elements")
        self.assertEqual(cm.exception.code, "protocol")
        self.assertGreaterEqual(c.malformed, 4)

    def test_oversized_reply_line_counts_malformed(self):
        big = (b"x" * 5000) + b"\n"

        def h(m, p, c):
            return [big, ok(ELEMENTS)]
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port,
                                   max_line=4096) as c:
            els = c.elements()
        self.assertEqual(len(els), 2)
        self.assertEqual(c.malformed, 1)

    def test_non_loopback_host_refused(self):
        for host in ("10.0.0.5", "0.0.0.0", "example.com"):
            with self.assertRaises(ValueError):
                control.ControlClient(host, 9876)

    def test_bad_port_and_method_refused(self):
        with self.assertRaises(ValueError):
            control.ControlClient("127.0.0.1", 70000)
        with self.assertRaises(ValueError):
            control.ControlClient("127.0.0.1", 0)
        c = control.ControlClient("127.0.0.1", 1)
        with self.assertRaises(ValueError):
            c.call("'; DROP TABLE")
        with self.assertRaises(ValueError):
            c.call("")


class Registry(unittest.TestCase):
    def test_filmcraft_builtin_matches_class_and_title(self):
        reg = control.AppControlRegistry({})
        ep = reg.match({"class": "ai.storyteller.filmcraft",
                        "title": "FilmCraft"})
        self.assertIsNotNone(ep)
        self.assertEqual((ep.app, ep.host, ep.port),
                         ("filmcraft", "127.0.0.1", 9876))
        # title alone also hits
        self.assertIsNotNone(
            reg.match({"class": "", "title": "FilmCraft — x"}))
        self.assertIsNone(reg.match({"class": "foot", "title": "shell"}))
        self.assertIsNone(reg.match(None))

    def test_config_scalar_host_port(self):
        reg = control.AppControlRegistry(
            {"control": {"myapp": "127.0.0.1:5555"}})
        ep = reg.match({"class": "MyApp", "title": ""})
        self.assertEqual((ep.host, ep.port), ("127.0.0.1", 5555))

    def test_config_table_form(self):
        reg = control.AppControlRegistry(
            {"control.other": {"port": "6666", "host": "127.0.0.1",
                               "match": "otherapp,Other App"}})
        ep = reg.match({"class": "OtherApp"})
        self.assertEqual((ep.app, ep.port), ("other", 6666))
        ep = reg.match({"class": "", "title": "Other App — doc"})
        self.assertEqual(ep.port, 6666)

    def test_port_only_and_blank_host_forms(self):
        reg = control.AppControlRegistry(
            {"control": {"a": "9999", "b": ":8888",
                         "c": "localhost:7777"}})
        self.assertEqual(reg.match({"class": "a"}).port, 9999)
        self.assertEqual(reg.match({"class": "b"}).port, 8888)
        self.assertEqual(reg.match({"class": "c"}).host, "localhost")

    def test_non_loopback_and_bad_port_entries_dropped(self):
        reg = control.AppControlRegistry(
            {"control": {"evil": "10.0.0.5:1234",
                         "badport": "127.0.0.1:notaport",
                         "toobig": "127.0.0.1:70000"}})
        self.assertIsNone(reg.match({"class": "evil"}))
        self.assertIsNone(reg.match({"class": "badport"}))
        self.assertIsNone(reg.match({"class": "toobig"}))

    def test_config_overrides_builtin_port(self):
        reg = control.AppControlRegistry(
            {"control": {"filmcraft": "127.0.0.1:9999"}})
        ep = reg.match({"class": "ai.storyteller.filmcraft"})
        self.assertEqual(ep.port, 9999)

    def test_settings_timeouts_bounded(self):
        st = control.settings({"control": {"connect_timeout_s": "9",
                                           "read_timeout_s": "120"}})
        self.assertEqual(st["connect_s"], 9.0)
        self.assertEqual(st["read_s"], 60.0)      # clamped
        st = control.settings({"control": {"connect_timeout_s": "zz"}})
        self.assertEqual(st["connect_s"], control.CONNECT_S)


class WindowAndRects(unittest.TestCase):
    def test_focused_window_bounds_from_clients(self):
        win = _win()
        self.assertEqual(win["class"], "ai.storyteller.filmcraft")
        self.assertEqual(win["bounds"], WIN_BOUNDS)

    def test_focused_window_falls_back_to_activewindow_size(self):
        with mock.patch.object(control, "_clients", return_value=[]), \
                mock.patch.object(control, "_activewindow",
                                  return_value=AW):
            win = control.focused_window()
        self.assertEqual(win["bounds"], WIN_BOUNDS)

    def test_focused_window_cua_list_windows_fallback(self):
        cua = SimpleNamespace(list_windows=lambda timeout=0.8: {
            "windows": [{"pid": 4242, "window_id": 5,
                         "frame": {"x": 100, "y": 50, "width": 800,
                                   "height": 600}}]})
        aw = dict(AW)
        del aw["at"], aw["size"]
        with mock.patch.object(control, "_clients",
                               side_effect=OSError("down")), \
                mock.patch.object(control, "_activewindow",
                                  return_value=aw):
            win = control.focused_window(cua=cua)
        self.assertEqual(win["bounds"], WIN_BOUNDS)

    def test_no_focused_window(self):
        with mock.patch.object(control, "_clients", return_value=[]), \
                mock.patch.object(control, "_activewindow",
                                  return_value={}):
            self.assertIsNone(control.focused_window())

    def test_window_local_rect_resolves(self):
        win = {"bounds": WIN_BOUNDS}
        # element at window-local (10,20,30,40) -> global (110,70,30,40)
        g = control.resolve_rect([10, 20, 30, 40], win)
        self.assertEqual(g, (110.0, 70.0, 30.0, 40.0))

    def test_already_global_rect_resolves(self):
        # a rect inside the window ONLY read as global: cx must sit
        # inside [bounds.x, bounds.x+w) yet push the local read past
        # the far edge -> rect.x+cx_local > w. Documented space (local)
        # is tried first, so this proves the fallback interpretation.
        win = {"bounds": WIN_BOUNDS}          # (100,50,800,600)
        # cx 850 inside [100,900]; local read pushes it to 950 > 908
        g = control.resolve_rect([835, 50, 30, 30], win)
        self.assertEqual(g, (835.0, 50.0, 30.0, 30.0))
        # when BOTH reads land inside, the documented local space wins
        g = control.resolve_rect([200, 100, 30, 40], win)
        self.assertEqual(g, (300.0, 150.0, 30.0, 40.0))

    def test_spoofed_rect_outside_window_rejected(self):
        win = {"bounds": WIN_BOUNDS}
        # (5000,5000) is inside no interpretation of an 800x600 window
        # at (100,50): window-local -> (5100,5050), global -> center
        # (5005,5005) — both outside
        self.assertIsNone(
            control.resolve_rect([5000, 5000, 10, 10], win))
        # a huge rect whose center lands beyond the window edge
        self.assertIsNone(
            control.resolve_rect([-5000, -5000, 10, 10], win))

    def test_pixels_per_point_scale_interpretation(self):
        # HiDPI: egui points at ppt=2 ~ physical px on a scale-1
        # monitor — a channel rect of (1500,1000) is outside an
        # 800x600 logical window in BOTH base spaces, and lands inside
        # only under the pt->logical factor (scale/ppt = 0.5)
        win = {"bounds": (0.0, 0.0, 800.0, 600.0)}
        mons = [{"x": 0, "y": 0, "width": 800, "height": 600,
                 "scale": 1.0}]
        g = control.resolve_rect([1500, 1000, 40, 40], win, ppt=2.0,
                                 mons=mons)
        self.assertEqual(g, (750.0, 500.0, 20.0, 20.0))

    def test_degenerate_and_no_bounds_rejected(self):
        win = {"bounds": WIN_BOUNDS}
        self.assertIsNone(control.resolve_rect([0, 0, 0, 10], win))
        self.assertIsNone(control.resolve_rect([0, 0, 10], win))
        self.assertIsNone(
            control.resolve_rect([float("nan"), 0, 10, 10], win))
        self.assertIsNone(control.resolve_rect([10, 10, 10, 10],
                                               {"bounds": None}))
        self.assertIsNone(control.resolve_rect([10, 10, 10, 10], {}))


class Provider(unittest.TestCase):
    """grounding._control: registry match on the focused app, elements
    fetch, rect-vs-window validation, then a Candidate on the standard
    global frame — the cua dispatch path consumes it unchanged."""

    def ctx(self, target="audio bin", timeout=1.0, cfg=None):
        cfg = cfg or {}
        return SimpleNamespace(target=target, region_hint="", shot=None,
                               cfg=cfg, st=g.settings(cfg),
                               timeout=timeout, cua=None)

    def _patch_win(self):
        return (mock.patch.object(control, "_clients",
                                  return_value=CLIENTS),
                mock.patch.object(control, "_activewindow",
                                  return_value=AW))

    def test_name_grounds_via_control(self):
        srv = CtrlServer(
            lambda m, p, c: ok(ELEMENTS if m == "ui.elements"
                               else INSPECT))
        self.addCleanup(srv.close)
        control._BEFORE.clear()
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        p1, p2 = self._patch_win()
        with p1, p2, mock.patch.object(_trace, "current",
                                       return_value="t-ctl1"):
            c = g._control(self.ctx(cfg=cfg))
        self.assertIsNotNone(c)
        self.assertEqual(c.source, "control")
        # window-local rect (10,20,30,40) on a window at (100,50)
        self.assertEqual((c.x, c.y), (125.0, 90.0))
        self.assertEqual(c.frame, "global")
        self.assertEqual(c.rect, (110.0, 70.0, 30.0, 40.0))
        self.assertEqual(c.confidence, 1.0)
        # the pre-dispatch snapshot landed for the verify rung
        self.assertIn(("t-ctl1", "filmcraft"), control._BEFORE)
        self.assertEqual(
            control._BEFORE[("t-ctl1", "filmcraft")]["hit"]["id"],
            "project.item.4")

    def test_no_match_returns_none_but_still_snapshots(self):
        srv = CtrlServer(
            lambda m, p, c: ok(ELEMENTS if m == "ui.elements"
                               else INSPECT))
        self.addCleanup(srv.close)
        control._BEFORE.clear()
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        p1, p2 = self._patch_win()
        with p1, p2, mock.patch.object(_trace, "current",
                                       return_value="t-ctl2"):
            c = g._control(self.ctx(target="no such widget", cfg=cfg))
        self.assertIsNone(c)
        self.assertIn(("t-ctl2", "filmcraft"), control._BEFORE)
        self.assertIsNone(
            control._BEFORE[("t-ctl2", "filmcraft")]["hit"])

    def test_no_channel_for_app_skips(self):
        aw = {"class": "foot", "title": "shell", "address": "0x9"}
        with mock.patch.object(control, "_clients",
                               return_value=[]), \
                mock.patch.object(control, "_activewindow",
                                  return_value=aw):
            with self.assertRaises(g.Skip):
                g._control(self.ctx())

    def test_channel_down_skips(self):
        cfg = {"control": {"filmcraft": f"127.0.0.1:{dead_port()}",
                           "connect_timeout_s": "0.1"}}
        p1, p2 = self._patch_win()
        with p1, p2:
            with self.assertRaises(g.Skip):
                g._control(self.ctx(cfg=cfg))

    def test_stalled_channel_is_provider_down(self):
        srv = CtrlServer(lambda m, p, c: SILENT)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}",
                           "read_timeout_s": "0.3",
                           "connect_timeout_s": "0.2"}}
        p1, p2 = self._patch_win()
        with p1, p2:
            with self.assertRaises(g.ProviderDown):
                g._control(self.ctx(timeout=0.3, cfg=cfg))

    def test_spoofed_rect_never_grounds(self):
        forged = [{"id": "evil.btn", "label": "Audio bin",
                   "rect": [5000, 5000, 10, 10]}]
        srv = CtrlServer(
            lambda m, p, c: ok(forged if m == "ui.elements"
                               else INSPECT))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        p1, p2 = self._patch_win()
        with p1, p2, mock.patch.object(_trace, "current",
                                       return_value="t-spf"):
            c = g._control(self.ctx(cfg=cfg))
        self.assertIsNone(c)

    def test_ground_target_end_to_end(self):
        srv = CtrlServer(
            lambda m, p, c: ok(ELEMENTS if m == "ui.elements"
                               else INSPECT))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"},
               "ground": {"providers": "control"}}
        p1, p2 = self._patch_win()
        with p1, p2, mock.patch.object(_trace, "current",
                                       return_value="t-e2e"):
            t = g.ground_target(
                "razor", cfg, capture=lambda: g.Shot(
                    __import__("base64").b64encode(b"\x89PNG\r\n\x1a\n")
                    .decode(), 100, 100),
                monitors=[{"x": 0, "y": 0, "width": 800, "height": 600,
                           "scale": 1.0}])
        self.assertEqual(t.source, "control")
        # tools.Razor rect (50,60,20,20) -> global (150,110) center
        self.assertEqual((t.x, t.y), (160, 120))
        self.assertEqual(t.rect, (150.0, 110.0, 20.0, 20.0))


class Rung(unittest.TestCase):
    """verify_rung: before-snapshot stashed at aim time vs a fresh
    after-read; votes landed/missed and abstains cleanly on every
    unavailable shape. Never sole-sources (corroboration is the
    ladder's)."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        control._BEFORE.clear()

    def _ctx(self, turn="t-run", cfg=None):
        d = pathlib.Path(self.td.name) / turn / "turn-00001"
        d.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(turn_dir=d, cfg=cfg or {}, claim={},
                               step={"tool": "click"})

    def _rung(self, ctx):
        with mock.patch.object(control, "_clients",
                               return_value=CLIENTS), \
                mock.patch.object(control, "_activewindow",
                                  return_value=AW):
            return control.verify_rung(ctx)

    def test_state_diff_votes_landed(self):
        state = {"n": 0}

        def h(m, p, c):
            if m == "ui.elements":
                return ok(ELEMENTS)
            out = dict(INSPECT)
            if state["n"]:
                out["ui"] = {"tool": "razor", "workspace": "Editing"}
            return ok(out)
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        state["n"] = 1                       # the click changed the tool
        v = self._rung(ctx)
        self.assertEqual(v["vote"], "landed")
        self.assertIn("tool", v["detail"])
        # evidence artifacts persisted into the recorded action dir
        self.assertTrue(
            (ctx.turn_dir / "control_before.json").exists())
        after = json.loads(
            (ctx.turn_dir / "control_after.json").read_text())
        self.assertEqual(after["inspect"]["ui"]["tool"], "razor")

    def test_identical_state_votes_missed(self):
        srv = CtrlServer(
            lambda m, p, c: ok(ELEMENTS if m == "ui.elements"
                               else INSPECT))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        v = self._rung(ctx)
        self.assertEqual(v["vote"], "missed")

    def test_volatile_jitter_alone_is_not_a_change(self):
        def h(m, p, c):
            if m == "ui.elements":
                return ok(ELEMENTS)
            out = dict(INSPECT)
            out["fps"] = 61.7                # jitter, not an effect
            out["playback"] = {"playing": False, "audioClock": 0.4}
            return ok(out)
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        self.assertEqual(self._rung(ctx)["vote"], "missed")

    def test_new_elements_vote_landed(self):
        def h(m, p, c):
            if m == "ui.elements":
                return ok(ELEMENTS + [{"id": "dialog.ok",
                                       "label": "OK",
                                       "rect": [1, 2, 3, 4]}])
            return ok(INSPECT)
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        self.assertEqual(self._rung(ctx)["vote"], "landed")

    def test_no_channel_abstains(self):
        ctx = self._ctx()
        aw = {"class": "foot", "title": "x"}
        with mock.patch.object(control, "_clients", return_value=[]), \
                mock.patch.object(control, "_activewindow",
                                  return_value=aw):
            v = control.verify_rung(ctx)
        self.assertEqual(v["vote"], "abstain")

    def test_no_pending_snapshot_abstains(self):
        srv = CtrlServer(lambda m, p, c: ok(INSPECT))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        v = self._rung(self._ctx(cfg=cfg))
        self.assertEqual(v["vote"], "abstain")
        self.assertIn("snapshot", v["detail"])

    def test_channel_down_abstains_never_blocks(self):
        srv = CtrlServer(lambda m, p, c: ok({}))
        port = srv.port
        srv.close()
        cfg = {"control": {"filmcraft": f"127.0.0.1:{port}",
                           "connect_timeout_s": "0.1"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        v = self._rung(ctx)
        self.assertEqual(v["vote"], "abstain")

    def test_malformed_stream_abstains(self):
        srv = CtrlServer(lambda m, p, c: b"junk\n")
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}",
                           "read_timeout_s": "0.3"}}
        ctx = self._ctx(cfg=cfg)
        control.note_before(ctx.turn_dir.parent.name, "filmcraft",
                            INSPECT, ELEMENTS)
        self.assertEqual(self._rung(ctx)["vote"], "abstain")

    def test_rung_registered_into_verify(self):
        self.assertIn("control", verify.RUNGS)
        self.assertIs(verify.RUNGS["control"], control.verify_rung)

    def test_control_vote_never_sole_sources(self):
        # through the ladder: control votes landed alone -> landed but
        # corroborated False (R2a reconcile already in verify.py)
        import zlib, struct

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data)))
        raw = b"".join(b"\x00" + bytes([90, 90, 90]) * 4
                       for _ in range(4))
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR",
                       struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        ctx = self._ctx(cfg={"control": {"filmcraft": "127.0.0.1:1"}})
        (ctx.turn_dir / "before.png").write_bytes(png)
        (ctx.turn_dir / "after.png").write_bytes(png)

        def rung(c):
            return {"vote": "landed", "detail": "ui.inspect diff"}
        step = {"tool": "click", "arg": "100,100@logical",
                "turn_dir": str(ctx.turn_dir),
                "action_truth": {"effect": "delivered"}}
        vd = verify.verdict(step, name="click", arg="100,100@logical",
                            tool_arg="100,100@logical", cfg={},
                            clients=[], monitors=[],
                            rungs={"control": rung},
                            judge=lambda *a: {"verdict": "unverifiable"})
        self.assertEqual(vd["verdict"], "landed")
        self.assertFalse(vd["corroborated"])
        self.assertEqual(vd["source"], "control")


class Untrusted(unittest.TestCase):
    def test_huge_element_list_capped(self):
        els = [{"id": f"e{i}", "label": "x", "rect": [0, 0, 1, 1]}
               for i in range(control.ELEMENT_CAP * 3)]
        srv = CtrlServer(lambda m, p, c: ok(els))
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            out = c.elements()
        self.assertEqual(len(out), control.ELEMENT_CAP)

    def test_control_chars_and_long_fields_scrubbed(self):
        els = [{"id": "evil\x1b[2j\nid", "label": "a\x00b" + "x" * 999,
                "rect": [0, 0, 5, 5]}]
        srv = CtrlServer(lambda m, p, c: ok(els))
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            out = c.elements()
        self.assertEqual(out[0]["id"], "evil[2jid")
        self.assertNotIn("\x00", out[0]["label"])
        self.assertEqual(len(out[0]["label"]), control.ID_CAP)

    def test_deep_inspect_bounded(self):
        deep = v = {}
        for i in range(50):
            v["k"] = {"next": {}}
            v = v["k"]["next"]
        srv = CtrlServer(lambda m, p, c: ok(deep))
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            out = c.inspect()          # bounded, never raises
        self.assertIsInstance(out, dict)

    def test_nan_and_infinity_sanitized(self):
        srv = CtrlServer(lambda m, p, c: (
            b'{"id":1,"ok":true,"result":{"fps":NaN,"x":Infinity}}\n'))
        self.addCleanup(srv.close)
        with control.ControlClient("127.0.0.1", srv.port) as c:
            out = c.inspect()          # json.loads parses NaN/Infinity
        self.assertEqual(out["fps"], "nan")
        self.assertEqual(out["x"], "inf")

    def test_diff_detail_never_carries_control_chars(self):
        srv = CtrlServer(
            lambda m, p, c: ok(ELEMENTS if m == "ui.elements"
                               else dict(INSPECT, ui={
                                   "tool": "razor\x07\x1b"})))
        self.addCleanup(srv.close)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        ctx = SimpleNamespace(
            turn_dir=pathlib.Path(td.name) / "t-x" / "turn-00001",
            cfg={"control": {"filmcraft": f"127.0.0.1:{srv.port}"}},
            claim={}, step={"tool": "click"})
        ctx.turn_dir.mkdir(parents=True)
        control._BEFORE.clear()
        control.note_before("t-x", "filmcraft", INSPECT, ELEMENTS)
        with mock.patch.object(control, "_clients",
                               return_value=CLIENTS), \
                mock.patch.object(control, "_activewindow",
                                  return_value=AW):
            v = control.verify_rung(ctx)
        self.assertNotRegex(v["detail"], r"[\x00-\x1f]")


if __name__ == "__main__":
    unittest.main()
