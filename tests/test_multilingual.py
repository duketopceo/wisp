"""B23: multilingual turns."""
import json
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from harness import runner  # noqa: E402
from wisp import (brain, context, dictate, lang, learn, memory, platform,  # noqa: E402
                  speech, stage_capture, stage_speak, stt_stream, vocab)

FIXTURES = ROOT / "tests" / "fixtures" / "turns"


class TestLang(unittest.TestCase):
    def test_parse(self):
        for raw, want in [("es", "es"), ("ES", "es"), ("pt-BR", "pt-BR"),
                          ("pt_br", "pt-BR"), ("Spanish", "es"),
                          ("japanese", "ja"), ("auto", ""), ("", ""),
                          ("tlh", ""), (None, "")]:
            self.assertEqual(lang.parse(raw), want, raw)

    def test_names_and_english(self):
        self.assertEqual(lang.name("pt-BR"), "Brazilian Portuguese")
        self.assertEqual(lang.name("de"), "German")
        self.assertTrue(lang.is_english(""))
        self.assertTrue(lang.is_english("en-GB"))
        self.assertFalse(lang.is_english("ja"))

    def test_reply_rule_only_for_other_languages(self):
        self.assertEqual(lang.reply_rule(""), "")
        self.assertEqual(lang.reply_rule("en"), "")
        r = lang.reply_rule("es")
        self.assertIn("Reply in Spanish", r)
        self.assertIn("unless they ask for another language", r)

    def test_pinned_language_wins_over_detected(self):
        cfg = {"stt": {"language": "fr"}}
        self.assertEqual(lang.resolve(cfg, "spanish"), "fr")
        self.assertEqual(lang.resolve({}, "spanish"), "es")
        self.assertEqual(lang.resolve({}, ""), "")

    def test_refusals(self):
        self.assertEqual(lang.stt_refusal({}), "")
        self.assertEqual(lang.stt_refusal({"stt": {"language": "es"}}), "")
        self.assertIn("isn't a language", lang.stt_refusal(
            {"stt": {"language": "tlh"}}))
        local = {"stt": {"provider": "local", "language": "de"}}
        self.assertIn("English only", lang.stt_refusal(local))
        local["audio"] = {"whisper_model": "ggml-small.bin"}
        self.assertEqual(lang.stt_refusal(local), "")
        en = {"stt": {"provider": "local", "language": "en"}}
        self.assertEqual(lang.stt_refusal(en), "")


class Req:
    """Capture the multipart body of the transcription request."""

    def __init__(self, replies):
        self.replies, self.bodies = list(replies), []

    def __call__(self, req, timeout=0):
        self.bodies.append(req.data.decode("latin-1"))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        resp = mock.MagicMock()
        resp.__enter__.return_value.read.return_value = json.dumps(r).encode()
        return resp


class TestHostedStt(unittest.TestCase):
    def run_stt(self, cfg, replies):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        wav = pathlib.Path(td.name) / "u.wav"
        wav.write_bytes(b"RIFFxxxx")
        req = Req(replies)
        with mock.patch.object(stage_capture._cancel, "urlopen", req), \
                mock.patch.object(stage_capture.config, "require_key",
                                  lambda k: "k"), \
                mock.patch.object(vocab, "build", lambda c: "Wisp"):
            out = stage_capture._transcribe_openai(
                wav, stage_capture.config.stt_settings(cfg), cfg)
        return out, req.bodies

    def test_auto_asks_the_model_which_language_it_heard(self):
        out, bodies = self.run_stt(
            {"stt": {"language": "auto"}},
            [{"text": " hola  mundo", "language": "spanish"}])
        self.assertEqual((str(out), out.language), ("hola mundo", "spanish"))
        self.assertIn('name="response_format"', bodies[0])
        self.assertIn("verbose_json", bodies[0])
        self.assertNotIn('name="language"', bodies[0])

    def test_pinned_language_is_sent_as_its_base_code(self):
        out, bodies = self.run_stt({"stt": {"language": "pt-BR"}},
                                   [{"text": "oi"}])
        self.assertIn('name="language"\r\n\r\npt\r\n', bodies[0])
        self.assertNotIn("response_format", bodies[0])
        self.assertEqual(out.language, "")

    def test_provider_without_verbose_json_still_transcribes(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, None)
        out, bodies = self.run_stt({}, [err, {"text": "hello"}])
        self.assertEqual(str(out), "hello")
        self.assertEqual(len(bodies), 2)
        self.assertNotIn("response_format", bodies[1])

    def test_pinned_language_the_provider_rejects_is_a_spoken_refusal(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, None)
        with self.assertRaises(lang.Refused) as c:
            self.run_stt({"stt": {"language": "sw"}}, [err])
        self.assertIn("Swahili", str(c.exception))

    def test_streamed_chunks_report_the_longest_chunks_language(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        s = stt_stream.Streamer(pathlib.Path(td.name) / "u.wav",
                                transcribe_fn=lambda p: "")
        s.langs = [(1, "english"), (6, "german")]
        s.texts = ["ja", "das ist ein langer satz"]
        s.enabled = True
        s._thread = None
        s.path.write_bytes(stt_stream.wav_bytes(b"\x00\x00" * 10))
        out = s.finish()
        self.assertEqual(out.language, "german")
        self.assertEqual(str(out), "ja das ist ein langer satz")


class TestLocalWhisper(unittest.TestCase):
    def run_local(self, cfg, stderr=""):
        td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            td, ignore_errors=True))
        binf = td / "whisper"
        binf.write_text("")
        model = td / "m.bin"
        model.write_text("")
        got = {}

        def fake(argv, **kw):
            got["argv"] = argv
            return mock.Mock(stdout=" bonjour ", stderr=stderr)
        with mock.patch.object(stage_capture.config, "WHISPER_BIN", binf), \
                mock.patch.object(stage_capture.config, "whisper_model",
                                  lambda c: model), \
                mock.patch.object(stage_capture._cancel, "run", fake), \
                mock.patch.object(vocab, "build", lambda c: ""), \
                mock.patch.object(stt_stream, "claim", lambda w: None):
            out = stage_capture.transcribe(td / "u.wav", cfg)
        return out, got["argv"]

    def test_english_model_gets_no_language_flag(self):
        out, argv = self.run_local({"stt": {"provider": "local"}})
        self.assertNotIn("-l", argv)
        self.assertEqual(str(out), "bonjour")

    def test_multilingual_model_detects_and_reports(self):
        cfg = {"stt": {"provider": "local"},
               "audio": {"whisper_model": "ggml-small.bin"}}
        out, argv = self.run_local(
            cfg, "whisper_full: auto-detected language: fr (p = 0.97)")
        self.assertEqual(argv[argv.index("-l") + 1], "auto")
        self.assertEqual(out.language, "fr")

    def test_multilingual_model_pinned(self):
        cfg = {"stt": {"provider": "local", "language": "de"},
               "audio": {"whisper_model": "ggml-small.bin"}}
        _out, argv = self.run_local(cfg)
        self.assertEqual(argv[argv.index("-l") + 1], "de")


class TestVoice(unittest.TestCase):
    def setUp(self):
        lang._HAVE.clear()

    def test_english_argv_is_unchanged(self):
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"):
            self.assertEqual(speech._argv("hi", {}), ["espeak-ng", "hi"])
            self.assertEqual(speech._argv("hi", {}, "en"),
                             ["espeak-ng", "hi"])

    def test_espeak_gets_the_language_voice(self):
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"), \
                mock.patch.object(lang, "_espeak_has", return_value=True):
            self.assertEqual(speech._argv("hola", {}, "es"),
                             ["espeak-ng", "-v", "es", "hola"])
            self.assertEqual(speech._argv("oi", {}, "pt-BR"),
                             ["espeak-ng", "-v", "pt-br", "oi"])

    def test_missing_voice_falls_back_to_the_default(self):
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"), \
                mock.patch.object(lang, "_espeak_has", return_value=False):
            self.assertEqual(speech._argv("hola", {}, "es"),
                             ["espeak-ng", "hola"])
            self.assertEqual(speech.voice_for({}, "es"), ("", True))

    def test_configured_voice_wins(self):
        cfg = {"voice": {"lang_voices": "es=es-mx, de=de"}}
        with mock.patch.object(platform, "tts_binary",
                               return_value="espeak-ng"):
            self.assertEqual(speech._argv("hola", cfg, "es"),
                             ["espeak-ng", "-v", "es-mx", "hola"])

    def test_custom_command_placeholders(self):
        cfg = {"voice": {"cmd": "say -v {voice} -l {lang} {text}"}}
        self.assertEqual(
            speech._argv("hola", cfg, "es"),
            ["say", "-v", "es", "-l", "es", "hola"])
        cfg["voice"]["lang_voices"] = "es=Monica"
        self.assertEqual(speech._argv("hola", cfg, "es")[2], "Monica")

    def test_voice_listing_is_parsed(self):
        out = ("Pty Language Age/Gender VoiceName File Other\n"
               " 5  fr-fr  --/M  french  roa/fr  (fr 5)\n"
               " 5  pt-br  --/M  pt-br  roa/pt-BR  (pt 5)\n")
        with mock.patch.object(lang.subprocess, "run",
                               return_value=mock.Mock(stdout=out)):
            self.assertTrue(lang._espeak_has("espeak-ng", "fr"))
            self.assertTrue(lang._espeak_has("espeak-ng", "pt-br"))
            self.assertTrue(lang._espeak_has("espeak-ng", "pt"))
            self.assertFalse(lang._espeak_has("espeak-ng", "de"))

    def test_fallback_is_said_once_per_language(self):
        argvs = []

        class P:
            def __init__(self, argv, **kw):
                argvs.append(argv)

            def wait(self, timeout=None):
                return 0

            def poll(self):
                return 0

            def terminate(self):
                pass
        cfg = {"voice": {"enabled": "true", "cmd": "say {text}"}}
        speech._NOTED.clear()
        for _ in range(2):
            with mock.patch.object(speech.subprocess, "Popen", P):
                sp = speech.SentenceSpeaker(cfg)
                sp.lang = "es"
                sp.finish("Hola mundo.")
                sp._worker.join(3)
        first, second = argvs[0][-1], argvs[1][-1]
        self.assertTrue(first.startswith("I don't have a Spanish voice"))
        self.assertTrue(first.endswith("Hola mundo."))
        self.assertEqual(second, "Hola mundo.")


class TestPrompts(unittest.TestCase):
    def messages(self, **kw):
        got = {}

        def fake(messages, cfg, **k):
            got["m"] = messages
            return {"content": "ok", "provider": "x", "fallback_from": None}
        with mock.patch.object(brain, "chat", fake), \
                mock.patch.object(context, "snapshot", lambda c: ""), \
                mock.patch.object(memory, "context_block", lambda *a: ""):
            stage_speak.ask_chat("hola", {"agent": {}}, **kw)
        return got["m"]

    def test_english_prompt_is_unchanged(self):
        self.assertEqual(self.messages(), self.messages(lang=""))
        self.assertEqual(self.messages(), self.messages(lang="en"))
        self.assertNotIn("Reply in", self.messages()[0]["content"])

    def test_answer_prompt_carries_the_reply_rule(self):
        s = self.messages(lang="de")[0]["content"]
        self.assertIn("The user spoke German. Reply in German", s)

    def test_dictation_keeps_the_spoken_language(self):
        base = dictate._system("cleanup", {}, {}, {})
        self.assertEqual(base, dictate._system("cleanup", {}, {}, {}, "en"))
        ja = dictate._system("cleanup", {}, {}, {}, "ja")
        self.assertIn("in Japanese", ja)
        self.assertIn("never translate", ja)

    def test_dictation_run_passes_the_language_to_the_rewrite(self):
        seen = {}

        def rewrite(mode, text, cfg, win, profile, corr, lang=""):
            seen["lang"] = lang
            return text
        with mock.patch.object(dictate, "rewrite", rewrite), \
                mock.patch.object(dictate, "_maybe_correction",
                                  lambda t: None), \
                mock.patch.object(dictate, "_focused", lambda s: {}), \
                mock.patch.object(dictate, "_read",
                                  lambda: {"corrections": {}}), \
                mock.patch.object(dictate, "insert",
                                  lambda *a: ("paste", "")), \
                mock.patch.object(dictate, "_seen", lambda *a, **k: None), \
                mock.patch.object(dictate, "_send_ok", lambda *a: False):
            dictate.run("wie geht es dir", {}, lang="de")
        self.assertEqual(seen["lang"], "de")


class TestEval(unittest.TestCase):
    def setUp(self):
        td = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(
            td, ignore_errors=True))
        self.dec, self.lab = td / "d.jsonl", td / "l.jsonl"

    def write(self, decs, labs):
        self.dec.write_text("".join(json.dumps(d) + "\n" for d in decs))
        self.lab.write_text("".join(json.dumps(d) + "\n" for d in labs))

    def test_per_language_first_time_correct(self):
        decs = [{"ts": f"t{i}", "result": "ANSWERED", **extra}
                for i, extra in enumerate(
                    [{"lang": "es"}, {"lang": "es"}, {"lang": "es"},
                     {}, {"lang": "de"}])]
        labs = [{"ref": "t0", "label": "correct"},
                {"ref": "t1", "label": "correct"},
                {"ref": "t2", "label": "incorrect"},
                {"ref": "t3", "label": "correct"},
                {"ref": "t4", "label": "correct", "lang": "de"}]
        self.write(decs, labs)
        rep = learn.eval_report({}, self.dec, self.lab)
        self.assertEqual(sorted(rep["langs"]), ["de", "en", "es"])
        self.assertEqual(rep["langs"]["es"]["labelled"], 3)
        self.assertAlmostEqual(rep["langs"]["es"]["rate"], 2 / 3)
        self.assertEqual(rep["langs"]["en"]["rate"], 1.0)
        self.assertIn("by language", learn.eval_text(rep))

    def test_label_lang_overrides_and_english_only_hides_the_table(self):
        self.write([{"ts": "t0", "result": "ANSWERED"}],
                   [{"ref": "t0", "label": "correct"}])
        rep = learn.eval_report({}, self.dec, self.lab)
        self.assertEqual(rep["langs"], {})
        self.assertNotIn("by language", learn.eval_text(rep))
        self.write([{"ts": "t0", "result": "ANSWERED"}],
                   [{"ref": "t0", "label": "incorrect", "lang": "ja"}])
        rep = learn.eval_report({}, self.dec, self.lab)
        self.assertEqual(rep["langs"]["ja"]["incorrect"], 1)

    def test_label_last_records_the_language(self):
        self.write([{"ts": "t9", "result": "ANSWERED"}], [])
        with mock.patch.object(learn.config, "DECISIONS", self.dec), \
                mock.patch.object(learn, "LABELS_FILE", self.lab):
            learn.label_last("correct", "", "pt_br")
        rec = json.loads(self.lab.read_text().splitlines()[-1])
        self.assertEqual((rec["ref"], rec["lang"]), ("t9", "pt-BR"))


class TestReplay(unittest.TestCase):
    CASES = [("lang_es", "es", "Spanish", False),
             ("lang_de", "de", "German", False),
             ("lang_pt_br", "pt-BR", "Brazilian Portuguese", False),
             ("lang_ja", "ja", "Japanese", False),
             ("lang_fr", "fr", "French", False)]

    def test_five_languages(self):
        for name, code, full, fallback in self.CASES:
            with self.subTest(name):
                res = runner.run_turn(FIXTURES / f"{name}.json")
                self.assertEqual(runner.check_expectations(res), [])
                fx = json.loads((FIXTURES / f"{name}.json").read_text())
                self.assertEqual(res.final["transcript"],
                                 fx["endpoints"]["whisper"]["transcript"])
                system = res.chat_calls()[0]["body"]["messages"][0]
                self.assertIn(f"Reply in {full}", system["content"])
                voice = res.trace_events("tts_voice")
                self.assertEqual([(v["lang"], v["fallback"])
                                  for v in voice], [(code, fallback)])

    def test_voice_without_language_support_says_so(self):
        res = runner.run_turn(FIXTURES / "lang_voice_fallback.json")
        self.assertEqual(runner.check_expectations(res), [])
        self.assertTrue(res.trace_events("tts_voice")[0]["fallback"])

    def test_unsupported_language_ends_with_a_spoken_reason(self):
        res = runner.run_turn(FIXTURES / "lang_unsupported.json")
        self.assertEqual(runner.check_expectations(res), [])
        self.assertEqual(res.chat_calls(), [])
        self.assertEqual(res.final["status"], "done")
        self.assertIn("isn't a language", res.final["result"])

    def test_english_turn_is_untouched(self):
        res = runner.run_turn(FIXTURES / "ask.json")
        self.assertEqual(res.trace_events("tts_voice"), [])
        self.assertEqual(res.trace_events("language"), [])
        self.assertNotIn("Reply in", json.dumps(
            res.chat_calls()[0]["body"]["messages"]))


if __name__ == "__main__":
    unittest.main()
