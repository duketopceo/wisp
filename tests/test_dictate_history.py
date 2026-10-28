"""B24: dictated words are never lost, never invented."""
import json
import os
import pathlib
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from wisp import dictate, dictate_history as H, stt_stream as S  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name)
        for name, f in (("FILE", "h.jsonl"), ("JOURNAL", "j.jsonl")):
            p = mock.patch.object(H, name, self.dir / f)
            p.start()
            self.addCleanup(p.stop)
        self.cfg = {}


class TestHistory(Base):
    def test_every_dictation_is_kept_newest_first_with_a_private_mode(self):
        H.add("first words", "inserted", self.cfg, app="kitty", via="typed")
        H.add("second words", "failed", self.cfg, note="no tool")
        got = H.entries()
        self.assertEqual([r["text"] for r in got],
                         ["second words", "first words"])
        self.assertEqual(got[0]["status"], "failed")
        self.assertEqual(stat.S_IMODE(os.stat(H.FILE).st_mode), 0o600)

    def test_count_bound_is_enforced(self):
        cfg = {"dictation": {"history_max": "3"}}
        for i in range(6):
            H.add(f"note {i}", "inserted", cfg)
        self.assertEqual([r["text"] for r in H.entries()],
                         ["note 5", "note 4", "note 3"])

    def test_age_bound_is_enforced(self):
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        H._write([{"ts": old, "status": "inserted", "text": "stale"}])
        H.add("fresh", "inserted", {})
        self.assertEqual([r["text"] for r in H.entries()], ["fresh"])
        cfg = {"dictation": {"history_days": "30"}}
        H._write([{"ts": old, "status": "inserted", "text": "stale"}])
        H.add("fresh", "inserted", cfg)
        self.assertEqual(len(H.entries()), 2)

    def test_defaults_are_100_entries_and_7_days(self):
        s = H.settings({})
        self.assertEqual((s["max"], s["days"], s["enabled"]),
                         (100, 7, True))

    def test_off_switch_keeps_nothing(self):
        cfg = {"dictation": {"history": "false"}}
        self.assertIsNone(H.add("hello", "inserted", cfg))
        self.assertFalse(H.FILE.exists())

    def test_clear_wipes_history_and_journal(self):
        H.add("hello", "inserted", {})
        H.Journal({}).add("half a session")
        self.assertEqual(H.clear(), 1)
        self.assertFalse(H.FILE.exists() or H.JOURNAL.exists())

    def test_retry_target_is_the_newest_that_did_not_land(self):
        H.add("lost one", "failed", {})
        H.add("fine", "inserted", {})
        self.assertEqual(H.get(0, failed_only=True)["text"], "lost one")
        self.assertEqual(H.get(0)["text"], "fine")
        self.assertIsNone(H.get(5))


class TestNothingInvented(unittest.TestCase):
    def test_nothing_said(self):
        for t in ("", "  ", ".", "um", "Um, uh.", "hmm", "you",
                  "Thank you.", "Thanks for watching!"):
            self.assertTrue(H.is_silence(t), t)

    def test_something_said(self):
        for t in ("buy milk", "thank you for the update", "um buy milk",
                  "you there"):
            self.assertFalse(H.is_silence(t), t)

    def test_cleanup_may_drop_and_fix_but_not_add(self):
        said = "um so i wanna send the the report to sam tomorrow"
        self.assertTrue(H.faithful(said, "So I want to send the report to "
                                         "Sam tomorrow."))
        self.assertTrue(H.faithful(said, "Send the report to Sam tomorrow."))
        self.assertFalse(H.faithful(
            said, "I want to send the report to Sam tomorrow. Please let me "
                  "know if you have any questions about the attached "
                  "quarterly figures."))
        self.assertFalse(H.faithful("um", "Hello! How can I help you today?"))

    def test_corrections_may_bring_their_words(self):
        self.assertTrue(H.faithful("open wisp dot ai", "open wisp.ai",
                                   extra=["wisp.ai"]))

    def test_unfaithful_cleanup_falls_back_to_what_was_said(self):
        said = "send the report to sam"
        for reply, kept in [
                ("Send the report to Sam.", "Send the report to Sam."),
                ("Sure! Here is the cleaned text: Send the report to Sam, "
                 "and thank him for his hard work this quarter.", said)]:
            with mock.patch.object(dictate, "_chat",
                                   return_value={"content": reply}):
                got = dictate.rewrite("cleanup", said, {}, {}, {}, {})
            self.assertEqual(got, kept)

    def test_near_silent_tap_inserts_nothing_and_asks_no_model(self):
        with mock.patch.object(dictate, "_chat") as chat, \
                mock.patch.object(dictate, "insert") as ins, \
                mock.patch.object(dictate, "_focused", return_value={}), \
                mock.patch.object(dictate, "_maybe_correction",
                                  return_value=None), \
                mock.patch.object(H, "FILE", pathlib.Path(
                    tempfile.mkdtemp()) / "h.jsonl"):
            for t in ("um", "you", "Thank you."):
                self.assertEqual(dictate.run(t, {}),
                                 "SKIP (nothing was said)")
        chat.assert_not_called()
        ins.assert_not_called()


class TestFailedInsert(Base):
    def run_dictate(self, insert_result, text="remember to call mom"):
        with mock.patch.object(dictate, "insert",
                               return_value=insert_result), \
                mock.patch.object(dictate, "_focused",
                                  return_value={"class": "firefox"}), \
                mock.patch.object(dictate, "_maybe_correction",
                                  return_value=None), \
                mock.patch.object(dictate, "_read",
                                  return_value={"corrections": {}}), \
                mock.patch.object(dictate, "_seen"), \
                mock.patch.object(dictate, "_send_ok", return_value=False), \
                mock.patch.object(dictate, "_chat",
                                  return_value={"content": text}):
            return dictate.run(text, self.cfg)

    def test_failed_insert_keeps_the_words_and_says_so(self):
        res = self.run_dictate(("", "SKIP (no insert path — wtype/wl-copy "
                                    "missing)"))
        self.assertTrue(res.startswith("SKIP (no insert path"))
        self.assertIn("wispd dictate retry", res)
        rec = H.get(0)
        self.assertEqual((rec["text"], rec["status"]),
                         ("remember to call mom", "failed"))

    def test_success_is_kept_too(self):
        self.run_dictate(("typed", ""))
        self.assertEqual(H.get(0)["status"], "inserted")

    def test_try_again_inserts_it(self):
        self.run_dictate(("", "SKIP (no insert path)"))
        rec = H.get(0, failed_only=True)
        with mock.patch.object(dictate, "insert",
                               return_value=("typed", "")) as ins, \
                mock.patch.object(dictate, "_focused",
                                  return_value={"class": "firefox"}), \
                mock.patch.object(dictate.cua_safety, "Guard"):
            out = dictate.retry(rec, self.cfg)
        self.assertTrue(out.startswith("INSERTED: remember to call mom"))
        self.assertEqual(ins.call_args[0][0], "remember to call mom")
        self.assertEqual(H.get(0)["status"], "inserted")
        self.assertIsNone(H.get(0, failed_only=True))

    def test_retry_into_a_terminal_never_sends_newlines(self):
        rec = {"ts": "t", "text": "ls\nrm file"}
        with mock.patch.object(dictate, "insert",
                               return_value=("typed", "")) as ins, \
                mock.patch.object(dictate, "_focused",
                                  return_value={"class": "kitty"}), \
                mock.patch.object(dictate.cua_safety, "Guard"):
            dictate.retry(rec, {})
        self.assertEqual(ins.call_args[0][0], "ls rm file")

    def test_a_failed_paste_leaves_the_clipboard_as_it_was(self):
        calls = []

        def fake_run(argv, input=None, **kw):
            calls.append((argv, input))
            return mock.Mock(returncode=0, stdout=b"")
        for prior, want in (("MY CLIP", ([ "wl-copy"], b"MY CLIP")),
                            (None, (["wl-copy", "--clear"], b""))):
            calls.clear()
            with mock.patch("shutil.which", return_value="/x"), \
                    mock.patch.object(dictate, "_clip_get",
                                      return_value=prior), \
                    mock.patch.object(dictate._cancel, "run", fake_run), \
                    mock.patch.object(dictate, "_input",
                                      return_value="SKIP (no key tool)"):
                self.assertFalse(dictate._paste("my dictation", {}))
            self.assertEqual(calls[0], (["wl-copy"], b"my dictation"))
            self.assertEqual(calls[-1], want)


def tone(seconds):
    one = S.RATE
    import array
    import math
    a = array.array("h", (int(8000 * math.sin(i * 0.3)) for i in range(one)))
    return a.tobytes() * int(seconds)


class TestLongSession(Base):
    def test_a_killed_twelve_minute_session_keeps_the_first_ten(self):
        n = {"i": 0}

        def fn(path):
            n["i"] += 1
            return f"chunk{n['i']}"
        path = self.dir / "u.wav"
        path.write_bytes(S.wav_bytes(tone(11 * 60)))    # minute 11
        s = S.Streamer(path, transcribe_fn=fn, chunk_s=58.0, tick_s=0.001,
                       journal=H.Journal({})).start()
        for _ in range(2000):
            if len(s.texts) >= 10:
                break
            time.sleep(0.01)
        s._stop.set()                  # the process dies: no finish()
        s._thread.join(5)
        self.assertGreaterEqual(s.cut / S.BPS, 10 * 58 - 5)   # >= ~10 min
        self.assertTrue(H.JOURNAL.exists())
        self.assertEqual(stat.S_IMODE(os.stat(H.JOURNAL).st_mode), 0o600)
        text = H.recover({})
        self.assertTrue(text.startswith("chunk1 chunk2"))
        self.assertGreaterEqual(len(text.split()), 10)
        self.assertFalse(H.JOURNAL.exists())
        rec = H.get(0)
        self.assertEqual(rec["status"], "recovered")
        self.assertEqual(H.get(0, failed_only=True)["text"], text)

    def test_a_clean_finish_removes_the_journal(self):
        path = self.dir / "u.wav"
        path.write_bytes(S.wav_bytes(tone(14)))
        s = S.Streamer(path, transcribe_fn=lambda p: "word", chunk_s=6.0,
                       tick_s=0.001, journal=H.Journal({})).start()
        for _ in range(300):
            if s.texts:
                break
            time.sleep(0.01)
        self.assertTrue(H.JOURNAL.exists())
        s.finish()
        self.assertFalse(H.JOURNAL.exists())

    def test_the_next_recording_keeps_an_interrupted_one(self):
        H.Journal({}).add("said before the crash")
        H.Journal({}).start()
        self.assertEqual(H.get(0)["text"], "said before the crash")

    def test_journal_is_off_with_history_off(self):
        j = H.Journal({"dictation": {"history": "false"}})
        j.add("secret")
        self.assertFalse(H.JOURNAL.exists())


class TestNeverInAPrompt(unittest.TestCase):
    def test_only_the_dictate_commands_read_the_history(self):
        users = sorted(p.name for p in (ROOT / "wisp").rglob("*.py")
                       if "dictate_history" in p.read_text()
                       and p.name != "dictate_history.py")
        users += [p.name for p in (ROOT / "wisp" / "cli").glob("*.py")
                  if False]
        self.assertEqual(sorted(set(users)), ["dictate.py", "stt_stream.py"])
        for banned in ("brain.py", "stage_speak.py", "context.py",
                       "memory.py", "stage_route.py", "act.py"):
            self.assertNotIn(banned, users)


if __name__ == "__main__":
    unittest.main()
