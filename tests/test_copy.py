#!/usr/bin/env python3
"""Shared UI copy (DESIGN-v2 5.9; plan U2, KTD7).

wisp/copy.py is the one source; scripts/assets/gen_copy.py writes
shell-plugin/lib/copy.js from it. These tests pin the vocabulary and fail
when the generated file is stale.
"""
import pathlib
import re
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts" / "assets"))

from wisp import copy as wcopy  # noqa: E402
import gen_copy  # noqa: E402

DASHES = ("—", "–")


def ipc_statuses():
    text = (ROOT / "docs" / "IPC_CONTRACT.md").read_text()
    m = re.search(r'"status":\s*"([a-z_|]+)"', text)
    return m.group(1).split("|")


class TestStatusWords(unittest.TestCase):
    def test_every_ipc_status_has_a_word_and_tone(self):
        statuses = ipc_statuses()
        self.assertIn("awaiting_choice", statuses)
        for s in statuses:
            self.assertTrue(wcopy.status_word(s), s)
            self.assertIn(wcopy.status_tone(s), wcopy.TONES, s)

    def test_spec_vocabulary(self):
        exp = {"idle": "ready", "transcribing": "hearing you",
               "deciding": "thinking", "acting": "working",
               "awaiting_choice": "your call", "suggestion": "idea",
               "error": "that failed", "offline": "offline"}
        for s, w in exp.items():
            self.assertEqual(wcopy.status_word(s), w)

    def test_unknown_status_reads_offline(self):
        self.assertEqual(wcopy.status_word("bogus"), "offline")
        self.assertEqual(wcopy.status_word(""), "offline")
        self.assertEqual(wcopy.status_tone("bogus"),
                         wcopy.status_tone("offline"))

    def test_red_means_failed_only(self):
        fails = [s for s in wcopy.STATUS if wcopy.status_tone(s) == "fail"]
        self.assertEqual(fails, ["error"])
        self.assertEqual(wcopy.status_tone("awaiting_choice"), "needsYou")

    def test_words_are_lowercase(self):
        for s, (word, _) in wcopy.STATUS.items():
            self.assertEqual(word, word.lower(), s)


class TestResults(unittest.TestCase):
    def test_skip_no_app_is_didnt_understand(self):
        r = wcopy.translate_result(
            "SKIP (launch route but no app identified)")
        self.assertEqual(r["text"], "didn't catch which app")
        self.assertEqual(r["state"], "didnt_understand")
        self.assertEqual(r["detail"],
                         "SKIP (launch route but no app identified)")

    def test_blocked_needs_confirmation(self):
        r = wcopy.translate_result("BLOCKED (tool 'x' needs confirmation)")
        self.assertEqual(r["text"], "blocked: needs your ok")
        self.assertIsNone(r["state"])

    def test_blocked_other_reason_keeps_reason(self):
        r = wcopy.translate_result("BLOCKED (window is locked)")
        self.assertEqual(r["text"], "blocked: window is locked")

    def test_ask_user_shows_the_question(self):
        r = wcopy.translate_result("ASK_USER which account?")
        self.assertEqual(r["text"], "which account?")

    def test_unrecognized_skip_hides_protocol(self):
        r = wcopy.translate_result("SKIP (rc=3)")
        self.assertNotIn("SKIP", r["text"])
        self.assertEqual(r["detail"], "SKIP (rc=3)")

    def test_plain_answer_passes_through(self):
        r = wcopy.translate_result("Opened Firefox.")
        self.assertEqual(r, {"text": "Opened Firefox.", "state": None,
                             "detail": ""})

    def test_no_translation_contains_a_dash(self):
        samples = ["SKIPPED (shell disabled — set allow_shell=true)",
                   "BLOCKED (risk=0.90 > 0.5)",
                   "SKIP (codebase-memory-mcp not installed — x)",
                   "BLOCKED (a — b)", "ERROR (boom)"]
        for raw in samples:
            text = wcopy.translate_result(raw)["text"]
            for d in DASHES:
                self.assertNotIn(d, text, raw)
        for rule in wcopy.RESULT_RULES:
            for d in DASHES:
                self.assertNotIn(d, rule[1])


class TestPickLabel(unittest.TestCase):
    def test_labels(self):
        cases = {"app:firefox": "firefox", "app:none": "none of these",
                 "action:launch": "open it",
                 "action:run_shell": "run a command",
                 "action:new_thing": "new thing",
                 "suggestion:action:act": "do it for me",
                 "Close all windows — yes": "Close all windows: yes",
                 "no": "no"}
        for pick, want in cases.items():
            self.assertEqual(wcopy.pick_label(pick), want, pick)


class TestGenerated(unittest.TestCase):
    def test_copy_js_is_fresh(self):
        js = ROOT / "shell-plugin" / "lib" / "copy.js"
        self.assertEqual(js.read_text(), gen_copy.render(),
                         "copy.js is stale: run "
                         "python scripts/assets/gen_copy.py")

    def test_gen_copy_check_mode(self):
        p = subprocess.run([sys.executable,
                            str(ROOT / "scripts" / "assets" / "gen_copy.py"),
                            "--check"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)


if __name__ == "__main__":
    unittest.main()
