#!/usr/bin/env python3
"""Shared UI copy (DESIGN-v2 5.9; plan U2, KTD7).

wisp/copy.py is the one source; scripts/assets/gen_copy.py writes
shell-plugin/lib/copy.js from it. These tests pin the vocabulary and fail
when the generated file is stale.
"""
import functools
import pathlib
import re
import subprocess
import sys
import unittest

import jsnode

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

    def test_word_view_blocked_is_not_done(self):
        self.assertEqual(wcopy.word_view("done", "BLOCKED (risk=0.90 > 0.5)"),
                         ("blocked", "needsYou"))
        self.assertEqual(wcopy.word_view("done", "ACTED ok"),
                         ("done", "ok"))
        self.assertEqual(wcopy.word_view("done", ""), ("done", "ok"))
        # only a finished turn is rewritten; every other status keeps its word
        for s in wcopy.STATUS:
            if s != "done":
                self.assertEqual(wcopy.word_view(s, "BLOCKED (x)"),
                                 (wcopy.status_word(s), wcopy.status_tone(s)))

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


class TestErrors(unittest.TestCase):
    def test_every_error_code_has_copy(self):
        from wisp import errors_codes
        self.assertEqual(set(wcopy.ERRORS), set(errors_codes.CODES))
        for code in errors_codes.CODES:
            self.assertTrue(wcopy.error_message(code), code)

    def test_unknown_code_reads_internal(self):
        self.assertEqual(wcopy.error_message("nope"),
                         wcopy.error_message("internal"))
        self.assertEqual(wcopy.error_hint(""), wcopy.error_hint("internal"))

    def test_messages_are_lowercase_plain(self):
        for code, (msg, hint) in wcopy.ERRORS.items():
            self.assertEqual(msg, msg.lower(), code)
            self.assertNotRegex(msg, r"\bE_[A-Z_]+|Exception|Traceback", code)

    def test_string_table(self):
        self.assertEqual(wcopy.string("state.reconnecting"), "reconnecting")
        self.assertEqual(wcopy.string("no.such.key"), "no.such.key")


@unittest.skipUnless(jsnode.NODE, "node not installed")
class TestJsParity(unittest.TestCase):
    """copy.js is generated, but its interpreter functions are
    hand-written; run both sides over one matrix so they cannot drift."""

    RESULTS = ["SKIP (launch route but no app identified)",
               "BLOCKED (tool 'x' needs confirmation)",
               "BLOCKED (risk=0.90 > 0.5)", "BLOCKED (a \u2014 b)",
               "BLOCKED (window is locked)", "ASK_USER which account?",
               "SKIPPED (shell disabled \u2014 set allow_shell=true)",
               "SKIPPED (close declined by user)",
               "SKIPPED (mcp_call handoff timed out)",
               "SKIPPED (mcp_call needs a human \u2014 no handoff channel)",
               "HANDED_OFF (mcp_call done by the user)",
               "SKIP (rc=3)", "ERROR (boom)", "ABORTED (user)",
               "Opened Firefox.", ""]
    PICKS = ["app:firefox", "app:none", "action:launch", "action:new_thing",
             "suggestion:action:act", "Close all windows \u2014 yes", "no",
             "", "x:y"]

    def js(self, expr):
        return jsnode.call(expr, Copy="copy", Status="status")

    def test_status(self):
        for s in list(wcopy.STATUS) + ["bogus", ""]:
            self.assertEqual(self.js(f"Status.statusWord({s!r})"),
                             wcopy.status_word(s), s)
            self.assertEqual(self.js(f"Status.statusTone({s!r})"),
                             wcopy.status_tone(s), s)

    def test_pill_view(self):
        for s in list(wcopy.STATUS) + ["bogus", ""]:
            for r in self.RESULTS:
                w, t = wcopy.word_view(s, r)
                got = self.js(f"Status.pillView({s!r}, {r!r})")
                self.assertEqual(got, {"word": w, "tone": t}, (s, r))

    def test_results(self):
        for raw in self.RESULTS:
            want = wcopy.translate_result(raw)
            got = self.js(f"Copy.translateResult({raw!r})")
            self.assertEqual(got, want, raw)

    def test_picks(self):
        for pick in self.PICKS:
            self.assertEqual(self.js(f"Copy.pickLabel({pick!r})"),
                             wcopy.pick_label(pick), pick)

    def test_errors_and_strings(self):
        for code in list(wcopy.ERRORS) + ["bogus", ""]:
            self.assertEqual(self.js(f"Copy.errorMessage({code!r})"),
                             wcopy.error_message(code), code)
            self.assertEqual(self.js(f"Copy.errorHint({code!r})"),
                             wcopy.error_hint(code), code)
        for key in list(wcopy.STRINGS) + ["no.such.key"]:
            self.assertEqual(self.js(f"Copy.string({key!r})"),
                             wcopy.string(key), key)

    def test_tables_identical(self):
        self.assertEqual(self.js("Copy.ERRORS"),
                         {k: list(v) for k, v in wcopy.ERRORS.items()})
        self.assertEqual(self.js("Copy.STRINGS"), wcopy.STRINGS)
        # the status words live in the one status table, not in copy.js
        self.assertEqual(
            {s: [self.js(f"Status.statusWord({s!r})"),
                 self.js(f"Status.statusTone({s!r})")]
             for s in wcopy.STATUS},
            {k: list(v) for k, v in wcopy.STATUS.items()})


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


# A literal key read through Copy.string("...") or ui("...") in the shell
# surfaces or the Python readers. string() returns an unknown key verbatim,
# so a missing key ships as raw text ("state.stale") instead of failing.
KEY_READ = re.compile(r"""(?:\bstring|\bui)\(\s*["']([a-z][\w.]*)["']\s*\)""")
# The settings window's Status pages; each must read at least one key, so
# the scan below cannot silently stop covering them.
STATUS_PAGES = ("shell-plugin/components/HealthSection.qml",
                "shell-plugin/components/SpendView.qml")


@functools.lru_cache(maxsize=None)
def _literal_key_reads():
    paths = [p for d in ("shell-plugin", "shells", "wisp")
             for p in (ROOT / d).rglob("*")
             if p.suffix in (".qml", ".js", ".py") and p.is_file()
             and "node_modules" not in p.parts]
    gen = {ROOT / "wisp" / "copy.py", ROOT / "shell-plugin" / "lib" / "copy.js"}
    return {str(p.relative_to(ROOT)): KEY_READ.findall(p.read_text())
            for p in paths if p not in gen}


class TestKeysExist(unittest.TestCase):
    def test_status_pages_read_only_existing_keys(self):
        reads = _literal_key_reads()
        for page in STATUS_PAGES:
            self.assertTrue(reads.get(page), f"{page} reads no copy key")
            missing = [k for k in reads[page] if k not in wcopy.STRINGS]
            self.assertEqual(missing, [], f"{page} reads keys not in "
                             "wisp/copy.py STRINGS")

    def test_every_literal_key_read_exists(self):
        missing = {f: sorted({k for k in keys if k not in wcopy.STRINGS})
                   for f, keys in _literal_key_reads().items()}
        missing = {f: ks for f, ks in missing.items() if ks}
        self.assertEqual(missing, {}, "copy keys read but not defined in "
                         "wisp/copy.py STRINGS; add them and rerun "
                         "scripts/assets/gen_copy.py")


if __name__ == "__main__":
    unittest.main()
