"""Live lookups for the answer route: the trigger, the OpenRouter body and
the answer stage wiring. No network: every call is a mock."""
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp import brain, livequery, pipeline, speech, stage_speak  # noqa: E402
from tests.test_stage_speak import StageBase  # noqa: E402

POSITIVE = [
    "What's the weather like?",
    "What's the weather like today in Provo?",
    "Will it rain tomorrow?",
    "what's the forecast for this weekend",
    "How hot is it outside",
    "What are the headlines",
    "Any news on the election?",
    "What's the Jazz score?",
    "Who won the game last night?",
    "What's the Tesla stock price?",
    "What is the price of bitcoin right now",
    "What's the exchange rate for euros?",
    "What time is it in Tokyo?",
    "What's the latest on the shuttle launch?",
    "What is the current population of Utah?",
    "Tell me today's top story",
]
NEGATIVE = [
    "what is the current folder",
    "what is the latest file in my downloads",
    "what is the current branch in this repo",
    "What does this mean?",
    "What does this button do?",
    "Where do I change the display scale?",
    "What's on my screen?",
    "What does current mean in this dialog?",
    "Explain this error",
    "Open the terminal",
    "What is the latest message on my screen?",
    "",
]

OR = {"name": "openrouter", "kind": "openai_compat", "model": "m",
      "base_url": "https://openrouter.ai/api/v1", "key_env": ""}
US = {**OR, "base_url": "https://us.openrouter.ai/api/v1"}
OTHER = {**OR, "name": "x", "base_url": "https://example.invalid/v1"}
OLLAMA = {"name": "ollama", "kind": "ollama", "model": "m",
          "base_url": "http://127.0.0.1:11434"}
OK = {"choices": [{"message": {"content": "ok", "annotations": [
    {"type": "url_citation", "url_citation": {
        "url": "https://a.example/x", "title": "A"}},
    {"type": "url_citation", "url_citation": {
        "url": "https://a.example/x", "title": "A again"}}]}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.01}}


class NeedsWeb(unittest.TestCase):
    def test_positives(self):
        for t in POSITIVE:
            self.assertTrue(livequery.needs_web(t), t)

    def test_negatives(self):
        for t in NEGATIVE:
            self.assertFalse(livequery.needs_web(t), t)


class BodyShape(unittest.TestCase):
    def sent(self, p, web, stream=False):
        with mock.patch.object(brain, "_post", return_value=OK) as post, \
             mock.patch.object(brain, "_headers", return_value={}), \
             mock.patch.object(brain.cancel, "urlopen",
                               return_value=io.BytesIO(b"data: [DONE]\n")) as uo:
            if stream:
                res = brain._stream_one(p, [], None, 60, 5, web)
                body = json.loads(uo.call_args[0][0].data)
            else:
                res = brain._chat_one(p, [], None, 60, web)
                body = post.call_args[0][2]
        return body, res

    def test_plugin_only_on_openrouter_with_web_on(self):
        for stream in (False, True):
            for p in (OR, US):
                body, _ = self.sent(p, {"max_results": 2}, stream)
                self.assertEqual(body["plugins"],
                                 [{"id": "web", "max_results": 2}])
            body, _ = self.sent(OR, True, stream)
            self.assertEqual(body["plugins"], [{"id": "web"}])
            for p in (OR, OTHER, OLLAMA):
                body, res = self.sent(p, False, stream)
                self.assertNotIn("plugins", body)
                self.assertNotIn("citations", res)
            for p in (OTHER, OLLAMA):
                body, _ = self.sent(p, {"max_results": 3}, stream)
                self.assertNotIn("plugins", body)

    def test_usage_cost_still_requested(self):
        body, _ = self.sent(OR, True)
        self.assertEqual(body["usage"], {"include": True})

    def test_citations_non_stream(self):
        _, res = self.sent(OR, True)
        self.assertEqual(res["citations"],
                         [{"title": "A", "url": "https://a.example/x"}])
        self.assertEqual(res["usage"]["cost"], 0.01)

    def test_citations_stream(self):
        note = {"type": "url_citation", "url_citation": {
            "url": "https://b.example", "title": "B"}}
        chunks = [{"choices": [{"delta": {"content": "hi"}}]},
                  {"choices": [{"delta": {"annotations": [note]}}]},
                  {"choices": [], "usage": {"cost": 0.02}}]
        data = "".join(f"data: {json.dumps(c)}\n" for c in chunks) \
            + "data: [DONE]\n"
        with mock.patch.object(brain, "_headers", return_value={}), \
             mock.patch.object(brain.cancel, "urlopen",
                               return_value=io.BytesIO(data.encode())):
            res = brain._stream_one(OR, [], None, 60, 5, True)
        self.assertEqual(res["citations"],
                         [{"title": "B", "url": "https://b.example"}])
        self.assertEqual(res["usage"]["cost"], 0.02)

    def test_public_chat_threads_web_to_the_chain(self):
        cfg = {"brain": {"default": "openrouter:m"}}
        with mock.patch.object(brain, "_chat_one",
                               return_value={"content": "x"}) as one, \
             mock.patch.object(brain, "budget_ok", return_value=True):
            brain.chat([], cfg, web={"max_results": 4})
        self.assertEqual(one.call_args[1]["web"], {"max_results": 4})


class WebRequest(unittest.TestCase):
    OR_CFG = {"brain": {"default": "openrouter:m"}}
    LOCAL = {"brain": {"default": "ollama:m"}}

    def test_modes(self):
        w = livequery.web_request
        q = "What's the weather like?"
        self.assertEqual(w(self.OR_CFG, q), {"max_results": 3})
        self.assertIsNone(w(self.LOCAL, q))
        self.assertIsNone(w(self.OR_CFG, "What does this mean?"))
        off = {**self.OR_CFG, "web": {"search": "false"}}
        self.assertIsNone(w(off, q))
        on = {**self.LOCAL, "web": {"search": "true"}}
        self.assertEqual(w(on, q), {"max_results": 3})
        few = {**self.OR_CFG, "web": {"search_max_results": "5"}}
        self.assertEqual(w(few, q), {"max_results": 5})
        bad = {**self.OR_CFG, "web": {"search_max_results": "x"}}
        self.assertEqual(w(bad, q), {"max_results": 3})


class AskChat(unittest.TestCase):
    def test_extra_system_line_only_with_web(self):
        cfg = {"brain": {"default": "openrouter:m"}}
        for web in ({"max_results": 3}, None):
            with mock.patch.object(brain, "chat_stream",
                                   return_value={"content": "x",
                                                 "citations": []}) as cs, \
                 mock.patch("wisp.context.snapshot", return_value=""):
                stage_speak.ask_chat("weather?", cfg, on_delta=lambda t: 0,
                                     web=web)
            msgs = cs.call_args[0][0]
            self.assertEqual(cs.call_args[1].get("web"), web)
            has = any(m["content"] == livequery.PROMPT for m in msgs
                      if m["role"] == "system")
            self.assertEqual(has, bool(web))
            self.assertEqual(msgs[-1]["role"], "user")


class AnswerStage(StageBase):
    def run_stage(self, cfg, text):
        seen = {}

        def ask(transcript, cfg_, session_text="", image_b64=None,
                on_delta=None, meta=None, **kw):
            seen.update(kw)
            if meta is not None:
                meta["citations"] = [{"title": "A", "url": "https://a.example"}]
            return "Sunny."
        ctx = self.ctx(cfg)
        ctx.text = text
        with mock.patch.object(pipeline, "ask_chat", side_effect=ask), \
             mock.patch.object(pipeline.speech, "speak", return_value=None):
            stage_speak._answer(ctx)
        return seen

    def cfg(self, **web):
        return {"voice": {"enabled": "false"}, "agent": {},
                "brain": {"default": "openrouter:m"}, "web": web}

    def test_weather_turn_searches_and_traces_citations(self):
        seen = self.run_stage(self.cfg(), "What's the weather like?")
        self.assertEqual(seen["web"], {"max_results": 3})
        call = next(c for c in self.emit.call_args_list
                    if c[0][1] == "brain_call")
        self.assertEqual(call[0][3]["citations"],
                         [{"title": "A", "url": "https://a.example"}])

    def test_screen_question_does_not(self):
        seen = self.run_stage(self.cfg(), "What does this button do?")
        self.assertNotIn("web", seen)

    def test_search_false_disables(self):
        seen = self.run_stage(self.cfg(search="false"),
                              "What's the weather like?")
        self.assertNotIn("web", seen)


if __name__ == "__main__":
    unittest.main()
