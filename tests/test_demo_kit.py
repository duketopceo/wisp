"""B17: the demo harness plans without recording, refuses a demo that did
not happen, and cannot leak a path, token or sensitive window."""
import contextlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "demo_record", ROOT / "scripts" / "demo" / "record.py")
rec = importlib.util.module_from_spec(_spec)
sys.modules["demo_record"] = rec
_spec.loader.exec_module(rec)

NAMES = ["circle-and-ask", "day-cost", "dictate-a-reply", "draw-and-teach",
         "helper-finishes"]

GOOD = """# t
title: T
length: 30
proof: result=ANSWERED && transcript~cost
## steps
- say 5 "what is the cost"
- wait 2
## captions
readme: a
release: b
omarchy: c
x: d
short: e
"""


class Scripts(unittest.TestCase):
    def test_the_five_scripts_exist_and_load(self):
        found = sorted(p.stem for p in rec.SCRIPTS.glob("*.md"))
        self.assertEqual(found, NAMES)
        for n in NAMES:
            s = rec.load(n)
            self.assertTrue(s["proof"])
            self.assertTrue(30 <= s["length"] <= 60, n)
            self.assertEqual(sorted(s["captions"]), sorted(rec.CHANNELS))
            self.assertTrue(any(st["verb"] in ("say", "run")
                                for st in s["steps"]), n)

    def test_scripts_carry_no_path_or_token(self):
        for p in rec.SCRIPTS.glob("*.md"):
            self.assertEqual(rec.leaks(p.read_text("utf-8")), [], p.name)

    def test_a_script_needs_a_proof_and_every_caption(self):
        for bad, why in ((GOOD.replace("proof: result=ANSWERED && "
                                       "transcript~cost\n", ""), "proof"),
                         (GOOD.replace("x: d\n", ""), "captions"),
                         (GOOD.replace("- wait 2", "- fly 2"), "bad step"),
                         (GOOD.replace('- wait 2', "- run rm -rf /"), "wispd"),
                         (GOOD.replace("transcript~cost", "transcript??"),
                          "proof")):
            with self.assertRaises(rec.DemoError, msg=why):
                rec.parse(bad, "t")
        self.assertEqual(rec.parse(GOOD, "t")["steps"][0]["verb"], "say")


class DryRun(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rec.main(list(argv))
        return code, out.getvalue()

    def test_dry_run_prints_keys_speech_and_capture_and_records_nothing(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(subprocess, "Popen") as popen, \
                mock.patch.object(subprocess, "run") as run:
            code, out = self.run_cli("--dry-run", "draw-and-teach",
                                     "--out", td)
            self.assertEqual(os.listdir(td), [])
        self.assertEqual(code, 0)
        self.assertIn("wf-recorder --audio -f", out)
        self.assertIn("key: wispd trigger start", out)
        self.assertIn("key: wispd trigger stop", out)
        self.assertIn("you say: What does this button do?", out)
        self.assertIn("proof: result=ANSWERED", out)
        popen.assert_not_called()
        run.assert_not_called()

    def test_tts_dry_run_names_the_speech_command(self):
        _, out = self.run_cli("--dry-run", "day-cost", "--tts")
        self.assertIn("espeak-ng", out)

    def test_dry_run_of_every_script_works(self):
        for n in NAMES:
            code, out = self.run_cli("--dry-run", n)
            self.assertEqual(code, 0, n)
            self.assertIn("proof:", out)

    def test_unknown_script_is_an_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(rec.main(["--dry-run", "nope"]), 1)
        self.assertIn("no such script", err.getvalue())


class Proof(unittest.TestCase):
    R = {"turn": "t1", "result": "ANSWERED", "transcript": "What does THIS do",
         "answers": {"route": {"choice": "answer"}}, "timing_ms": {"act": 40}}

    def test_conditions(self):
        ok = lambda s, recs=None: rec.proof_ok(
            s, [self.R] if recs is None else recs)[0]
        self.assertTrue(ok("result=answered"))
        self.assertTrue(ok("transcript~what does this"))
        self.assertTrue(ok("answers.route.choice=answer && result=ANSWERED"))
        self.assertTrue(ok("timing_ms.act>=40"))
        self.assertFalse(ok("result=FAILED"))
        self.assertFalse(ok("transcript~cost"))
        self.assertFalse(ok("answers.route.nope=x"))
        self.assertFalse(ok("result=ANSWERED", []))

    def test_every_condition_must_hold_on_one_turn(self):
        a = dict(self.R, turn="a", transcript="hi")
        b = dict(self.R, turn="b", result="FAILED")
        ok, _ = rec.proof_ok("result=ANSWERED && transcript~what", [a, b])
        self.assertFalse(ok)

    def test_only_decisions_after_the_start_count(self):
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "d.jsonl"
            f.write_text(
                json.dumps({"ts": "2026-01-01T00:00:00+00:00", "n": 1}) + "\n"
                + "garbage\n"
                + json.dumps({"ts": "2026-01-01T01:00:00+00:00", "n": 2}) + "\n")
            from datetime import datetime
            t = datetime.fromisoformat("2026-01-01T00:30:00+00:00").timestamp()
            got = rec.decisions_since(f, t)
        self.assertEqual([r["n"] for r in got], [2])

    def test_a_failed_proof_keeps_nothing(self):
        s = rec.parse(GOOD, "t")
        with tempfile.TemporaryDirectory() as td:
            raw = pathlib.Path(td) / "t.raw.mkv"

            class P:
                def terminate(self): raw.write_bytes(b"x")
                def wait(self, timeout=0): return 0
            with mock.patch.object(rec, "_need"), \
                    mock.patch.object(rec.subprocess, "Popen",
                                      return_value=P()), \
                    mock.patch.object(rec, "_sh"), \
                    mock.patch.object(rec.time, "sleep"), \
                    mock.patch("wisp.redact.rects", return_value=([], True)), \
                    mock.patch.object(rec, "decisions_since", return_value=[]):
                with self.assertRaises(rec.DemoError) as cm:
                    rec.record(s, td)
            self.assertIn("proof failed", str(cm.exception))
            self.assertEqual(os.listdir(td), [])

    def test_unreadable_window_list_stops_the_recording(self):
        s = rec.parse(GOOD, "t")
        with tempfile.TemporaryDirectory() as td:
            class P:
                def terminate(self): pass
                def wait(self, timeout=0): return 0
            with mock.patch.object(rec, "_need"), \
                    mock.patch.object(rec.subprocess, "Popen",
                                      return_value=P()), \
                    mock.patch.object(rec, "_sh"), \
                    mock.patch.object(rec.time, "sleep"), \
                    mock.patch("wisp.redact.rects", return_value=([], False)):
                with self.assertRaises(rec.DemoError) as cm:
                    rec.record(s, td)
        self.assertIn("unblanked", str(cm.exception))


class Redaction(unittest.TestCase):
    def test_scrub_removes_home_paths_and_tokens(self):
        home = os.path.expanduser("~")
        t = (f"saved {home}/notes/x and /home/alice/.ssh/id gh"
             "p_abcdefgh12345 sk-abcdefghijk token=zzzzzzzz")
        out = rec.scrub_text(t)
        self.assertEqual(rec.leaks(out), [])
        self.assertIn("~/notes/x", out)
        self.assertNotIn("alice", out)

    def test_a_caption_that_leaks_is_scrubbed_before_it_is_written(self):
        s = rec.parse(GOOD.replace("readme: a",
                                   "readme: see /home/bob/secret.txt"), "t")
        with tempfile.TemporaryDirectory() as td:
            paths = rec.write_captions(s, td)
            self.assertEqual(len(paths), 5)
            body = pathlib.Path(td, "t.readme.txt").read_text()
        self.assertNotIn("bob", body)

    def test_drawbox_blanks_each_sensitive_rect_for_its_second(self):
        tl = [(0.0, []), (1.0, [(100, 50, 400, 300)]), (2.0, [])]
        f = rec.drawbox_filter(tl, (0, 0, 1920, 1080), (1280, 720))
        self.assertEqual(f.count("drawbox"), 1)
        self.assertIn("x=66:y=33:w=267:h=200", f)
        self.assertIn("between(t,1,2)", f)
        self.assertEqual(rec.drawbox_filter([(0.0, [])], (0, 0, 10, 10),
                                            (10, 10)), "")

    def test_ocr_flags_frames_with_a_path_or_token(self):
        texts = {"a.png": "hello", "b.png": "cat /home/carol/.env",
                 "c.png": "OPENAI token=abcdefgh1"}
        with mock.patch.object(rec.shutil, "which", return_value="/x/t"):
            got = rec.ocr_findings(list(texts), ocr=lambda f: texts[f])
        self.assertEqual([g[0] for g in got], ["b.png", "c.png"])

    def test_without_tesseract_the_check_says_it_did_not_run(self):
        with mock.patch.object(rec.shutil, "which", return_value=None):
            self.assertIsNone(rec.ocr_findings(["a.png"]))


class Readme(unittest.TestCase):
    def test_the_hero_block_is_patched_in_place(self):
        base = "a\n<!-- hero:start -->\n<!-- hero:end -->\nb\n"
        out = rec.patch_readme(base, "draw-and-teach", "Draw")
        self.assertIn("(assets/readme/draw-and-teach.mp4)", out)
        self.assertIn("![Draw](assets/readme/draw-and-teach.poster.png)", out)
        self.assertEqual(rec.patch_readme(out, "draw-and-teach", "Draw"), out)
        with self.assertRaises(rec.DemoError):
            rec.patch_readme("no markers", "x", "y")

    def test_the_real_readme_has_the_markers(self):
        t = (ROOT / "README.md").read_text("utf-8")
        self.assertIn(rec.HERO_START, t)
        self.assertIn(rec.HERO_END, t)


class NothingIsSent(unittest.TestCase):
    def test_no_network_or_send_code_in_the_kit(self):
        src = "\n".join(p.read_text("utf-8") for p in
                        (ROOT / "scripts" / "demo").rglob("*")
                        if p.is_file() and p.suffix in (".py", ".md"))
        for bad in ("urllib", "requests", "http.client", "smtplib", "socket",
                    "webhook", "curl ", "api.twitter", "bsky", "slack"):
            self.assertNotIn(bad, src.lower() if bad == "slack" else src,
                             bad)


if __name__ == "__main__":
    unittest.main()
