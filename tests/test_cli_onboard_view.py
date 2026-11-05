#!/usr/bin/env python3
"""Onboarding checklist and walk: one lit step, everything else quiet."""
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wisp.cli import onboard_view as ov, output  # noqa: E402
from cli_env import CliEnv  # noqa: E402
from tty_env import tty_run  # noqa: E402

GOLD = ROOT / "tests" / "golden" / "output"


def step(i, name, state, detail, fix="", optional=False):
    return {"id": i, "name": name, "optional": optional, "state": state,
            "ok": state == "done", "done": state == "done",
            "detail": detail, "try": fix}


ST = {"finished": False, "ready": False, "steps": [
    step("mic", "microphone", "done", "parecord and the speech model are ready"),
    step("models", "models", "done", "local models off; brain is "
         "openrouter:meta-llama/llama-4-maverick"),
    step("keys", "API keys", "todo", "missing OPENROUTER_API_KEY (brain), "
         "GROQ_API_KEY (speech)", "wispd onboard --step keys"),
    step("agents", "background agents", "todo", "not installed",
         "wispd install --agents", True),
    step("cua", "cua pointer driver", "na", "cua-driver is not installed "
         "(optional)", "", True),
    step("notifications", "notifications", "todo", "no notifier found",
         "omarchy pkg add libnotify"),
]}


class TestChecklist(unittest.TestCase):
    def test_goldens_at_three_widths(self):
        for width in (60, 80, 200):
            with self.subTest(width=width):
                text = ov.checklist(ST, width=width) + "\n"
                f = GOLD / f"onboard_status_{width}.txt"
                if os.environ.get("WISP_UPDATE_GOLDEN"):
                    f.write_text(text)
                self.assertEqual(text, f.read_text())
                for line in text.splitlines():
                    self.assertLessEqual(output.display_width(line),
                                         min(width, 100), line)

    def test_exactly_one_lit_step_and_it_is_the_first_open_required_one(self):
        t = ov.checklist(ST, glyphs=True)
        self.assertEqual(t.count("\u25cf"), 1)
        lit = next(l for l in t.splitlines() if "\u25cf" in l)
        self.assertIn("API keys", lit)
        self.assertEqual(t.count("\u25cb"), 2)       # the other open steps
        self.assertIn("done", t)
        self.assertIn("n/a", t)

    def test_fix_is_shown_for_the_lit_step_only(self):
        t = ov.checklist(ST)
        self.assertIn("next: wispd onboard --step keys", t)
        self.assertNotIn("wispd install --agents", t)
        self.assertIn("wispd onboard --step keys   do this step", t)

    def test_when_required_steps_are_done_an_optional_one_is_lit(self):
        st = dict(ST, steps=[dict(s, state="done") if not s["optional"]
                             and s["state"] != "na" else s
                             for s in ST["steps"]])
        lit = next(l for l in ov.checklist(st, glyphs=True).splitlines()
                   if "\u25cf" in l)
        self.assertIn("background agents", lit)

    def test_all_done_says_ready_and_lights_nothing(self):
        st = dict(ST, ready=True, steps=[dict(s, state="done" if s["state"]
                                              != "na" else "na")
                                         for s in ST["steps"]])
        t = ov.checklist(st, glyphs=True)
        self.assertNotIn("\u25cf", t)
        self.assertIn("Setup is ready.", t)

    def test_only_the_lit_dot_is_ember(self):
        t = ov.checklist(ST, color=True, glyphs=True)
        self.assertEqual(t.count("\x1b[1;33m"), 1)
        self.assertNotIn("\x1b[32m", t)      # done steps are not green
        self.assertNotIn("\x1b[93m", t)

    def test_plain_output_is_ascii_without_glyphs(self):
        self.assertTrue(ov.checklist(ST).isascii())


class TestWalkView(unittest.TestCase):
    def test_step_header_has_one_dot_and_a_quiet_count(self):
        h = ov.step_header("microphone", 1, 7, glyphs=True, first=True)
        self.assertEqual(h, ["\u25cf Microphone   step 1 of 7"])
        h = ov.step_header("API keys", 3, 7, glyphs=False)
        self.assertEqual(h, ["", "* API keys   step 3 of 7"])

    def test_result_lines_are_quiet_words(self):
        self.assertEqual(ov.result_line("done", "ok"), "  done ok")
        self.assertEqual(ov.result_line("fail", "x"), "  not yet x")
        self.assertEqual(ov.result_line("fix", "do y"), "  fix: do y")
        self.assertEqual(ov.result_line("undo", "z"), "  undo: z")
        self.assertNotIn("\x1b", ov.result_line("done", "ok"))

    def test_opening_is_the_wordmark_and_a_wrapped_note(self):
        lines = ov.opening(7, glyphs=True, width=60)
        self.assertEqual(lines[0], "\u25cf wisp")
        for l in lines:
            self.assertLessEqual(output.display_width(l), 60)


class TestOnboardCommand(unittest.TestCase):
    def test_json_status_keeps_its_shape(self):
        with CliEnv() as env:
            code, out, err = env.run(["onboard", "--status", "--json"])
            import json
            j = json.loads(out)["data"]
            self.assertTrue({"ready", "finished", "done_count", "total",
                             "steps"} <= set(j))
            self.assertTrue(all({"id", "name", "state", "ok", "try"}
                                <= set(s) for s in j["steps"]))

    def test_piped_status_is_the_checklist(self):
        with CliEnv() as env:
            code, out, err = env.run(["onboard", "--status"])
            self.assertEqual(code, 0, err)
            self.assertTrue(out.startswith("wisp onboard"))
            self.assertTrue(out.isascii())
            self.assertEqual(out.count("\n* ") + out.count("  * "), 1)

    def test_walk_on_a_tty_shows_the_wordmark_then_one_lit_step_at_a_time(
            self):
        with CliEnv() as env:
            e = dict(env.env, LANG="C.UTF-8", NO_COLOR="1", COLUMNS="80")
            code, text = tty_run(e, ["onboard"], stdin_text="q\n")
            self.assertEqual(code, 0, text)
            plain = output.strip_ansi(text)
            self.assertTrue(plain.startswith("\u25cf wisp\n  voice agent"),
                            plain[:60])
            self.assertEqual(plain.count("\u25cf"), 2)   # wordmark + step 1
            self.assertIn("step 1 of", plain)


if __name__ == "__main__":
    unittest.main()
