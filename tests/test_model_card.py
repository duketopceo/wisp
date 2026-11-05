"""B13: 3D parts cards: glTF/GLB parts, the allow-listed fetch, the note
object, the typed `ask` turn and the pure-JS projection (node)."""
import io
import json
import os
import pathlib
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import jsnode  # noqa: E402
from wisp import config, model3d, note, stage_capture, stage_ctx  # noqa: E402
from wisp.tools import modelfetch  # noqa: E402

URL = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Models/main/car.glb"


def gltf(**over):
    doc = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"name": "toy car", "nodes": [0]}],
        "nodes": [{"name": "body", "mesh": 0, "children": [1, 2]},
                  {"name": "wheel_front", "mesh": 1,
                   "translation": [2, 0, 0]},
                  {"mesh": 1, "translation": [-2, 0, 0]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]},
                   {"primitives": [{"attributes": {"POSITION": 1}}]}],
        "accessors": [{"min": [-1, -1, -1], "max": [1, 1, 1]},
                      {"min": [-.5, -.5, -.5], "max": [.5, .5, .5]}]}
    doc.update(over)
    return doc


def glb(doc):
    body = json.dumps(doc).encode()
    body += b" " * (-len(body) % 4)
    total = 12 + 8 + len(body)
    return (struct.pack("<III", 0x46546C67, 2, total)
            + struct.pack("<II", len(body), 0x4E4F534A) + body)


class Parts(unittest.TestCase):
    def test_gltf_json_gives_named_boxes_scaled_to_one(self):
        got = model3d.parse(json.dumps(gltf()).encode())
        self.assertEqual(got["title"], "toy car")
        self.assertEqual([p["name"] for p in got["parts"]],
                         ["body", "wheel front", "part 3"])
        xs = [p["box"][0] for p in got["parts"]] + \
             [p["box"][3] for p in got["parts"]]
        self.assertAlmostEqual(max(xs) - min(xs), 1.0, places=3)

    def test_glb_reads_the_same(self):
        a = model3d.parse(json.dumps(gltf()).encode())
        b = model3d.parse(glb(gltf()))
        self.assertEqual(a, b)

    def test_duplicate_names_are_numbered(self):
        d = gltf()
        d["nodes"][2]["name"] = "wheel_front"
        got = model3d.parse(json.dumps(d).encode())
        self.assertEqual([p["name"] for p in got["parts"]][1:],
                         ["wheel front", "wheel front 2"])

    def test_a_file_that_points_elsewhere_is_refused(self):
        for key in ("buffers", "images"):
            d = gltf(**{key: [{"uri": "https://evil.example/x.bin"}]})
            with self.assertRaises(model3d.ModelError):
                model3d.parse(json.dumps(d).encode())
        ok = gltf(buffers=[{"uri": "data:application/octet-stream;base64,AA"}])
        model3d.parse(json.dumps(ok).encode())

    def test_junk_and_oversize_never_raise_anything_else(self):
        for data in (b"", b"not json", b"[]", b'{"asset": 1}',
                     b"glTF" + b"\0" * 20, glb({"asset": {}})[:20],
                     json.dumps(gltf(nodes=[{"mesh": 9}])).encode(),
                     json.dumps(gltf(nodes=[{}] * 3000)).encode(),
                     b" " * (model3d.MAX_JSON + 1)):
            with self.assertRaises(model3d.ModelError, msg=data[:20]):
                model3d.parse(data)

    def test_a_node_cycle_and_hostile_numbers_are_harmless(self):
        d = gltf()
        d["nodes"][1]["children"] = [0]
        d["nodes"][0]["scale"] = [1e308, "x", None]
        d["accessors"][0]["max"] = [1, float("1e999") if False else 1, 1]
        got = model3d.parse(json.dumps(d).encode())
        self.assertTrue(got["parts"])

    def test_parts_are_capped(self):
        n = model3d.MAX_PARTS + 20
        d = gltf(nodes=[{"mesh": 0, "name": f"p{i}"} for i in range(n)],
                 scenes=[{"nodes": list(range(n))}])
        self.assertEqual(len(model3d.parse(json.dumps(d).encode())["parts"]),
                         model3d.MAX_PARTS)


class Resp:
    def __init__(self, data):
        self.buf = io.BytesIO(data)

    def read(self, n=-1):
        return self.buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Env(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        for p in (mock.patch.object(config, "DATA_DIR", self.tmp / "data"),
                  mock.patch.object(config, "load_config", lambda: {}),
                  mock.patch.dict(os.environ, {
                      "WISP_NOTES_DIR": str(self.tmp / "notes")})):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def opener(data, calls=None):
        def op(url, timeout):
            if calls is not None:
                calls.append(url)
            return Resp(data)
        return op


class Fetch(Env):
    def test_only_listed_https_hosts(self):
        self.assertEqual(modelfetch.check_url(URL, {}),
                         "raw.githubusercontent.com")
        for bad, word in (("http://raw.githubusercontent.com/a.glb", "secure"),
                          ("https://evil.example.com/a.glb", "isn't on"),
                          ("https://u:p@raw.githubusercontent.com/a", "login"),
                          ("", "secure")):
            with self.assertRaises(modelfetch.ModelRefused) as cm:
                modelfetch.check_url(bad, {})
            self.assertIn(word, str(cm.exception))
        cfg = {"models": {"allow": "models.example.org"}}
        modelfetch.check_url("https://cdn.models.example.org/a.glb", cfg)
        with self.assertRaises(modelfetch.ModelRefused):
            modelfetch.check_url(URL, cfg)

    def test_fetch_stores_parts_not_the_file_and_repeats_are_free(self):
        calls = []
        data = glb(gltf())
        rec = modelfetch.fetch(URL, {}, opener=self.opener(data, calls),
                               resolve=lambda h: None)
        self.assertEqual(len(rec["parts"]), 3)
        again = modelfetch.fetch(URL, {}, opener=self.opener(data, calls),
                                 resolve=lambda h: None)
        self.assertEqual(again["parts"], rec["parts"])
        self.assertEqual(len(calls), 1)
        stored = list(modelfetch.models_dir().iterdir())
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].stat().st_mode & 0o777, 0o600)
        self.assertNotIn(b"glTF", stored[0].read_bytes()[:4])

    def test_too_large_and_not_a_model_fail_speakably(self):
        with self.assertRaises(modelfetch.ModelFailed) as cm:
            modelfetch.fetch(URL, {"models": {"max_kb": "1"}},
                             opener=self.opener(b"x" * 4096),
                             resolve=lambda h: None)
        self.assertIn("too large", str(cm.exception))
        with self.assertRaises(modelfetch.ModelFailed):
            modelfetch.fetch(URL, {}, opener=self.opener(b"<html>"),
                             resolve=lambda h: None)
        self.assertIsNone(modelfetch.lookup(URL))

    def test_private_hosts_are_refused_before_any_download(self):
        calls = []
        with mock.patch("socket.getaddrinfo", return_value=[
                (2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(modelfetch.ModelRefused):
                modelfetch.fetch(URL, {}, opener=self.opener(b"", calls))
        self.assertEqual(calls, [])


class NoteObject(Env):
    TEXT = f"::model[url={URL},alt=toy car]\nclick a part\n::"

    def test_a_model_object_parses_and_is_never_spoken(self):
        parsed = note.parse(self.TEXT)
        self.assertEqual([o["kind"] for o in parsed["objects"]], ["model"])
        self.assertEqual(note.strip_image_lines("Here it is.\n" + self.TEXT),
                         "Here it is.")

    def test_loading_then_ready_with_parts(self):
        jobs = []
        pad = note.NotePad("c", root=self.tmp / "notes", cfg={},
                           fetch_model=lambda u, cfg: modelfetch.fetch(
                               u, cfg, opener=self.opener(glb(gltf())),
                               resolve=lambda h: None),
                           spawn=jobs.append)
        first = pad.set(self.TEXT)
        st = first["objects"][0]["model"]
        self.assertEqual((st["status"], st["parts"]), ("loading", []))
        self.assertEqual(len(jobs), 1)
        jobs[0]()
        again = note._payload("c", pad.path, note.parse(self.TEXT),
                              closed=False, cfg={})
        st = again["objects"][0]["model"]
        self.assertEqual(st["status"], "ready")
        self.assertEqual(len(st["parts"]), 3)
        self.assertEqual(st["title"], "toy car")

    def test_a_refused_model_starts_no_download_and_has_a_reason(self):
        jobs = []
        pad = note.NotePad("c", root=self.tmp / "notes", cfg={},
                           spawn=jobs.append)
        out = pad.set("::model[url=https://evil.example.com/a.glb]\n::")
        self.assertEqual(jobs, [])
        self.assertEqual(out["objects"][0]["model"]["status"], "refused")
        self.assertIn("evil.example.com", note.refusals(out)[0])


class TypedTurn(unittest.TestCase):
    def test_a_typed_question_skips_recording_and_stt(self):
        ctx = stage_ctx.TurnCtx({}, mock.Mock(), None, None, None,
                                mock.MagicMock(), "t", mock.Mock(), None,
                                60, "m")
        ctx.typed = "what is the wheel for?"
        with mock.patch.object(stage_capture, "_pl") as pl:
            self.assertTrue(stage_capture.capture_stage(ctx))
        pl.return_value.record.assert_not_called()
        pl.return_value.transcribe.assert_not_called()
        self.assertEqual(ctx.text, "what is the wheel for?")
        ctx.state.transition.assert_called_once()
        self.assertEqual(ctx.state.transition.call_args.args[0], "deciding")
        self.assertEqual(
            ctx.state.transition.call_args.kwargs["transcript"],
            "what is the wheel for?")

    def test_ask_is_a_mutating_command_for_marked_peers(self):
        from wisp import ipc
        self.assertEqual(ipc.classify_cmd("ask"), "mutating")


class AskVerb(unittest.TestCase):
    """The real daemon: `ask` refuses empty text and starts a turn for a
    question (the turn itself fails without models; the reply is what
    counts)."""

    def test_empty_is_refused_and_a_question_is_accepted(self):
        import socket
        from daemonbox import DaemonBox
        box = DaemonBox()
        self.addCleanup(box.close)
        box.start()
        self.assertTrue(box.sock.exists(), "daemon did not start")

        def send(msg):
            c = socket.socket(socket.AF_UNIX)
            c.settimeout(20)
            c.connect(str(box.sock))
            c.sendall(json.dumps(msg).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = c.recv(65536)
                if not chunk:
                    break
                data += chunk
            c.close()
            return json.loads(data)

        self.assertEqual(send({"cmd": "ask", "text": "  "}),
                         {"ok": False, "error": "empty"})
        self.assertEqual(send({"cmd": "ask", "text": "what is the lid?"}),
                         {"ok": True, "asked": True})


@unittest.skipUnless(jsnode.NODE, "node not installed")
class Projection(unittest.TestCase):
    PARTS = ('[{name:"body",box:[-.5,-.2,-.2,.3,.15,.2]},'
             '{name:"wheel",box:[.15,-.35,-.25,.4,-.1,.25]}]')

    @staticmethod
    def call(expr):
        return jsnode.call(expr, M="model3d")

    def test_only_a_ready_model_with_good_parts_makes_a_card(self):
        note_ = ('{objects:[{kind:"model",attrs:{alt:"car"},model:'
                 '{status:"%s",parts:%s}}]}')
        self.assertIsNone(self.call("M.modelOf(%s)" % (
            note_ % ("loading", self.PARTS))))
        self.assertIsNone(self.call("M.modelOf(%s)" % (
            note_ % ("ready", "[]"))))
        self.assertIsNone(self.call("M.modelOf(%s)" % (
            note_ % ("ready", '[{name:"x",box:[1,2]}]'))))
        got = self.call("M.modelOf(%s)" % (note_ % ("ready", self.PARTS)))
        self.assertEqual((got["title"], len(got["parts"])), ("car", 2))
        for none in ("null", "undefined", "{}", "{objects:5}"):
            self.assertIsNone(self.call(f"M.modelOf({none})"))

    def test_rectangles_stay_inside_the_view_for_any_turn(self):
        for yaw in (0, 0.6, 1.57, 3.1, -2):
            for pitch in (-1.2, 0, 0.45, 1.2):
                rs = self.call(f"M.project({self.PARTS},{yaw},{pitch},280,200)")
                for r in rs:
                    self.assertGreaterEqual(r["x"], -1)
                    self.assertGreaterEqual(r["y"], -1)
                    self.assertLessEqual(r["x"] + r["w"], 281)
                    self.assertLessEqual(r["y"] + r["h"], 201)

    def test_the_nearest_part_wins_a_click_and_a_miss_is_empty(self):
        rects = ('[{name:"far",x:0,y:0,w:50,h:50,depth:-1},'
                 '{name:"near",x:20,y:20,w:50,h:50,depth:1}]')
        self.assertEqual(self.call(f"M.hit({rects},30,30)"), "near")
        self.assertEqual(self.call(f"M.hit({rects},5,5)"), "far")
        self.assertEqual(self.call(f"M.hit({rects},200,200)"), "")

    def test_the_question_names_the_part_and_is_plain_text(self):
        self.assertEqual(self.call('M.question("toy car","front wheel")'),
                         "What is the front wheel of the toy car, and what "
                         "does it do?")
        self.assertEqual(self.call('M.question("","lid")'),
                         "What is the lid part, and what does it do?")
        self.assertEqual(self.call('M.question("car","")'), "")
        q = self.call('M.question("c\\n\\u0000ar","a\\nb' + "x" * 100 + '")')
        self.assertNotIn("\n", q)
        self.assertLess(len(q), 140)

    def test_pitch_is_clamped(self):
        self.assertEqual(self.call("M.clampPitch(9)"), 1.2)
        self.assertEqual(self.call("M.clampPitch(-9)"), -1.2)


if __name__ == "__main__":
    unittest.main()
