"""B25: nothing secret leaks into logs, and words only reach the stores
that exist to keep them.

A replay turn runs the real pipeline in a temp HOME with sentinel secrets
(an API key, a transcript). After it, every file the turn left on disk and
the child's stderr are searched:

- the sentinel key appears NOWHERE, trace on or off, on success and when a
  provider answers with an error that echoes the key back;
- the sentinel transcript appears only in the local stores that are meant
  to hold what you said (and each of those is private: see
  tests/test_private_data.py), never in stderr and never in an error
  report;
- with `[debug] trace = false` there is no trace file at all.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402
from wisp import report  # noqa: E402

KEY = "sk-test-SENTINEL-7Qx2LmN9"
WORDS = "SENTINELWORDS please summarise the quarterly numbers"
WORDS_TOKEN = "SENTINELWORDS"

# Local stores that hold what you said, by design. Documented in
# docs/TRUST.md ("Stored on this machine"); a new file carrying a
# transcript must be added there and here.
WORD_STORES = {
    "data/wisp/session.jsonl",     # recent turns, [session]
    "data/wisp/decisions.jsonl",   # route labels for `wispd label`
    "data/wisp/route_ab.jsonl",    # router agreement record
    "data/wisp/trace.jsonl",       # dev trace, [debug] trace
    "data/wisp/recall.db",         # memory index
    "run/wisp/state.json",         # live state for the panel (tmpfs)
}


def turn(name, trace="true", status=None, error_body=None, words=WORDS):
    fx = runner.load_fixture(name)
    fx["endpoints"]["whisper"]["transcript"] = words
    fx["env"] = {"OPENROUTER_API_KEY": KEY, "WISP_FAKE_STT_KEY": KEY}
    fx["config"] = {"debug": {"trace": trace}}
    if status:
        fx["endpoints"]["brain"]["status"] = status
        fx["endpoints"]["brain"]["error_body"] = error_body or ""
    return runner.run_turn(fx, collect_files=True)


class Hygiene(unittest.TestCase):
    def audit(self, res):
        self.assertEqual(res.violations, [])
        for path, text in res.files.items():
            self.assertNotIn(KEY, text, f"key leaked into {path}")
            self.assertNotIn("SENTINEL-7Qx2", text, f"key part in {path}")
        self.assertNotIn(KEY, res.stderr)
        self.assertNotIn(WORDS_TOKEN, res.stderr, "transcript on stderr")
        for path, text in res.files.items():
            if WORDS_TOKEN in text:
                self.assertIn(path, WORD_STORES,
                              f"transcript written to an unlisted file "
                              f"{path}")

    def test_success_turn_with_trace_on(self):
        res = turn("ask", trace="true")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.audit(res)
        self.assertIn("data/wisp/trace.jsonl", res.files)

    def test_trace_off_writes_no_trace_file(self):
        res = turn("ask", trace="false")
        self.assertEqual(res.exit_code, 0, res.stderr)
        self.audit(res)
        self.assertNotIn("data/wisp/trace.jsonl", res.files)

    def test_a_provider_error_that_echoes_the_key_does_not_leak_it(self):
        res = turn("brain_down", status=401,
                   error_body=f"Incorrect API key provided: {KEY} "
                              f"(you said {WORDS})")
        self.audit(res)
        self.assertEqual(res.final.get("error_code"), "brain_down")

    def test_a_key_in_the_transcript_is_not_copied_to_a_log_file_we_forgot(
            self):
        res = turn("ask", words=f"my key is {KEY} and {WORDS}")
        # the words themselves may sit in the listed stores, but no other
        # file and not stderr
        for path, text in res.files.items():
            if KEY in text:
                self.assertIn(path, WORD_STORES, path)
        self.assertNotIn(KEY, res.stderr)

    def test_the_stores_are_the_only_places_with_words(self):
        res = turn("ask")
        carrying = {p for p, t in res.files.items() if WORDS_TOKEN in t}
        self.assertTrue(carrying <= WORD_STORES, carrying - WORD_STORES)
        self.assertIn("data/wisp/session.jsonl", carrying)


class ErrorReports(unittest.TestCase):
    def queue(self, exc, context=None):
        with tempfile.TemporaryDirectory() as d:
            q = pathlib.Path(d) / "q.jsonl"
            r = report.Reporter(
                {"report": {"dsn": "http://pub@127.0.0.1:9/1"}},
                queue_file=q, sync=True)
            self.assertTrue(r.capture("brain_down", exc, context))
            return q.read_text() if q.exists() else ""

    def test_the_queue_has_neither_key_nor_words(self):
        exc = RuntimeError(f"HTTP 401 {KEY} {WORDS}")
        text = self.queue(exc, {
            "transcript": WORDS, "typed": WORDS, "reply": WORDS,
            "api_key": KEY, "headers": {"Authorization": f"Bearer {KEY}"},
            "detail": f"Incorrect API key provided: {KEY}",
            "path": "/home/someone/.config/wisp/.env"})
        self.assertTrue(text)
        self.assertNotIn(KEY, text)
        self.assertNotIn("SENTINEL-7Qx2", text)
        self.assertNotIn(WORDS_TOKEN, text)
        self.assertNotIn("someone", text)

    def test_a_key_inside_free_text_is_masked(self):
        text = self.queue(RuntimeError("x"), {
            "where": f"provider said: Incorrect API key {KEY} rejected"})
        self.assertNotIn(KEY, text)


if __name__ == "__main__":
    unittest.main()
