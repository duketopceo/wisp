"""U1-U3: real answers, session memory, tiered screen context."""
import base64
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from dim import pipeline, session


class TestSession(unittest.TestCase):
    def test_append_and_tail(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "session.jsonl"
            for i in range(3):
                session.append_turn(f"say {i}", route="answer",
                                    reply=f"reply {i}", path=p)
            out = session.tail(2, path=p)
            self.assertEqual([t["transcript"] for t in out],
                             ["say 1", "say 2"])

    def test_tail_missing_file(self):
        self.assertEqual(session.tail(path=pathlib.Path("/nonexistent/x")),
                         [])

    def test_tail_tolerates_torn_line(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "session.jsonl"
            p.write_text('{"transcript": "ok"}\n{"transcript": "tor')
            out = session.tail(path=p)
            self.assertEqual(len(out), 1)

    def test_as_text(self):
        turns = [{"transcript": "open discord", "result": "LAUNCHED"},
                 {"transcript": "what did I do", "reply": "opened discord"}]
        txt = session.as_text(turns)
        self.assertIn("user: open discord", txt)
        self.assertIn("dim: opened discord", txt)


class TestAskChat(unittest.TestCase):
    def _resp(self, content="real reply"):
        body = json.dumps({"choices": [{"message": {"content": content}}]})
        m = mock.Mock()
        m.read.return_value = body.encode()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda *a: False
        return m

    def test_returns_model_reply(self):
        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=self._resp()), \
             mock.patch.object(pipeline.config, "load_api_key",
                               return_value="k"):
            out = pipeline.ask_chat("what can I say", {"agent": {}})
        self.assertEqual(out, "real reply")

    def test_empty_choices_returns_empty(self):
        body = json.dumps({"choices": []})
        m = mock.Mock()
        m.read.return_value = body.encode()
        m.__enter__ = lambda s: s
        m.__exit__ = lambda *a: False
        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               return_value=m), \
             mock.patch.object(pipeline.config, "load_api_key",
                               return_value="k"):
            self.assertEqual(pipeline.ask_chat("hi", {"agent": {}}), "")

    def test_image_part_attached(self):
        sent = {}

        def fake(req, **kw):
            sent.update(json.loads(req.data))
            return self._resp()

        with mock.patch.object(pipeline.urllib.request, "urlopen",
                               side_effect=fake), \
             mock.patch.object(pipeline.config, "load_api_key",
                               return_value="k"):
            pipeline.ask_chat("what is this", {"agent": {}},
                              image_b64=base64.b64encode(b"png").decode())
        content = sent["messages"][-1]["content"]
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"]
                        .startswith("data:image/png;base64,"))


class TestScreenB64(unittest.TestCase):
    def answers(self, noul=0.0, route="launch"):
        return {"needs_screen": {"noul": noul},
                "route": {"choice": route}}

    def test_disabled_in_config(self):
        cfg = {"agent": {"screenshots": "false"}}
        self.assertIsNone(pipeline.screen_b64(cfg, self.answers(noul=1.0)))

    def test_low_noul_no_capture(self):
        with mock.patch.object(pipeline, "capture_screen") as c:
            out = pipeline.screen_b64({"agent": {}}, self.answers(noul=0.2))
        self.assertIsNone(out)
        c.assert_not_called()

    def test_high_noul_captures(self):
        with tempfile.TemporaryDirectory() as td:
            png = pathlib.Path(td) / "s.png"
            png.write_bytes(b"fakepng")
            with mock.patch.object(pipeline, "capture_screen",
                                   return_value=png):
                out = pipeline.screen_b64({"agent": {}},
                                          self.answers(noul=0.9))
        self.assertEqual(base64.b64decode(out), b"fakepng")
        self.assertFalse(png.exists())  # cleaned up

    def test_answer_route_captures(self):
        with tempfile.TemporaryDirectory() as td:
            png = pathlib.Path(td) / "s.png"
            png.write_bytes(b"x")
            with mock.patch.object(pipeline, "capture_screen",
                                   return_value=png):
                out = pipeline.screen_b64({"agent": {}},
                                          self.answers(noul=0.1,
                                                       route="answer"))
        self.assertIsNotNone(out)

    def test_grim_failure_returns_none(self):
        with mock.patch.object(pipeline, "capture_screen",
                               return_value=None):
            self.assertIsNone(pipeline.screen_b64({"agent": {}},
                                                  self.answers(noul=1.0)))


if __name__ == "__main__":
    unittest.main()
