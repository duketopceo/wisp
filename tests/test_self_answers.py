"""B30: Wisp answers questions about itself from local state, with no
model call, and only when the phrase is the whole utterance."""
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402
from wisp import ledger, selfknow  # noqa: E402

NOW = dt.datetime(2026, 10, 28, 14, 0, 0)

CFG = {"brain": {"default": "openrouter:meta-llama/llama-4-maverick",
                 "fallback": "ollama:ornith", "router": "act"},
       "agent": {"model": "typesafe/jev-1.13"}}


def rows(*specs):
    """Ledger lines: (days_ago, provider, model, usd, paid)."""
    out = []
    for days, prov, model, usd, paid in specs:
        ts = (NOW - dt.timedelta(days=days)).isoformat(timespec="seconds")
        out.append(json.dumps({"ts": ts, "provider": prov, "model": model,
                               "in": 100, "out": 50, "usd": usd,
                               "paid": paid}))
    return "\n".join(out) + "\n"


class Intents(unittest.TestCase):
    YES = {
        "model": ["what model are you", "What model are you?",
                  "which model are you using", "what model is this",
                  "what are you running on", "wisp, what model are you"],
        "spend_today": ["what did I spend today",
                        "how much have I spent today",
                        "what's my spend today", "hey wisp what did i spend "
                        "today", "how much have you cost me today"],
        "spend_week": ["what did I spend this week",
                       "how much did I spend this week"],
        "version": ["what version is this", "what version are you",
                    "what version of wisp am I running",
                    "which version is this"],
        "copy": ["copy that", "Copy that to the clipboard.", "copy it",
                 "copy your last answer", "please copy that"],
        "again": ["say that again", "repeat that", "repeat that please",
                  "what did you say", "say it again"],
        "wrong": ["what went wrong", "what went wrong there",
                  "why did that fail", "what was the error"],
    }
    NO = [
        "explain what version control is",
        "what is the model of a car",
        "what model of phone should i buy",
        "how much did I spend on groceries",
        "what did I spend on the trip to Denver today",
        "copy that file to my desktop",
        "copy this paragraph into a new document",
        "say that again in French",
        "repeat that five times",
        "what went wrong in the roman empire",
        "what happened in 1066",
        "what version of python is this",
        "tell me what version you are and why",
        "", "   ", "x" * 200,
    ]

    def test_each_phrase_resolves_to_its_kind(self):
        for kind, phrases in self.YES.items():
            for p in phrases:
                self.assertEqual(selfknow.intent(p), kind, p)

    def test_phrases_inside_a_longer_question_are_not_captured(self):
        for p in self.NO:
            self.assertIsNone(selfknow.intent(p), p)

    def test_every_kind_is_covered(self):
        self.assertEqual(set(self.YES), set(selfknow.KINDS))


class Spend(unittest.TestCase):
    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.path = d / "usage.jsonl"
        self.path.write_text(rows(
            (0, "openrouter", "m1", 0.30, True),
            (0, "openrouter", "m1", 0.1234, True),
            (0, "ollama", "ornith", 0.0, False),
            (2, "openrouter", "m1", 1.00, True),
            (6, "openrouter", "m1", 0.50, True),
            (8, "openrouter", "m1", 9.00, True),     # outside the week
        ))

    def line(self, kind, cfg=None):
        return selfknow.spend_line(kind, cfg or {}, NOW, self.path)

    def test_today_matches_the_ledger(self):
        t = ledger.totals(NOW, self.path)
        self.assertAlmostEqual(t["today_usd"], 0.4234, places=4)
        self.assertEqual(t["calls_today"], 3)
        self.assertEqual(self.line("spend_today"),
                         "You've spent $0.42 today, across 3 calls. "
                         "Your daily cap is $8.")

    def test_the_week_is_the_last_seven_days_and_matches_the_ledger(self):
        w = ledger.window(7, NOW, self.path)
        self.assertAlmostEqual(w["usd"], 1.9234, places=4)
        self.assertEqual(w["calls"], 5)
        self.assertEqual(self.line("spend_week"),
                         "You've spent $1.92 in the last seven days, "
                         "across 5 calls.")

    def test_the_daily_cap_is_the_configured_one(self):
        cfg = {"budget": {"daily_usd": "2"}}
        self.assertIn("Your daily cap is $2.", self.line("spend_today", cfg))
        self.assertIn("Your daily cap is $8.", self.line("spend_today"))
        self.assertNotIn("cap", self.line("spend_week"))

    def test_no_calls_and_free_calls_and_tiny_amounts(self):
        empty = pathlib.Path(tempfile.mkdtemp()) / "usage.jsonl"
        self.assertEqual(selfknow.spend_line("spend_today", {}, NOW, empty),
                         "You haven't made any model calls today.")
        self.path.write_text(rows((0, "ollama", "ornith", 0.0, False)))
        self.assertIn("nothing today", self.line("spend_today"))
        self.path.write_text(rows((0, "openrouter", "m", 0.004, True)))
        self.assertIn("under a cent", self.line("spend_today"))

    def test_an_unreadable_ledger_says_so(self):
        with mock.patch.object(ledger, "totals", side_effect=OSError):
            self.assertEqual(
                selfknow.answer("spend_today", {}),
                "I can't read the usage ledger right now.")


class Model(unittest.TestCase):
    def test_names_the_configured_models_and_the_last_call(self):
        last = {"provider": "openrouter", "model": "meta-llama/llama-4-"
                "maverick", "ts": ""}
        line = selfknow.models_line(CFG, last)
        self.assertIn("meta-llama/llama-4-maverick through openrouter", line)
        self.assertIn("falling back to ornith through ollama", line)
        self.assertIn("whisper-large-v3-turbo at api.groq.com", line)
        self.assertIn("My last call used meta-llama/llama-4-maverick", line)

    def test_never_names_a_model_that_is_not_configured(self):
        line = selfknow.models_line(CFG, None)
        for hidden in ("gpt", "claude", "gemini", "jev"):
            self.assertNotIn(hidden, line.lower())
        self.assertNotIn("last call", line)

    def test_the_router_model_is_named_only_when_it_is_used(self):
        cfg = {**CFG, "brain": {**CFG["brain"], "router": "jev"}}
        self.assertIn("the router is typesafe/jev-1.13",
                      selfknow.models_line(cfg))

    def test_a_local_speech_setup_says_so(self):
        cfg = {**CFG, "stt": {"provider": "whisper"}}
        self.assertIn("whisper on this machine", selfknow.models_line(cfg))

    def test_the_last_call_comes_from_the_ledger(self):
        d = pathlib.Path(tempfile.mkdtemp()) / "usage.jsonl"
        d.write_text(rows((3, "openrouter", "old", 0.1, True),
                          (0, "ollama", "ornith", 0.0, False)))
        self.assertEqual(ledger.last_call(path=d)["model"], "ornith")
        self.assertIsNone(ledger.last_call(
            path=pathlib.Path(tempfile.mkdtemp()) / "none.jsonl"))


class Version(unittest.TestCase):
    def test_release_and_development_and_unknown(self):
        with mock.patch("wisp.deploy.read", return_value={
                "ref": "v0.9.2", "commit": "0467ae3d0d40c6688627545f168672e"
                "46f9b3279"}):
            self.assertEqual(selfknow.version_line(),
                             "This is Wisp v0.9.2, commit 0467ae3.")
        with mock.patch("wisp.deploy.read", return_value={
                "ref": "master", "commit": "a762e9a538656b791e3a6e15b389b4"
                "b8efbea546"}):
            self.assertEqual(selfknow.version_line(),
                             "This is a development build, commit a762e9a.")
        with mock.patch("wisp.deploy.read", return_value=None):
            self.assertIn("no deploy record", selfknow.version_line())


class Replay(unittest.TestCase):
    TAIL = [
        {"route": "answer", "reply": "Press Super plus Space to open the "
         "launcher."},
        {"route": "setting", "reply": "I'm already as fast as I go."},
        {"route": "setting", "reply": "You've spent $0.42 today."},
    ]

    def test_again_repeats_the_last_real_answer_not_a_self_answer(self):
        self.assertEqual(selfknow.answer("again", {}, session_tail=self.TAIL),
                         "Press Super plus Space to open the launcher.")
        self.assertEqual(selfknow.answer("again", {}, session_tail=[]),
                         "I haven't said anything yet.")

    def test_copy_puts_the_full_answer_on_the_clipboard(self):
        got = []
        self.assertEqual(selfknow.answer(
            "copy", {}, session_tail=self.TAIL,
            copier=lambda t: got.append(t) or True), "Copied.")
        self.assertEqual(got, ["Press Super plus Space to open the "
                               "launcher."])
        self.assertIn("couldn't copy", selfknow.answer(
            "copy", {}, session_tail=self.TAIL, copier=lambda t: False))
        self.assertEqual(selfknow.answer("copy", {}, session_tail=[]),
                         "I have nothing to copy yet.")

    def test_wrong_reads_the_last_typed_error_in_plain_words(self):
        line = selfknow.answer("wrong", {}, errors=[
            {"ts": "t", "code": "timeout", "exc": "X"},
            {"ts": "t", "code": "brain_down", "exc": "URLError"}])
        self.assertEqual(
            line, "The last error: can't reach the answering model. "
            "Check your model endpoint, then try again.")
        self.assertNotIn("URLError", line)
        self.assertEqual(selfknow.answer("wrong", {}, errors=[]),
                         "Nothing has gone wrong that I know of.")

    def test_unknown_error_codes_still_get_words(self):
        line = selfknow.wrong_line([{"ts": "t", "code": "zzz", "exc": ""}])
        self.assertTrue(line.startswith("The last error:"))

    def test_run_returns_the_result_the_speak_stage_reads(self):
        out = selfknow.run("again", {})
        self.assertTrue(out.startswith("ACTED (0 steps): "))
        self.assertEqual(selfknow.run("nope", {}),
                         "SKIP (unknown self question)")


def turn(words):
    fx = runner.load_fixture("ask")
    fx["endpoints"]["whisper"]["transcript"] = words
    return runner.run_turn(fx)


class ZeroModelCalls(unittest.TestCase):
    def spoken(self, res):
        return [e["answer"] for e in res.events
                if e["status"] == "speaking" and e.get("answer")]

    def test_self_questions_make_no_brain_or_router_call(self):
        for words in ("what model are you", "what did I spend today",
                      "what version is this", "say that again",
                      "what went wrong", "copy that"):
            res = turn(words)
            self.assertEqual(res.exit_code, 0, res.stderr)
            self.assertEqual(res.violations, [])
            self.assertEqual(res.chat_calls("brain"), [], words)
            self.assertEqual(res.calls.get("jev", []), [], words)
            self.assertTrue(self.spoken(res), words)

    def test_the_model_answer_names_the_configured_model(self):
        res = turn("what model are you")
        self.assertIn("fake-model", self.spoken(res)[0])

    def test_a_longer_question_still_goes_to_the_brain(self):
        res = turn("explain what version control is")
        self.assertTrue(res.chat_calls("brain"))


if __name__ == "__main__":
    unittest.main()
