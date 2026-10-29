"""U6: Groq Orpheus talk-back. Every request is stubbed (tts_groq._open);
the player is a tiny python child that logs when it starts and sleeps
the WAV's real length. No key, no network, no sound."""
import io
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import wave
from unittest import mock

from wisp import config, ledger, notify, platform, speech, tts_groq
from wisp import voice_polish

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
TERMS = json.loads((FIXTURES / "groq_tts_terms_400.json").read_text())

_PLAYER_CODE = (
    "import sys, time, wave\n"
    "w = wave.open(sys.argv[1]); n = w.getnframes(); r = w.getframerate()\n"
    "open(sys.argv[2], 'a').write('start %f %d\\n' % (time.time(),"
    " round(n * 1000 / r)))\n"
    "time.sleep(n / r)\n")


def make_wav(ms: int, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * (rate * ms // 1000))
    return buf.getvalue()


class PlayerTests(unittest.TestCase):
    def test_pw_play_first_then_paplay_then_aplay(self):
        for have, want in ((("pw-play", "paplay", "aplay"), "pw-play"),
                           (("paplay", "aplay"), "paplay"),
                           (("aplay",), "aplay"), ((), None)):
            with mock.patch.object(platform, "_which",
                                   lambda b, h=have: b in h):
                got = platform.audio_player()
            self.assertEqual(got[0] if got else None, want)


class FakeResp:
    status = 200

    def __init__(self, data: bytes):
        self._data = data
        self.closed = False
        self.headers = {"Content-Type": "audio/wav"}

    def read(self, n=-1):
        return self._data if n < 0 else self._data[:n]

    def close(self):
        self.closed = True


def http_error(code, body=b"", headers=None):
    return urllib.error.HTTPError("https://x/audio/speech", code, "err",
                                  headers or {}, io.BytesIO(body))


class FakeNet:
    """Scripted replacement for tts_groq._open. Each call takes the next
    step: ("ok", ms) | ("err", HTTPError) | ("block",). Past the script,
    ("ok", 300)."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        self.resps = []
        self.tokens = []
        self.blocked = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, req, timeout, token):
        body = json.loads(req.data)
        auth = req.get_header("Authorization")
        with self._lock:
            self.requests.append(body)
            self.tokens.append(token)
            step = self.steps.pop(0) if self.steps else ("ok", 300)
        self.auth = auth
        self.url = req.full_url
        if step[0] == "block":
            self.blocked.set()
            token.wait(10)
            token.check()
        if step[0] == "err":
            raise step[1]
        resp = FakeResp(make_wav(step[1]))
        self.resps.append(resp)
        return resp


class GroqCase(unittest.TestCase):
    """Isolated process state, fake player, fake key, ledger in a tmp dir."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        tmp = pathlib.Path(self.dir.name)
        self.plog = tmp / "player.log"
        self.slog = tmp / "espeak.log"
        script = tmp / "espeak.sh"
        script.write_text(f'#!/bin/sh\necho "$1" >> {self.slog}\nsleep 0.05\n')
        script.chmod(0o755)
        self.espeak = str(script)
        self.usage = tmp / "usage.jsonl"
        self.clock = [1_000_000.0]
        speech.stop()
        tts_groq.reset()
        for p in (
            mock.patch.object(tts_groq, "_now", lambda: self.clock[0]),
            mock.patch.object(config, "load_env_key",
                              lambda name: "test-key"),
            mock.patch.object(
                tts_groq, "player_argv",
                lambda path: [sys.executable, "-c", _PLAYER_CODE, path,
                              str(self.plog)]),
            mock.patch.object(ledger, "path", lambda: self.usage),
            mock.patch.object(ledger, "ACTIVE", True),
            mock.patch.object(tts_groq, "_state_path",
                              lambda: tmp / "voice_groq.json"),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(speech.stop)
        self.addCleanup(tts_groq.reset)
        self.calls = []

    # -- helpers ---------------------------------------------------
    def cfg(self, **voice):
        v = {"enabled": "true", "provider": "groq", "cmd": self.espeak}
        v.update(voice)
        return {"voice": v}

    def net(self, *steps):
        n = FakeNet(*steps)
        p = mock.patch.object(tts_groq, "_open", n)
        p.start()
        self.addCleanup(p.stop)
        return n

    def speaker(self, cfg=None):
        return speech.SentenceSpeaker(
            cfg or self.cfg(),
            on_sentence=lambda pts: self.calls.append(
                (list(pts), time.time())))

    def say(self, sp, full, marks=()):
        done = threading.Event()
        sp.finish(full, on_done=done.set, marks=marks)
        self.assertTrue(done.wait(timeout=20), "speaker never finished")

    def played(self):
        if not self.plog.exists():
            return []
        out = []
        for line in self.plog.read_text().splitlines():
            _, ts, ms = line.split()
            out.append((float(ts), int(ms)))
        return out

    def spoken(self):
        return self.slog.read_text().splitlines() \
            if self.slog.exists() else []

    def rows(self):
        if not self.usage.exists():
            return []
        return [json.loads(x) for x in self.usage.read_text().splitlines()]


class ChunkTests(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(tts_groq.chunks("Wisp is on."), ["Wisp is on."])

    def test_450_chars_become_three_chunks_of_at_most_200(self):
        text = " ".join(["word"] * 90)[:450].rstrip()
        out = tts_groq.chunks(text)
        self.assertEqual(len(out), 3)
        self.assertTrue(all(len(c) <= 200 for c in out), [len(c) for c in out])
        self.assertEqual(" ".join(out).split(), text.split())

    def test_long_sentence_splits_at_a_clause_break(self):
        a = "First we open the settings panel and look for the display tab"
        b = "then we pick the monitor and drag the slider to the right until it looks good"
        c = "and finally we press apply so the change sticks for the whole desktop session"
        text = f"{a}, {b}, {c}"
        self.assertGreater(len(text), 200)
        out = tts_groq.chunks(text)
        self.assertTrue(all(len(x) <= 200 for x in out))
        self.assertTrue(out[0].endswith(","), out)

    def test_unbroken_run_is_hard_cut(self):
        out = tts_groq.chunks("x" * 450)
        self.assertEqual([len(c) for c in out], [200, 200, 50])


class WavTests(unittest.TestCase):
    def test_duration_from_header(self):
        self.assertEqual(tts_groq.wav_ms(make_wav(300)), 300)

    def test_placeholder_data_size_falls_back_to_byte_count(self):
        data = bytearray(make_wav(500))
        i = data.index(b"data")
        data[i + 4:i + 8] = (0xFFFFFFFF).to_bytes(4, "little")
        self.assertEqual(tts_groq.wav_ms(bytes(data)), 500)

    def test_not_a_wav_raises(self):
        with self.assertRaises(ValueError):
            tts_groq.wav_ms(b"<html>nope</html>")


class ClassifyTests(unittest.TestCase):
    def test_recorded_terms_400(self):
        e = tts_groq.classify(TERMS["status"], {},
                              json.dumps(TERMS["body"]).encode())
        self.assertEqual(e.kind, "terms")
        self.assertIn("console.groq.com/playground", e.detail)

    def test_terms_matched_by_message_alone(self):
        body = json.dumps({"error": {"message": "The model `m` requires "
                                     "terms acceptance."}}).encode()
        self.assertEqual(tts_groq.classify(400, {}, body).kind, "terms")

    def test_429_carries_retry_after(self):
        e = tts_groq.classify(429, {"retry-after": "42"}, b"{}")
        self.assertEqual((e.kind, e.retry_after), ("rate_limit", 42.0))

    def test_429_without_header_gets_a_default(self):
        self.assertGreater(tts_groq.classify(429, {}, b"").retry_after, 0)

    def test_auth_and_server_errors(self):
        self.assertEqual(tts_groq.classify(401, {}, b"").kind, "auth")
        self.assertEqual(tts_groq.classify(503, {}, b"").kind, "http")
        self.assertEqual(tts_groq.classify(400, {}, b"{}").kind, "http")


class VoiceModeTests(GroqCase):
    """speech, voice_polish and notify read the one helper."""

    def modes(self, value):
        cfg = {"voice": {"enabled": value}}
        sp = speech.SentenceSpeaker(cfg)
        self.addCleanup(sp.stop)
        notifier = _notifier(cfg)
        return {"helper": speech.voice_enabled(cfg),
                "speaker": sp.enabled,
                "polish": voice_polish.voice_on(cfg),
                "notify": notifier.send("ans", spoken=True) == "spoken"}

    def test_true_false_auto_agree_everywhere(self):
        with mock.patch.object(platform, "tts_binary", lambda: None):
            for value, with_key, want in (
                    ("true", False, True), ("false", True, False),
                    ("auto", True, True), ("auto", False, False)):
                tts_groq.reset()
                with mock.patch.object(
                        config, "load_env_key",
                        lambda name, k=with_key: "k" if k else ""):
                    got = self.modes(value)
                self.assertEqual(
                    set(got.values()), {want}, (value, with_key, got))

    def test_auto_falls_back_to_espeak_when_no_key(self):
        with mock.patch.object(config, "load_env_key", lambda n: ""), \
                mock.patch.object(platform, "tts_binary",
                                  lambda: "espeak-ng"):
            tts_groq.reset()
            self.assertTrue(speech.voice_enabled({"voice": {}}))

    def test_missing_setting_means_auto(self):
        with mock.patch.object(platform, "tts_binary", lambda: None):
            self.assertTrue(speech.voice_enabled({}))          # key present
            tts_groq.reset()
            with mock.patch.object(config, "load_env_key", lambda n: ""):
                self.assertFalse(speech.voice_enabled({}))

    def test_key_lookup_is_cached(self):
        calls = []
        with mock.patch.object(config, "load_env_key",
                               lambda n: calls.append(n) or "k"):
            tts_groq.reset()
            for _ in range(5):
                speech.voice_enabled({"voice": {"enabled": "auto"}})
        self.assertEqual(len(calls), 1)


def _notifier(cfg):
    return notify.Notifier(cfg=cfg, sync=True, runner=lambda *a, **k: (0, ""),
                           monitor=lambda secs: iter(()))


class SynthTests(GroqCase):
    def test_request_shape_and_one_usage_row_priced_by_characters(self):
        net = self.net(("ok", 300))
        f = tts_groq.Fetcher(self.cfg())
        a = f.synth("Wisp is on.")
        self.assertEqual(a.ms, 300)
        self.assertEqual(net.requests, [{
            "model": "canopylabs/orpheus-v1-english", "voice": "hannah",
            "input": "Wisp is on.", "response_format": "wav"}])
        self.assertTrue(net.url.endswith("/openai/v1/audio/speech"))
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["provider"], rows[0]["paid"]),
                         ("groq", True))
        self.assertAlmostEqual(rows[0]["usd"], 11 * 22 / 1_000_000, 8)
        self.assertEqual(rows[0]["in"], 11)

    def test_configured_voice_and_model_are_sent(self):
        net = self.net(("ok", 100))
        tts_groq.Fetcher(self.cfg(tts_voice="troy", tts_model="m-x")
                         ).synth("Hi.")
        self.assertEqual((net.requests[0]["voice"], net.requests[0]["model"]),
                         ("troy", "m-x"))

    def test_terms_error_records_class_and_a_one_hour_backoff(self):
        self.net(("err", http_error(
            400, json.dumps(TERMS["body"]).encode())))
        with self.assertRaises(tts_groq.GroqError) as cm:
            tts_groq.Fetcher(self.cfg()).synth("Hi.")
        self.assertEqual(cm.exception.kind, "terms")
        rec = tts_groq.last_error()
        self.assertEqual(rec["class"], "terms")
        self.assertEqual(rec["until"], self.clock[0] + 3600)
        self.assertFalse(tts_groq.usable(self.cfg()))
        self.clock[0] += 3601
        self.assertTrue(tts_groq.usable(self.cfg()))     # re-probes itself
        self.assertEqual(self.rows(), [])                # not billed

    def test_rate_limit_backoff_honors_retry_after(self):
        self.net(("err", http_error(429, b"{}", {"retry-after": "90"})))
        with self.assertRaises(tts_groq.GroqError):
            tts_groq.Fetcher(self.cfg()).synth("Hi.")
        self.assertEqual(tts_groq.backoff_until(), self.clock[0] + 90)
        self.clock[0] += 89
        self.assertFalse(tts_groq.usable(self.cfg()))
        self.clock[0] += 2
        self.assertTrue(tts_groq.usable(self.cfg()))

    def test_error_record_is_readable_by_another_process(self):
        self.net(("err", http_error(
            400, json.dumps(TERMS["body"]).encode())))
        with self.assertRaises(tts_groq.GroqError):
            tts_groq.Fetcher(self.cfg()).synth("Hi.")
        tts_groq._LAST = None            # a fresh process: only the file
        self.assertEqual(tts_groq.last_error()["class"], "terms")

    def test_spend_cap_blocks_before_any_request(self):
        net = self.net(("ok", 100))
        cfg = self.cfg()
        cfg["budget"] = {"daily_usd": "0"}
        with self.assertRaises(tts_groq.GroqError) as cm:
            tts_groq.Fetcher(cfg).synth("Hi.")
        self.assertEqual(cm.exception.kind, "budget")
        self.assertEqual(net.requests, [])

    def test_not_a_wav_is_an_error_and_not_billed(self):
        net = self.net()
        net.steps = [("ok", 100)]
        with mock.patch.object(FakeResp, "read", lambda s, n=-1: b"nope"):
            with self.assertRaises(tts_groq.GroqError) as cm:
                tts_groq.Fetcher(self.cfg()).synth("Hi.")
        self.assertEqual(cm.exception.kind, "bad_audio")
        self.assertEqual(self.rows(), [])


class SpeakerTests(GroqCase):
    def test_two_sentences_two_wavs_in_order_second_point_at_its_audio(self):
        net = self.net(("ok", 300), ("ok", 200))
        text = "Open Settings first. Then click Display."
        sp = self.speaker()
        seen = []
        sp._on_sentence = lambda pts: (
            self.calls.append((list(pts), time.time())),
            seen.append(sp.sentence_ms))
        self.say(sp, text, marks=[(19, "p1"), (39, "p2")])
        self.assertEqual([r["input"] for r in net.requests],
                         ["Open Settings first.", "Then click Display."])
        self.assertEqual([ms for _, ms in self.played()], [300, 200])
        self.assertEqual([c[0] for c in self.calls], [["p1"], ["p2"]])
        # timed from the WAV header, not the espeak word estimate
        self.assertEqual(seen, [300, 200])
        start1, start2 = (t for t, _ in self.played())
        t1, t2 = (c[1] for c in self.calls)
        self.assertAlmostEqual(t1, start1, delta=0.4)
        self.assertAlmostEqual(t2, start2, delta=0.4)
        self.assertGreaterEqual(t2 - t1, 0.28)
        self.assertEqual(self.spoken(), [])

    def test_next_sentence_is_fetched_while_the_current_one_plays(self):
        net = self.net(("ok", 800), ("ok", 100))
        sp = self.speaker()
        sp.feed("One here. Two there. ", [])
        deadline = time.time() + 5
        while time.time() < deadline and len(net.requests) < 2:
            time.sleep(0.02)
        self.assertEqual(len(net.requests), 2)
        # the second request went out before the first sentence finished
        self.assertEqual(len(self.played()) <= 1, True)
        self.say(sp, "One here. Two there.")

    def test_450_char_sentence_becomes_three_requests(self):
        net = self.net(("ok", 100), ("ok", 100), ("ok", 100))
        sentence = " ".join(["word"] * 90)[:450].rstrip() + "."
        sp = self.speaker()
        self.say(sp, sentence)
        self.assertEqual(len(net.requests), 3)
        self.assertTrue(all(len(r["input"]) <= 200 for r in net.requests))
        self.assertEqual(len(self.played()), 3)

    def test_stop_during_a_fetch_closes_the_request_and_never_plays(self):
        net = self.net(("block",))
        sp = self.speaker()
        sp.feed("Hello there you. ", [])
        self.assertTrue(net.blocked.wait(5))
        sp.stop()
        time.sleep(0.4)
        self.assertEqual(self.played(), [])
        self.assertTrue(net.tokens[0].cancelled)
        self.assertIsNone(speech._PROC)

    def test_stop_drops_prefetched_audio_and_closes_responses(self):
        net = self.net(("ok", 1500), ("ok", 300))
        sp = self.speaker()
        sp.feed("One here. Two there. ", [])
        deadline = time.time() + 5
        while time.time() < deadline and not (
                len(net.resps) >= 2 and self.played()):
            time.sleep(0.02)
        sp.stop()
        time.sleep(0.4)
        self.assertEqual(len(self.played()), 1)         # never played #2
        self.assertTrue(all(r.closed for r in net.resps))

    def test_barge_in_kills_the_player_within_150ms(self):
        self.net(("ok", 5000))
        sp = self.speaker()
        sp.feed("A long answer here. ", [])
        deadline = time.time() + 5
        while time.time() < deadline and not (
                speech.is_speaking() and self.played()):
            time.sleep(0.01)
        self.assertTrue(speech.is_speaking())
        proc = speech._PROC
        t = time.monotonic()
        speech.stop()
        proc.wait(timeout=2)
        self.assertLess(time.monotonic() - t, 0.15)
        self.assertFalse(speech.is_speaking())

    def test_429_mid_answer_finishes_in_espeak_and_skips_groq_until_retry(self):
        net = self.net(("ok", 100),
                       ("err", http_error(429, b"{}", {"retry-after": "30"})))
        sp = self.speaker()
        self.say(sp, "One here. Two there. Three more.")
        self.assertEqual(len(net.requests), 2)           # sentence 3: none
        self.assertEqual(len(self.played()), 1)
        self.assertEqual(self.spoken(), ["Two there.", "Three more."])
        # the next turn is inside the backoff: no request at all
        sp2 = self.speaker()
        self.say(sp2, "Next turn.")
        self.assertEqual(len(net.requests), 2)
        self.assertIn("Next turn.", self.spoken())
        self.clock[0] += 31
        sp3 = self.speaker()
        self.say(sp3, "After the wait.")
        self.assertEqual(len(net.requests), 3)

    def test_terms_error_speaks_in_espeak_and_retries_after_the_backoff(self):
        net = self.net(("err", http_error(
            400, json.dumps(TERMS["body"]).encode())))
        sp = self.speaker()
        self.say(sp, "Hello there.")
        self.assertEqual(self.spoken(), ["Hello there."])
        self.assertEqual(tts_groq.last_error()["class"], "terms")
        self.say(self.speaker(), "Still waiting.")
        self.assertEqual(len(net.requests), 1)
        self.clock[0] += 3601
        self.say(self.speaker(), "Back again.")
        self.assertEqual(len(net.requests), 2)
        self.assertEqual(len(self.played()), 1)

    def test_other_failure_latches_the_turn_but_the_next_turn_retries(self):
        net = self.net(("err", http_error(500)))
        self.say(self.speaker(), "One here. Two there. Three more.")
        self.assertEqual(self.spoken(),
                         ["One here.", "Two there.", "Three more."])
        # requests go out one sentence at a time: the failure of the
        # first stops the rest before any is sent
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(self.played(), [])
        net.steps = [("ok", 100)]
        self.say(self.speaker(), "Fresh turn.")                  # retries
        self.assertEqual(len(net.requests), 2)
        self.assertEqual(len(self.played()), 1)

    def test_points_still_fire_when_groq_fails(self):
        self.net(("err", http_error(500)))
        sp = self.speaker()
        self.say(sp, "One here. Two there.", marks=[(8, "p1"), (19, "p2")])
        self.assertEqual([c[0] for c in self.calls], [["p1"], ["p2"]])

    def test_spend_cap_means_no_request_and_espeak_speaks(self):
        net = self.net(("ok", 100))
        cfg = self.cfg()
        cfg["budget"] = {"daily_usd": "0"}
        self.say(self.speaker(cfg), "Over the cap.")
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["Over the cap."])

    def test_each_request_writes_one_usage_row(self):
        self.net(("ok", 100), ("ok", 100))
        self.say(self.speaker(), "One here. Two there.")
        rows = self.rows()
        self.assertEqual([r["in"] for r in rows], [9, 10])
        self.assertAlmostEqual(sum(r["usd"] for r in rows),
                               19 * 22 / 1_000_000, 8)

    def test_muted_speaker_makes_no_request(self):
        net = self.net(("ok", 100))
        d = voice_polish.begin(
            self.cfg(), runner=lambda argv, **k: (0, "Volume: 0.5 [MUTED]"))
        self.assertTrue(d.muted)
        sp = speech.SentenceSpeaker(d.cfg)
        self.say(sp, "Nobody hears this.")
        self.assertEqual(net.requests, [])
        self.assertEqual(self.played(), [])
        self.assertEqual(self.spoken(), [])

    def test_spanish_turn_uses_espeak(self):
        net = self.net(("ok", 100))
        sp = self.speaker()
        sp.lang = "es"
        self.say(sp, "Hola, amigo.")
        self.assertEqual(net.requests, [])
        self.assertEqual(len(self.spoken()), 1)

    def test_no_key_means_espeak(self):
        net = self.net(("ok", 100))
        with mock.patch.object(config, "load_env_key", lambda n: ""):
            tts_groq.reset()
            self.say(self.speaker(), "No key here.")
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["No key here."])

    def test_provider_espeak_never_asks_groq(self):
        net = self.net(("ok", 100))
        self.say(self.speaker(self.cfg(provider="espeak")), "Local only.")
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["Local only."])

    def test_first_audio_callback_reports_ms_from_first_sentence(self):
        self.net(("ok", 100))
        got = []
        sp = speech.SentenceSpeaker(self.cfg(), on_audio=got.append)
        self.say(sp, "Timed start.")
        self.assertEqual(len(got), 1)
        self.assertIsInstance(got[0], int)


if __name__ == "__main__":
    unittest.main()
