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
import urllib.request
import wave
from unittest import mock

from wisp import cancel, config, ledger, notify, platform, speech, tts_groq
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
        self.times = []
        self.blocked = threading.Event()
        self._lock = threading.Lock()

    def __call__(self, req, timeout, token):
        body = json.loads(req.data)
        auth = req.get_header("Authorization")
        with self._lock:
            self.requests.append(body)
            self.times.append(time.time())
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


class _Notices(list):
    """Stands in for notify.send: records (message, level)."""

    def append_notice(self, msg, level="info", **kw):
        self.append((msg, level))
        return "sent"


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
        self.notices = _Notices()
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
            # U7: the one-time notice never reaches a real notifier
            mock.patch.object(tts_groq, "_notified_path",
                              lambda: tmp / "voice_groq_notified.json",
                              create=True),
            mock.patch.object(notify, "send", self.notices.append_notice),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(speech.stop)
        self.addCleanup(tts_groq.reset)
        self.calls = []
        # no worker thread may outlive its test: a straggler would call the
        # next test's stubbed network
        before = set(threading.enumerate())
        self.addCleanup(self._drain, before)

    @staticmethod
    def _drain(before):
        speech.stop()
        for t in set(threading.enumerate()) - before:
            if t.daemon:
                t.join(5)

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

    def test_auto_with_no_key_and_espeak_installed_is_off(self):
        with mock.patch.object(config, "load_env_key", lambda n: ""), \
                mock.patch.object(platform, "tts_binary",
                                  lambda: "espeak-ng"):
            tts_groq.reset()
            self.assertFalse(speech.voice_enabled({"voice": {}}))
            self.assertEqual(speech.backend({"voice": {}})[0], "off")

    def test_auto_with_a_key_is_groq(self):
        with mock.patch.object(config, "load_env_key", lambda n: "k"), \
                mock.patch.object(platform, "tts_binary",
                                  lambda: "espeak-ng"):
            tts_groq.reset()
            cfg = {"voice": {"enabled": "auto"}}
            self.assertTrue(speech.voice_enabled(cfg))
            self.assertEqual(speech.backend(cfg)[0], "groq")

    def test_true_with_no_key_is_espeak(self):
        with mock.patch.object(config, "load_env_key", lambda n: ""), \
                mock.patch.object(platform, "tts_binary",
                                  lambda: "espeak-ng"):
            tts_groq.reset()
            cfg = {"voice": {"enabled": "true"}}
            self.assertTrue(speech.voice_enabled(cfg))
            self.assertEqual(speech.backend(cfg)[0], "espeak")

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

    def test_not_a_wav_is_an_error_but_still_billed(self):
        net = self.net()
        net.steps = [("ok", 100)]
        with mock.patch.object(FakeResp, "read", lambda s, n=-1: b"nope"):
            with self.assertRaises(tts_groq.GroqError) as cm:
                tts_groq.Fetcher(self.cfg()).synth("Hi.")
        self.assertEqual(cm.exception.kind, "bad_audio")
        # Groq billed the 200 response whatever was in it
        self.assertEqual([r["in"] for r in self.rows()], [3])


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
        self.say(sp, "One here. Two there.")
        # the second request went out while the first sentence (800 ms)
        # was still playing
        (start1, ms1), _ = self.played()
        self.assertEqual(ms1, 800)
        self.assertLess(net.times[1], start1 + ms1 / 1000 - 0.2)

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
        self.say(self.speaker(), "Inside the 60 s backoff.")
        self.assertEqual(len(net.requests), 1)
        self.clock[0] += 61
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


KEY = "gsk_FAKEKEYSECRET0123456789"


class ReviewFixTests(GroqCase):
    # -- 1: dead air --------------------------------------------------
    def test_silent_endpoint_hands_over_to_espeak_and_backs_off(self):
        net = self.net(("block",))
        with mock.patch.object(tts_groq, "FIRST_AUDIO_S", 0.3):
            t0 = time.monotonic()
            self.say(self.speaker(), "Hello there.")
            self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(self.spoken(), ["Hello there."])
            self.assertEqual(tts_groq.last_error()["class"], "net")
            self.clock[0] += 30                    # inside the 60 s backoff
            self.say(self.speaker(), "Next turn.")
            self.assertEqual(len(net.requests), 1)
            self.assertIn("Next turn.", self.spoken())
            self.clock[0] += 31
            net.steps = [("ok", 100)]
            self.say(self.speaker(), "After.")
            self.assertEqual(len(net.requests), 2)

    def test_net_and_5xx_back_off_60s_but_4xx_does_not(self):
        for step, wait in ((("err", urllib.error.URLError("down")), 60),
                           (("err", http_error(503)), 60),
                           (("err", http_error(404)), 0)):
            tts_groq.reset()
            tts_groq._state_path().unlink(missing_ok=True)
            self.net(step)
            with self.assertRaises(tts_groq.GroqError):
                tts_groq.Fetcher(self.cfg()).synth("Hi.")
            self.assertEqual(tts_groq.backoff_until(),
                             self.clock[0] + wait if wait else 0.0, step)

    # -- 2: notice delivery -------------------------------------------
    def _notified(self):
        p = pathlib.Path(self.dir.name) / "voice_groq_notified.json"
        return json.loads(p.read_text()) if p.exists() else []

    def _fail401(self):
        self.net(("err", http_error(401, b"{}")))
        with self.assertRaises(tts_groq.GroqError):
            tts_groq.Fetcher(self.cfg()).synth("Hi.")

    def test_quiet_or_disabled_notice_is_not_marked_shown(self):
        for decision in ("quiet", "disabled"):
            tts_groq.reset()
            with mock.patch.object(notify, "send",
                                   lambda *a, d=decision, **k: d):
                self._fail401()
            self.assertEqual(self._notified(), [], decision)
        tts_groq.reset()
        self._fail401()                              # now it can show
        self.assertEqual(len(self.notices), 1)
        self.assertEqual(self._notified(), ["auth"])

    def test_held_notice_counts_as_delivered(self):
        with mock.patch.object(notify, "send", lambda *a, **k: "held"):
            self._fail401()
        self.assertEqual(self._notified(), ["auth"])

    def test_notice_is_reserved_while_sending(self):
        sent = []

        def send(msg, level="info", **kw):
            sent.append(msg)
            if len(sent) == 1:     # a second failure lands mid-delivery
                tts_groq._announce(tts_groq.last_error(), kw.get("cfg"))
            return "sent"
        with mock.patch.object(notify, "send", send):
            self._fail401()
        self.assertEqual(len(sent), 1)

    # -- 3: doctor after recovery -------------------------------------
    def test_doctor_forgets_the_error_after_a_good_synth(self):
        from test_voice_u7 import voice_rows
        self.net(("err", http_error(429, b"{}", {"retry-after": "30"})),
                 ("ok", 100))
        with self.assertRaises(tts_groq.GroqError):
            tts_groq.Fetcher(self.cfg()).synth("Hi.")
        state = pathlib.Path(self.dir.name) / "voice_groq.json"
        self.assertTrue(state.exists())
        self.clock[0] += 31
        tts_groq.Fetcher(self.cfg()).synth("Hi.")
        self.assertIsNone(tts_groq.last_error())
        self.assertFalse(state.exists())
        self.assertIn("none", voice_rows(self.cfg())["groq last error"])
        self.assertEqual(self._notified(), ["rate_limit"])

    # -- 4/5: speaker edges -------------------------------------------
    def test_temp_wav_is_removed_when_no_player_after_all(self):
        made = []
        real = speech.SentenceSpeaker._wav_file

        def wav(data):
            made.append(real(data))
            return made[-1]
        self.net(("ok", 100))
        with mock.patch.object(speech.SentenceSpeaker, "_wav_file",
                               staticmethod(wav)), \
                mock.patch.object(
                    tts_groq, "player_argv",
                    lambda p: [sys.executable, "-c", "pass"]
                    if p == "x" else None):
            self.say(self.speaker(), "Hello there.")
        self.assertEqual(len(made), 1)
        self.assertFalse(pathlib.Path(made[0]).exists())
        self.assertEqual(self.spoken(), ["Hello there."])

    def test_sentence_without_a_job_is_spoken_locally_with_its_points(self):
        sp = self.speaker()
        item = speech._Item("Hello there.", ["p1"])
        sp._say_groq(item, ["p1"])
        self.assertEqual(self.spoken(), ["Hello there."])
        self.assertEqual([c[0] for c in self.calls], [["p1"]])

    def test_wav_file_failure_latches_to_espeak(self):
        self.net(("ok", 100))
        with mock.patch.object(speech.SentenceSpeaker, "_wav_file",
                               staticmethod(lambda data: "")):
            sp = self.speaker()
            self.say(sp, "Hello there.")
        self.assertTrue(sp._groq_off)
        self.assertEqual(self.spoken(), ["Hello there."])

    def test_429_on_the_third_chunk_speaks_only_the_rest_one_point(self):
        sentence = " ".join(["word"] * 90)[:450].rstrip() + "."
        parts = tts_groq.chunks(sentence)
        self.assertEqual(len(parts), 3)
        self.net(("ok", 100), ("ok", 100),
                 ("err", http_error(429, b"{}", {"retry-after": "30"})))
        self.say(self.speaker(), sentence, marks=[(5, "p1")])
        self.assertEqual(len(self.played()), 2)
        self.assertEqual(self.spoken(), [parts[2]])
        self.assertEqual([c[0] for c in self.calls], [["p1"]])

    def test_backoff_landing_before_playback_keeps_the_fetched_audio(self):
        sentence = " ".join(["word"] * 90)[:450].rstrip() + "."
        parts = tts_groq.chunks(sentence)
        self.net(("ok", 100), ("ok", 100),
                 ("err", http_error(429, b"{}", {"retry-after": "30"})))
        real = speech.SentenceSpeaker._ensure_worker
        sp = self.speaker()
        done = threading.Event()
        with mock.patch.object(speech.SentenceSpeaker, "_ensure_worker",
                               lambda self: None):
            sp.finish(sentence, on_done=done.set)
            job = sp._order[0].job
            self.assertTrue(job.finished.wait(10))   # 429 already landed
        self.assertFalse(tts_groq.usable(self.cfg()))
        real(sp)
        self.assertTrue(done.wait(20))
        self.assertEqual(len(self.played()), 2)
        self.assertEqual(self.spoken(), [parts[2]])

    def test_prefetch_racing_a_latch_starts_no_new_request(self):
        net = self.net(("ok", 100))
        sp = self.speaker()
        item = speech._Item("Hello there.", [])
        sp._order.append(item)
        sp._groq_off = True            # latched after _prefetch's check
        with mock.patch.object(speech.SentenceSpeaker, "_groq_ok",
                               lambda self: True):
            sp._prefetch()
        time.sleep(0.2)
        self.assertIsNone(item.job)
        self.assertEqual(net.requests, [])

    def test_a_401_latches_the_turn_and_sends_the_auth_notice_once(self):
        net = self.net(("err", http_error(401, b"{}")))
        self.say(self.speaker(), "One here. Two there. Three more.")
        self.assertEqual(self.spoken(),
                         ["One here.", "Two there.", "Three more."])
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(len(self.notices), 1)
        self.assertIn("rejected the key", self.notices[0][0])

    # -- 6: spend -----------------------------------------------------
    def test_cancel_mid_read_is_still_billed(self):
        f = tts_groq.Fetcher(self.cfg())
        self.net(("ok", 100))

        def read(s, n=-1):
            f.close()
            return make_wav(100)
        with mock.patch.object(FakeResp, "read", read):
            with self.assertRaises(cancel.Cancelled):
                f.synth("Hi there.")
        self.assertEqual([r["in"] for r in self.rows()], [9])

    # -- 7: the key only goes to https, never across a redirect -------
    def test_plain_http_base_url_never_gets_the_key(self):
        net = self.net(("ok", 100))
        cfg = self.cfg(tts_base_url="http://groq.example.test/v1")
        with self.assertRaises(tts_groq.GroqError) as cm:
            tts_groq.Fetcher(cfg).synth("Hi.")
        self.assertEqual(cm.exception.kind, "config")
        self.assertEqual(net.requests, [])
        self.assertEqual(tts_groq.last_error()["class"], "config")
        self.say(self.speaker(cfg), "Local please.")
        self.assertEqual(net.requests, [])
        self.assertEqual(self.spoken(), ["Local please."])

    def test_loopback_http_is_allowed(self):
        net = self.net(("ok", 100))
        tts_groq.Fetcher(self.cfg(
            tts_base_url="http://127.0.0.1:9999/v1")).synth("Hi.")
        self.assertEqual(len(net.requests), 1)

    def test_redirects_are_not_followed(self):
        req = urllib.request.Request("https://api.groq.com/x", data=b"{}",
                                     headers={"Authorization": "Bearer k"})
        h = tts_groq._NoRedirect()
        self.assertIsNone(h.redirect_request(
            req, io.BytesIO(), 307, "moved", {}, "https://evil.test/x"))
        with mock.patch.object(cancel, "urlopen_with") as m:
            tts_groq._open(req, 4, cancel.CancelToken())
        self.assertTrue(any(isinstance(x, tts_groq._NoRedirect)
                            for x in m.call_args.kwargs["handlers"]))

    # -- 8: the key is never recorded ---------------------------------
    def test_the_key_appears_in_no_record_notice_or_doctor_row(self):
        from test_voice_u7 import voice_rows
        echo = json.dumps({"error": {"message": "bad key " + KEY}}).encode()
        cases = {
            "auth": ("err", http_error(401, echo)),
            "net": ("err", urllib.error.URLError("refused " + KEY)),
            "terms": ("err", http_error(400, json.dumps(
                {"error": {"message": "requires terms acceptance " + KEY,
                           "code": "model_terms_required"}}).encode())),
            "rate_limit": ("err", http_error(
                429, echo, {"retry-after": "30"})),
        }
        tmp = pathlib.Path(self.dir.name)
        with mock.patch.object(config, "load_env_key", lambda n: KEY):
            for kind, step in cases.items():
                tts_groq.reset()
                for f in tmp.glob("voice_groq*.json"):
                    f.unlink()
                self.notices.clear()
                self.net(step)
                with self.assertRaises(tts_groq.GroqError) as cm:
                    tts_groq.Fetcher(self.cfg()).synth("Hi.")
                self.assertEqual(cm.exception.kind, kind)
                blobs = [json.dumps(tts_groq.last_error()),
                         str(cm.exception)]
                blobs += [f.read_text() for f in tmp.glob("voice_groq*.json")]
                blobs += [m for m, _ in self.notices]
                blobs += list(voice_rows(self.cfg()).values())
                for b in blobs:
                    self.assertNotIn(KEY, b, kind)


if __name__ == "__main__":
    unittest.main()
