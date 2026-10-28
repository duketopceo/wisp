"""U1-U3: real answers, session memory, tiered screen context."""
import base64
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import pipeline, session


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
        self.assertIn("wisp: opened discord", txt)

    def test_as_text_spoken_friendly(self):
        # act-loop noise must read like conversation, not internals —
        # 'ACTED (3 steps): opened it' → 'opened it'; failures admit
        turns = [{"transcript": "open it",
                  "result": "ACTED (3 steps): opened it"},
                 {"transcript": "click gdx",
                  "result": "SKIP (click needs user confirmation)"},
                 {"transcript": "which account",
                  "result": "ASK_USER which account?"}]
        txt = session.as_text(turns)
        self.assertIn("wisp: opened it", txt)
        self.assertIn("wisp: couldn't do that", txt)
        self.assertIn("wisp: asked: which account?", txt)
        self.assertNotIn("ACTED", txt)
        self.assertNotIn("SKIP", txt)


class TestAskChat(unittest.TestCase):
    def setUp(self):
        # brain now refuses a keyed provider with no key (key_missing)
        k = mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
        k.start()
        self.addCleanup(k.stop)

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
        # needs_screen question removed — route alone decides now
        return {"route": {"choice": route}}

    def test_disabled_in_config(self):
        cfg = {"agent": {"screenshots": "false"}}
        self.assertIsNone(pipeline.screen_b64(cfg, self.answers(noul=1.0)))

    def test_non_answer_route_no_capture(self):
        with mock.patch.object(pipeline, "capture_screen") as c:
            out = pipeline.screen_b64({"agent": {}}, self.answers())
        self.assertIsNone(out)
        c.assert_not_called()

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


class TestSessionPerApp(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.p = pathlib.Path(td.name) / "session.jsonl"

    def add(self, said, app):
        session.append_turn(said, reply="r " + said, path=self.p, app=app)

    def test_scoped_tail_returns_only_that_apps_turns(self):
        self.add("in term 1", "kitty")
        self.add("in browser", "firefox")
        self.add("in term 2", "Kitty")
        out = session.tail(8, path=self.p, app="kitty")
        self.assertEqual([t["transcript"] for t in out],
                         ["in term 1", "in term 2"])
        out = session.tail(8, path=self.p, app="firefox")
        self.assertEqual([t["transcript"] for t in out], ["in browser"])

    def test_scoped_tail_limits_to_n_after_filtering(self):
        for i in range(5):
            self.add(f"t{i}", "kitty")
            self.add(f"b{i}", "firefox")
        out = session.tail(2, path=self.p, app="kitty")
        self.assertEqual([t["transcript"] for t in out], ["t3", "t4"])

    def test_unscoped_tail_sees_every_app(self):
        self.add("a", "kitty")
        self.add("b", "firefox")
        self.assertEqual(len(session.tail(8, path=self.p)), 2)

    def test_legacy_records_have_no_app(self):
        self.p.write_text('{"transcript": "old"}\n')
        self.add("new", "kitty")
        self.assertEqual([t["transcript"] for t in
                          session.tail(8, path=self.p, app="kitty")],
                         ["new"])
        self.assertEqual(len(session.tail(8, path=self.p)), 2)

    def test_unknown_app_matches_unlabelled_turns_only(self):
        self.add("none", "")
        self.add("term", "kitty")
        self.assertEqual([t["transcript"] for t in
                          session.tail(8, path=self.p, app="")], ["none"])

    def test_non_object_lines_are_skipped(self):
        self.p.write_text('"junk"\n[1]\n')
        self.add("ok", "kitty")
        self.assertEqual(len(session.tail(8, path=self.p, app="kitty")), 1)


class TestPrevTurnPerApp(unittest.TestCase):
    def test_act_prev_turn_reads_the_focused_apps_turn(self):
        from types import SimpleNamespace
        from wisp import act
        state = SimpleNamespace(focus={"app": "kitty", "title": "x"})
        with mock.patch.object(session, "tail",
                               return_value=[{"transcript": "ls",
                                              "reply": "listed"}]) as t:
            txt = act._prev_turn(state)
        t.assert_called_once_with(1, app="kitty")
        self.assertIn("user: ls", txt)

    def test_act_prev_turn_without_focus_is_unscoped(self):
        from wisp import act
        with mock.patch.object(session, "tail", return_value=[]) as t:
            self.assertEqual(act._prev_turn(None), "")
        t.assert_called_once_with(1, app=None)


class TestFinishRecordsTheApp(unittest.TestCase):
    def test_finished_turn_is_logged_with_its_focused_app(self):
        from types import SimpleNamespace
        from wisp import stage_speak
        ctx = SimpleNamespace(
            state=mock.MagicMock(), cfg={}, sp=mock.MagicMock(),
            text="list files", reply="done", result="ANSWERED",
            answers={"route": {"choice": "answer"}}, turn="t1",
            app="kitty")
        with mock.patch.object(stage_speak, "_pl"), \
                mock.patch.object(session, "append_turn") as add, \
                mock.patch("wisp.bgwriter.submit"):
            self.assertEqual(stage_speak._finish(ctx), 0)
        self.assertEqual(add.call_args.kwargs["app"], "kitty")
