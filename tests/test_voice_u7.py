"""U7: the doctor voice row, the one-time Groq notice, and one voice for
speech.speak (R13, R18). Network and player stubbed; no key, no sound."""
import json
import time
import unittest
from unittest import mock

from wisp import config, ledger, speech, tts_groq
from wisp.cli import diagnose

from test_tts_groq import GroqCase, TERMS, http_error

LINK = ("https://console.groq.com/playground"
        "?model=canopylabs%2Forpheus-v1-english")


def terms_err():
    return ("err", http_error(400, json.dumps(TERMS["body"]).encode()))


def trip(case, step, text="Hi."):
    case.net(step)
    try:
        tts_groq.Fetcher(case.cfg()).synth(text)
    except tts_groq.GroqError:
        pass


def voice_rows(cfg):
    rows = []
    diagnose._voice_rows(lambda n, v, ok=True: rows.append((n, v, ok)), cfg)
    return {n: v for n, v, _ in rows}


class DoctorRowTests(GroqCase):
    def test_no_error_says_groq_and_no_retry_pending(self):
        got = voice_rows(self.cfg())
        self.assertTrue(got["voice backend"].startswith("groq"), got)
        self.assertIn("none", got["groq last error"])
        self.assertIn("now", got["groq retry"])

    def test_terms_error_shows_fix_link_and_espeak(self):
        trip(self, terms_err())
        got = voice_rows(self.cfg())
        self.assertTrue(got["voice backend"].startswith("cmd"), got)
        self.assertIn("terms", got["groq last error"])
        self.assertIn(LINK, got["groq last error"])
        self.assertIn(tts_groq.fmt_time(self.clock[0] + 3600),
                      got["groq retry"])

    def test_rate_limit_shows_end_time(self):
        trip(self, ("err", http_error(429, b"{}", {"retry-after": "90"})))
        got = voice_rows(self.cfg())
        end = tts_groq.fmt_time(self.clock[0] + 90)
        self.assertIn("rate_limit", got["groq last error"])
        self.assertIn(end, got["groq last error"])
        self.assertIn(end, got["groq retry"])

    def test_read_from_the_file_without_a_network_call(self):
        trip(self, terms_err())
        tts_groq._LAST = None            # a fresh doctor process
        tts_groq._UNTIL, tts_groq._LOADED = 0.0, False
        with mock.patch.object(tts_groq, "_open", side_effect=AssertionError):
            got = voice_rows(self.cfg())
        self.assertIn("terms", got["groq last error"])

    def test_off_and_local_backends(self):
        self.assertEqual(speech.backend({"voice": {
            "enabled": "false"}})[0], "off")
        self.assertEqual(speech.backend(self.cfg(provider="espeak"))[0],
                         "cmd")


class DoctorAutoNoKeyTests(GroqCase):
    def test_auto_with_no_key_reads_off_and_why(self):
        with mock.patch.object(config, "load_env_key", lambda n: ""):
            tts_groq.reset()
            got = voice_rows({"voice": {"enabled": "auto"}})
        self.assertTrue(got["voice backend"].startswith("off"), got)
        self.assertIn("no Groq key", got["voice backend"])


class NoticeTests(GroqCase):
    def test_terms_notice_has_link_and_espeak_and_fires_once(self):
        trip(self, terms_err())
        self.assertEqual(len(self.notices), 1)
        msg = self.notices[0][0]
        self.assertIn(LINK, msg)
        self.assertIn("espeak", msg)
        self.clock[0] += 3601
        trip(self, terms_err())          # same class, next turn
        self.assertEqual(len(self.notices), 1)

    def test_each_class_fires_once(self):
        trip(self, terms_err())
        self.clock[0] += 3601
        trip(self, ("err", http_error(429, b"{}", {"retry-after": "90"})))
        self.clock[0] += 91
        trip(self, ("err", http_error(401, b"{}")))
        trip(self, ("err", http_error(429, b"{}", {"retry-after": "90"})))
        self.assertEqual(len(self.notices), 3)

    def test_a_restart_does_not_repeat_it(self):
        trip(self, terms_err())
        tts_groq.reset()                 # a new daemon process
        self.clock[0] += 3601
        trip(self, terms_err())
        self.assertEqual(len(self.notices), 1)

    def test_no_notice_outside_the_daemon(self):
        with mock.patch.object(ledger, "ACTIVE", False):
            trip(self, terms_err())
        self.assertEqual(self.notices, [])


class SpeakTests(GroqCase):
    def test_speak_uses_groq_when_the_helper_says_groq(self):
        net = self.net(("ok", 200))
        proc = speech.speak("Opened the settings.", self.cfg())
        proc.wait(timeout=20)
        self.assertEqual(len(net.requests), 1, net.requests)
        self.assertEqual(net.requests[0]["input"], "Opened the settings.")
        self.assertEqual(len(self.played()), 1)
        self.assertEqual(self.spoken(), [])
        self.assertIsNotNone(proc.poll())

    def test_speak_returns_at_once_without_waiting_for_the_network(self):
        net = self.net(("block",))
        t0 = time.monotonic()
        proc = speech.speak("Slow.", self.cfg())
        self.assertLess(time.monotonic() - t0, 0.5)
        self.assertIsNone(proc.poll())
        self.assertTrue(speech.is_speaking())
        # let the request reach the (stubbed) network before stopping, so
        # no worker outlives the test and hits the next test's stub
        self.assertTrue(net.blocked.wait(5))
        speech.stop()
        proc.wait(timeout=5)

    def test_a_fast_player_is_not_killed_by_speak_replacing_the_old_proc(self):
        self.net(("ok", 1500))
        real = speech.SentenceSpeaker.finish

        def finish(sp, *a, **k):
            real(sp, *a, **k)
            deadline = time.time() + 5          # the worker wins the race
            while not self.played() and time.time() < deadline:
                time.sleep(0.01)
        with mock.patch.object(speech.SentenceSpeaker, "finish", finish):
            proc = speech.speak("Race me.", self.cfg())
        proc.wait(timeout=20)
        # a killed player would end the call at once, not after 1.5 s
        self.assertGreater(time.time() - self.played()[0][0], 1.2)
        self.assertEqual(self.spoken(), [])

    def test_failure_falls_back_to_espeak(self):
        self.net(("err", http_error(500, b"{}")))
        proc = speech.speak("Fallback line.", self.cfg())
        proc.wait(timeout=20)
        self.assertEqual(self.spoken(), ["Fallback line."])
        self.assertEqual(self.played(), [])

    def test_backoff_goes_straight_to_espeak(self):
        trip(self, ("err", http_error(429, b"{}", {"retry-after": "90"})))
        net = self.net()
        proc = speech.speak("Waiting.", self.cfg())
        proc.wait(timeout=20)
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["Waiting."])

    def test_no_key_speaks_espeak(self):
        net = self.net()
        with mock.patch.object(config, "load_env_key", lambda n: ""):
            tts_groq.reset()
            proc = speech.speak("No key.", self.cfg())
            proc.wait(timeout=20)
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["No key."])

    def test_stop_aborts_the_request_and_nothing_plays(self):
        net = self.net(("block",))
        proc = speech.speak("Stop me.", self.cfg())
        self.assertTrue(net.blocked.wait(5))
        t0 = time.monotonic()
        speech.stop()
        proc.wait(timeout=5)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(self.played(), [])
        self.assertEqual(self.spoken(), [])

    def test_stop_kills_the_playing_audio(self):
        self.net(("ok", 5000))
        proc = speech.speak("Long one.", self.cfg())
        deadline = time.time() + 10
        while not self.played() and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.played()), 1)
        t0 = time.monotonic()
        speech.stop()
        proc.wait(timeout=5)
        self.assertLess(time.monotonic() - t0, 1.0)
        self.assertFalse(speech.is_speaking())


if __name__ == "__main__":
    unittest.main()
