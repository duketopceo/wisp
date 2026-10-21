"""U5 `observe` — the act loop's model-facing frame capture.

A frame comes from the focused app's control channel `ui.screenshot`
when the app ships a channel (a fake JSON-lines server stands in),
else a cua `zoom` crop in the run's "wisp" session (a fake `call()`
boundary). The verify path's visible deny gate runs BEFORE any
capture — a deny-listed or unreadable surface means no frame, no
rec dir, no pack entry. A captured frame lands in a minted
`turn-9NNNN/` dir with driver-shaped action.json + evidence.json so
packs.write indexes it with kind:"observe".
"""
import base64
import json
import pathlib
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import zlib
from types import SimpleNamespace
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import cli_env  # noqa: E402

from wisp import act, cua, observe, packs, record, tools  # noqa: E402
from wisp import control  # noqa: E402
from wisp import trace as _trace  # noqa: E402


# ------------------------------------------------------------ fixtures

def _png_bytes(w=8, h=8):
    """Minimal RGB8 PNG — no PIL needed."""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))


PNG = _png_bytes()
JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01"
        b"\x00\x00" + b"\x00" * 32 + b"\xff\xd9")


class CtrlServer:
    """Loopback JSON-lines server — one reply dict per request line."""

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
                threading.Thread(target=self._serve, args=(conn,),
                                 daemon=True).start()
        except OSError:
            return

    def _serve(self, conn):
        try:
            f = conn.makefile("rb")
            while True:
                line = f.readline(8 * 1024 * 1024)
                if not line:
                    return
                if not line.strip():
                    continue
                req = json.loads(line)
                self.requests.append((req.get("method"),
                                      req.get("params") or {}))
                r = self.handler(req.get("method", ""),
                                 req.get("params") or {})
                d = dict(r or {})
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


class FakeCua:
    """The cua driver boundary: replies[tool] -> reply dict, or an
    Exception to raise, or a callable(args, kw) -> dict."""

    def __init__(self, replies):
        self.replies = dict(replies)
        self.calls = []

    def call(self, tool, args=None, *, timeout=None, strict=True,
             session="wisp"):
        args = dict(args or {})
        self.calls.append({"tool": tool, "args": args,
                           "session": session})
        r = self.replies.get(tool)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            return r(args)
        return dict(r or {})

    def calls_named(self, tool):
        return [c for c in self.calls if c["tool"] == tool]


# compositor fixtures — a focused FilmCraft window and a plain foot
WIN_FC = {"class": "ai.storyteller.filmcraft", "title": "FilmCraft — x",
          "address": "0xabc", "pid": 4242,
          "bounds": (100.0, 50.0, 800.0, 600.0)}
WIN_FOOT = {"class": "foot", "title": "shell", "address": "0xdef",
            "pid": 777, "bounds": (10.0, 10.0, 700.0, 500.0)}
CLIENTS_OK = [{"class": "ai.storyteller.filmcraft",
               "title": "FilmCraft — x", "mapped": True,
               "workspace": {"id": 1}}]
CLIENTS_DENY = CLIENTS_OK + [
    {"class": "gcr-prompter", "title": "unlock", "mapped": True,
     "workspace": {"id": 1}}]
MONS = [{"activeWorkspace": {"id": 1}}]


class ObserveCase(unittest.TestCase):
    """rec/, packs/, shots/, salt and the trace file all live in a
    temp dir."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        t = pathlib.Path(self.td.name)
        self.rec_root = t / "rec"
        self.rec = self.rec_root / "t-o1"
        self.store = t / "packs"
        self._patchers = [
            mock.patch.object(record, "REC_DIR", self.rec_root),
            mock.patch.object(packs, "PACKS_DIR", self.store),
            mock.patch.object(packs, "SALT_FILE", t / "pack.salt"),
            mock.patch.object(packs, "SHOTS_DIR", t / "shots"),
            mock.patch.object(observe, "SHOTS_DIR", t / "shots"),
            mock.patch.object(_trace, "TRACE_FILE", t / "trace.jsonl"),
            mock.patch.object(_trace, "_enabled", True),
        ]
        for p in self._patchers:
            p.start()
        self.addCleanup(self._unpatch)

    def _unpatch(self):
        for p in reversed(self._patchers):
            p.stop()

    def manifest(self, turn="t-o1"):
        return json.loads(
            (self.store / turn / "manifest.json").read_text())


class TestChannel(ObserveCase):
    """Lane 1: a focused channel app -> ui.screenshot writes the PNG."""

    def test_channel_screenshot_lands_in_turn_dir(self):
        def h(method, params):
            self.assertEqual(method, "ui.screenshot")
            pathlib.Path(params["path"]).write_bytes(PNG)
            return ok({"path": params["path"], "w": 400, "h": 300})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertFalse(out["suppressed"])
        self.assertEqual(out["source"], "control")
        self.assertTrue(out["result"].startswith("SHOT "))
        frame = self.rec / "turn-90000" / "observe.png"
        self.assertEqual(out["path"], frame)
        self.assertEqual(out["turn_dir"], self.rec / "turn-90000")
        self.assertEqual(frame.read_bytes(), PNG)
        # the request carried the destination path + no panel
        params = srv.requests[0][1]
        self.assertEqual(params["path"], str(frame))
        self.assertNotIn("panel", params)
        # driver-shaped metadata — packs can index the dir
        action = json.loads(
            (self.rec / "turn-90000" / "action.json").read_text())
        self.assertEqual(action["tool"], "observe")
        self.assertEqual(action["action_truth"]["route"],
                         "observe:control")
        ev = json.loads(
            (self.rec / "turn-90000" / "evidence.json").read_text())
        self.assertEqual(ev["kind"], "observe")
        self.assertEqual(ev["source"], "control")

    def test_panel_arg_reaches_the_channel(self):
        def h(method, params):
            pathlib.Path(params["path"]).write_bytes(PNG)
            return ok({"path": params["path"]})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("timeline", cfg, rec_dir=self.rec,
                              win=WIN_FC, clients=CLIENTS_OK,
                              monitors=MONS)
        self.assertTrue(out["result"].startswith("SHOT "))
        self.assertEqual(srv.requests[0][1]["panel"], "timeline")

    def test_channel_inline_image_reply_is_written(self):
        # an app may return the image instead of writing the path —
        # either way the frame lands
        b64 = base64.b64encode(PNG).decode()
        srv = CtrlServer(lambda m, p: ok({"image": b64}))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        frame = self.rec / "turn-90000" / "observe.png"
        self.assertEqual(out["path"], frame)
        self.assertEqual(frame.read_bytes(), PNG)

    def test_channel_written_non_image_is_deleted(self):
        # F3: the app writes into our evidence dir but its bytes stay
        # untrusted — a non-image payload is unlinked, then the reply's
        # inline image is tried instead
        def h(method, params):
            pathlib.Path(params["path"]).write_bytes(
                b"definitely not an image, just text")
            return ok({"image": base64.b64encode(PNG).decode()})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        frame = self.rec / "turn-90000" / "observe.png"
        self.assertEqual(frame.read_bytes(), PNG)   # inline fallback
        self.assertTrue(out["result"].startswith("SHOT "))

    def test_channel_written_non_image_without_inline_dies(self):
        def h(method, params):
            pathlib.Path(params["path"]).write_bytes(b"not an image")
            return ok({})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertIsNone(out["path"])
        self.assertEqual(out["source"], None)
        # the hostile file never survived in the evidence dir
        self.assertFalse(
            (self.rec / "turn-90000" / "observe.png").exists())

    def test_channel_written_oversize_is_deleted(self):
        # F4: an app-written file over IMG_CAP is not evidence
        def h(method, params):
            pathlib.Path(params["path"]).write_bytes(
                PNG + b"\x00" * (observe.IMG_CAP + 1))
            return ok({})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertIsNone(out["path"])
        self.assertFalse(
            (self.rec / "turn-90000" / "observe.png").exists())

    def test_channel_written_symlink_is_deleted(self):
        # a symlink target is NOT a regular file — the channel cannot
        # alias evidence to bytes it doesn't own
        def h(method, params):
            p = pathlib.Path(params["path"])
            real = p.parent / "real.png"
            real.write_bytes(PNG)
            p.symlink_to(real)
            return ok({})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertIsNone(out["path"])
        p = self.rec / "turn-90000" / "observe.png"
        self.assertFalse(p.exists() or p.is_symlink())


class TestZoom(ObserveCase):
    """Lane 2: no channel on the focused app -> cua zoom crop."""

    def _fake(self, zoom_reply=None, zoom_exc=None):
        replies = {
            "list_windows": {"windows": [
                {"pid": 777, "window_id": 7, "title": "shell",
                 "class": "foot",
                 "frame": {"x": 10, "y": 10, "w": 700, "h": 500}}]},
            "get_window_state": {
                "window_bounds": {"x": 10, "y": 10, "w": 700, "h": 500},
                "screenshot": {"width": 700, "height": 500}},
        }
        if zoom_exc is not None:
            replies["zoom"] = zoom_exc
        else:
            replies["zoom"] = zoom_reply or {
                "image": base64.b64encode(JPEG).decode(),
                "mime_type": "image/jpeg"}
        return FakeCua(replies)

    def test_zoom_fallback_crops_the_window(self):
        fake = self._fake()
        out = observe.capture("", {}, rec_dir=self.rec, win=WIN_FOOT,
                              clients=[{"class": "foot", "mapped": True,
                                        "workspace": {"id": 1}}],
                              monitors=MONS, cua_client=fake)
        self.assertEqual(out["source"], "zoom")
        frame = self.rec / "turn-90000" / "observe.jpg"
        self.assertEqual(out["path"], frame)
        self.assertEqual(frame.read_bytes(), JPEG)
        # snapshot-first ordering: list -> get_window_state -> zoom
        tools_called = [c["tool"] for c in fake.calls]
        self.assertEqual(tools_called,
                         ["list_windows", "get_window_state", "zoom"])
        # same session as the recording — the label flows explicitly
        for c in fake.calls:
            self.assertEqual(c["session"], "wisp")
        zoom = fake.calls_named("zoom")[0]["args"]
        self.assertEqual((zoom["window_id"], zoom["pid"]), (7, 777))
        self.assertEqual((zoom["x1"], zoom["y1"], zoom["x2"],
                          zoom["y2"]), (0, 0, 700, 500))
        # get_window_state primed a screenshot context, not an AT-SPI
        # walk
        snap = fake.calls_named("get_window_state")[0]["args"]
        self.assertTrue(snap["include_screenshot"])
        self.assertFalse(snap["include_accessibility_tree"])
        ev = json.loads(
            (self.rec / "turn-90000" / "evidence.json").read_text())
        self.assertEqual(ev["kind"], "observe")
        self.assertEqual(ev["source"], "zoom")

    def test_zoom_region_arg(self):
        fake = self._fake()
        out = observe.capture("10,20,300,200", {}, rec_dir=self.rec,
                              win=WIN_FOOT, clients=[], monitors=MONS,
                              cua_client=fake)
        self.assertTrue(out["result"].startswith("SHOT "))
        zoom = fake.calls_named("zoom")[0]["args"]
        self.assertEqual((zoom["x1"], zoom["y1"], zoom["x2"],
                          zoom["y2"]), (10, 20, 300, 200))

    def test_missing_snapshot_context_reprimes_and_retries(self):
        calls = {"n": 0}

        def zoom(args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise cua.CuaError(cua.REFUSED,
                                   "screenshot_context_missing")
            return {"image": base64.b64encode(JPEG).decode()}
        fake = FakeCua({
            "list_windows": {"windows": [
                {"pid": 777, "window_id": 7,
                 "frame": {"x": 10, "y": 10, "w": 700, "h": 500}}]},
            "get_window_state": {"screenshot": {"width": 700,
                                                "height": 500}},
            "zoom": zoom})
        out = observe.capture("", {}, rec_dir=self.rec, win=WIN_FOOT,
                              clients=[], monitors=MONS,
                              cua_client=fake)
        self.assertTrue(out["result"].startswith("SHOT "))
        self.assertEqual(len(fake.calls_named("zoom")), 2)
        self.assertGreaterEqual(
            len(fake.calls_named("get_window_state")), 2)

    def test_no_focused_window_and_no_channel_skips(self):
        fake = self._fake()
        out = observe.capture("", {}, rec_dir=self.rec,
                              win=None, active={},
                              clients=[], monitors=MONS,
                              cua_client=fake)
        self.assertTrue(out["result"].startswith("SKIP"))
        self.assertIsNone(out["path"])
        # nothing was captured or minted
        self.assertFalse(fake.calls)
        self.assertFalse(self.rec.exists())


class TestSuppression(ObserveCase):
    """R9: the verify gate precedes every capture attempt."""

    def test_deny_listed_surface_suppresses(self):
        srv = CtrlServer(lambda m, p: ok({"path": p.get("path")}))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        fake = self._fake_zoom()
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_DENY, monitors=MONS,
                              cua_client=fake)
        self.assertTrue(out["suppressed"])
        self.assertTrue(out["result"].startswith("SUPPRESSED"))
        self.assertIn("deny-listed", out["result"])
        # no frame, no rec dir minted, neither lane was attempted
        self.assertEqual(srv.requests, [])
        self.assertFalse(fake.calls)
        self.assertFalse(self.rec.exists())
        # and nothing durable lands in a pack either
        pack = packs.write("t-o1", [{"tool": "observe", "arg": "",
                                     "result": out["result"]}],
                           rec_dir=self.rec, recorded=False,
                           clients=CLIENTS_DENY, monitors=MONS)
        self.assertIsNone(pack)
        self.assertFalse(self.store.exists())

    def test_unreadable_window_list_suppresses(self):
        def boom():
            raise OSError("hypr socket gone")
        out = observe.capture("", {}, rec_dir=self.rec, win=WIN_FC,
                              clients=boom, monitors=MONS)
        self.assertTrue(out["suppressed"])
        self.assertIn("unreadable", out["result"])
        self.assertFalse(self.rec.exists())

    def _fake_zoom(self):
        return FakeCua({
            "list_windows": {"windows": []},
            "zoom": {"image": base64.b64encode(JPEG).decode()}})


class TestPackLinkage(ObserveCase):
    """The observe dir indexes like recorded evidence, provenance
    marked."""

    def test_observe_frame_in_manifest_frames(self):
        def h(method, params):
            pathlib.Path(params["path"]).write_bytes(PNG)
            return ok({"path": params["path"]})
        srv = CtrlServer(h)
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=self.rec, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertEqual(out["source"], "control")
        step = {"tool": "observe", "arg": "",
                "result": out["result"],
                "turn_dir": str(out["turn_dir"])}
        pack = packs.write("t-o1", [step], cfg=cfg, rec_dir=self.rec,
                           recorded=False,
                           transcript=[{"role": "user",
                                        "text": "look"}],
                           clients=CLIENTS_OK, monitors=MONS)
        self.assertEqual(pack, self.store / "t-o1")
        m = self.manifest()
        # frames[] carries the observe dir, the frame marked observe
        entry = next(e for e in m["frames"]
                     if e["dir"] == "turn-90000")
        kinds = {f["name"]: f["kind"] for f in entry["files"]}
        self.assertEqual(kinds["observe.png"], "observe")
        self.assertIn("action.json", kinds)
        self.assertIn("evidence.json", kinds)
        self.assertGreaterEqual(m["frame_count"], 1)
        # the action index links the step to the dir + stamped ts
        a = next(a for a in m["actions"] if a["tool"] == "observe")
        self.assertEqual(a["turn_dir"], "turn-90000")
        self.assertIn("ts", a)
        # the actual file is durable in the pack
        self.assertEqual(
            (pack / "turn-90000" / "observe.png").read_bytes(), PNG)
        # rec/ intermediates were cleaned after promotion
        self.assertFalse(self.rec.exists())

    def test_shots_fallback_links_nothing(self):
        # no turn context -> the frame lands in shots/; capture()
        # reports no turn_dir so the pack stays empty
        srv = CtrlServer(lambda m, p: ok({"image": base64.b64encode(
            PNG).decode()}))
        self.addCleanup(srv.close)
        cfg = {"control": {"filmcraft": f"127.0.0.1:{srv.port}"}}
        out = observe.capture("", cfg, rec_dir=None, win=WIN_FC,
                              clients=CLIENTS_OK, monitors=MONS)
        self.assertTrue(out["result"].startswith("SHOT "))
        self.assertIsNone(out["turn_dir"])
        self.assertEqual(pathlib.Path(out["path"]).parent,
                         pathlib.Path(observe.SHOTS_DIR))


class TestPathConfinement(ObserveCase):
    """F4: a reply's file-path image key is only honored when the
    resolved real path sits inside the minted evidence dir — it can
    never become a read of an arbitrary host path."""

    def _zoom_fake(self, reply):
        return FakeCua({
            "list_windows": {"windows": [
                {"pid": 777, "window_id": 7, "title": "shell",
                 "class": "foot",
                 "frame": {"x": 10, "y": 10, "w": 700, "h": 500}}]},
            "get_window_state": {
                "window_bounds": {"x": 10, "y": 10, "w": 700, "h": 500},
                "screenshot": {"width": 700, "height": 500}},
            "zoom": reply})

    def _cap(self, fake):
        return observe.capture(
            "", {}, rec_dir=self.rec, win=WIN_FOOT,
            clients=[{"class": "foot", "mapped": True,
                      "workspace": {"id": 1}}],
            monitors=MONS, cua_client=fake)

    def test_path_key_outside_the_evidence_dir_refused(self):
        # a hostile reply points at a host file — outside root => the
        # key is ignored entirely (no read, no frame)
        secret = pathlib.Path(self.td.name) / "secret.png"
        secret.write_bytes(PNG)
        fake = self._zoom_fake({"path": str(secret)})
        out = self._cap(fake)
        self.assertIsNone(out["path"])
        self.assertFalse(
            (self.rec / "turn-90000" / "observe.jpg").exists())

    def test_path_key_escape_via_dotdot_refused(self):
        fake = self._zoom_fake(
            {"path": str(self.rec / ".." / "escape.png")})
        (pathlib.Path(self.td.name) / "escape.png").write_bytes(PNG)
        out = self._cap(fake)
        self.assertIsNone(out["path"])

    def test_path_key_inside_the_evidence_dir_serves(self):
        # the reply is computed at call time: it points at a file it
        # just wrote inside the freshly-minted evidence dir
        def zoom(args):
            d = max(self.rec.glob("turn-9*"))
            (d / "channel-wrote.png").write_bytes(PNG)
            return {"path": str(d / "channel-wrote.png")}
        fake = FakeCua({
            "list_windows": {"windows": [
                {"pid": 777, "window_id": 7, "title": "shell",
                 "class": "foot",
                 "frame": {"x": 10, "y": 10, "w": 700, "h": 500}}]},
            "get_window_state": {
                "window_bounds": {"x": 10, "y": 10, "w": 700, "h": 500},
                "screenshot": {"width": 700, "height": 500}},
            "zoom": zoom})
        out = self._cap(fake)
        self.assertIsNotNone(out["path"])
        self.assertEqual(out["path"].read_bytes(), PNG)

    def test_symlink_path_key_never_serves(self):
        # inside-root name aliased to outside bytes — resolve() moves
        # it out of root, so it is refused
        outside = pathlib.Path(self.td.name) / "outside.png"
        outside.write_bytes(PNG)

        def zoom(args):
            d = max(self.rec.glob("turn-9*"))
            (d / "alias.png").symlink_to(outside)
            return {"path": str(d / "alias.png")}
        fake = FakeCua({
            "list_windows": {"windows": [
                {"pid": 777, "window_id": 7, "title": "shell",
                 "class": "foot",
                 "frame": {"x": 10, "y": 10, "w": 700, "h": 500}}]},
            "get_window_state": {
                "window_bounds": {"x": 10, "y": 10, "w": 700, "h": 500},
                "screenshot": {"width": 700, "height": 500}},
            "zoom": zoom})
        out = self._cap(fake)
        self.assertIsNone(out["path"])


class TestToolWiring(unittest.TestCase):
    """REGISTRY -> schema -> run() -> wisp.observe.observe."""

    def test_schema_advertises_observe(self):
        names = {t["function"]["name"] for t in tools.tool_schemas()}
        self.assertIn("observe", names)
        meta = tools.meta_of("observe")
        self.assertEqual(meta["tier"], "T0")
        self.assertEqual(tools.risk_of("observe"), "safe")
        self.assertIn("observe", tools.describe())

    def test_run_dispatches_to_observe(self):
        with mock.patch.object(observe, "observe",
                               return_value="SHOT /tmp/x.png") as o:
            out = tools.run("observe", "", {"agent": {}})
        self.assertEqual(out, "SHOT /tmp/x.png")
        o.assert_called_once_with("", {"agent": {}})


class TestLoopObserve(unittest.TestCase):
    """The act loop: observe feeds the frame to the model through the
    existing image path and links the turn dir — without running the
    verdict ladder on a read-only capture."""

    def test_observe_attaches_image_and_turn_dir(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        d = pathlib.Path(td.name) / "turn-90000"
        d.mkdir(parents=True)
        frame = d / "observe.png"
        frame.write_bytes(PNG)
        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "observe",
                                          "arguments": json.dumps(
                                              {"arg": ""})}}]},
            {"role": "assistant", "content": "looks good"},
        ]
        steps = []
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(act, "_write_pack"), \
                mock.patch("wisp.brain.provider",
                           return_value={"name": "openrouter",
                                         "vision": "true",
                                         "tools": "true"}), \
                mock.patch.object(observe, "observe",
                                  return_value=f"SHOT {frame}") as o, \
                mock.patch.object(act, "_attach_image") as att:
            out = act.run_act_loop("inspect the app", {"agent": {}},
                                   steps_out=steps,
                                   initial_image="aGk=")
        self.assertTrue(out.startswith("ACTED"), out)
        o.assert_called_once()
        # the frame attaches through the existing model_image path,
        # flagged as a cropped inspect-only view (coords=False)
        att.assert_called_once()
        a_args, a_kw = att.call_args
        self.assertEqual(a_args[1], str(frame))
        self.assertEqual(a_kw.get("coords"), False)
        # the step links the turn dir but carries no verdict ladder
        self.assertEqual(steps[0]["turn_dir"], str(d))
        self.assertNotIn("verify", steps[0])
        self.assertNotIn("verdict", steps[0])

    def test_suppressed_observe_links_nothing(self):
        replies = [
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function",
                             "function": {"name": "observe",
                                          "arguments": json.dumps(
                                              {"arg": ""})}}]},
            {"role": "assistant", "content": "can't look"},
        ]
        steps = []
        suppressed = ("SUPPRESSED (deny-listed surface visible: "
                      "gcr-prompter — observation declined; no frame "
                      "captured)")
        with mock.patch.object(act, "_post", side_effect=replies), \
                mock.patch.object(act, "_write_pack"), \
                mock.patch.object(observe, "observe",
                                  return_value=suppressed), \
                mock.patch.object(act, "_attach_image") as att:
            out = act.run_act_loop("inspect", {"agent": {}},
                                   steps_out=steps,
                                   initial_image="aGk=")
        self.assertTrue(out.startswith("ACTED"), out)
        att.assert_not_called()
        self.assertNotIn("turn_dir", steps[0])
        self.assertNotIn("verify", steps[0])


if __name__ == "__main__":
    unittest.main()
