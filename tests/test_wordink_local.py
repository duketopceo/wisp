import http.server
import json
import os
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

from wisp import onboard, stage_capture, wordink_local

TOKEN = "t" * 64
MODELS = [{"id": "whisper_small", "installed": True},
          {"id": "parakeet_v2", "installed": True},
          {"id": "big", "installed": False}]


class Handler(http.server.BaseHTTPRequestHandler):
    seen = []
    models = MODELS
    status = 200

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self._send(401, {})
        if self.path == "/health":
            return self._send(200, {"version": "1", "apiVersion": "2"})
        if self.path.startswith("/models"):
            return self._send(200, type(self).models)
        self._send(404, {})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n)
        type(self).seen.append((self.path, self.headers.get("Content-Type"),
                                body))
        if type(self).status != 200:
            return self._send(type(self).status, {"code": "model-not-ready"})
        self._send(200, {"transcript": " hello   world ", "durationMs": 5})


class Server:
    def __enter__(self):
        Handler.seen, Handler.models, Handler.status = [], MODELS, 200
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.dir = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.dir.name) / "local-api.json"
        self.write()
        return self

    def write(self, **over):
        info = {"port": self.srv.server_address[1], "token": TOKEN,
                "apiVersion": "2", "pid": os.getpid(), **over}
        self.path.write_text(json.dumps(info))

    def __exit__(self, *a):
        self.srv.shutdown()
        self.srv.server_close()
        self.dir.cleanup()


class Find(unittest.TestCase):
    def test_live_app_is_found(self):
        with Server() as s:
            c = wordink_local.find(s.path)
            self.assertTrue(c["base"].startswith("http://127.0.0.1:"))

    def test_missing_stale_wrong_version_or_wrong_token(self):
        self.assertIsNone(wordink_local.find("/nonexistent/local-api.json"))
        with Server() as s:
            s.write(pid=2 ** 22 + 12345)            # no such process
            self.assertIsNone(wordink_local.find(s.path))
            s.write(apiVersion="3")
            self.assertIsNone(wordink_local.find(s.path))
            s.write(token="wrong")                  # /health answers 401
            self.assertIsNone(wordink_local.find(s.path))
            s.path.write_text("not json")
            self.assertIsNone(wordink_local.find(s.path))

    def test_data_dir_per_os(self):
        env = {"HOME": "/h", "XDG_DATA_HOME": "/x"}
        self.assertEqual(str(wordink_local.data_dir(env, "linux")),
                         "/x/wordink")
        self.assertEqual(str(wordink_local.data_dir({"HOME": "/h"}, "linux")),
                         "/h/.local/share/wordink")
        self.assertIn("Application Support",
                      str(wordink_local.data_dir(env, "darwin")))
        self.assertEqual(str(wordink_local.data_dir(
            {"HEX_APPLICATION_SUPPORT_DIR": "/o"}, "linux")), "/o")


class Transcribe(unittest.TestCase):
    def wav(self, d):
        p = pathlib.Path(d) / "u.wav"
        p.write_bytes(b"RIFFfake")
        return p

    def test_posts_wav_to_the_installed_parakeet(self):
        with Server() as s, tempfile.TemporaryDirectory() as d:
            out = wordink_local.transcribe(self.wav(d), {}, path=s.path)
        self.assertEqual(str(out), "hello world")
        path, ctype, body = Handler.seen[0]
        self.assertEqual(path, "/transcriptions?model=parakeet_v2")
        self.assertEqual((ctype, body), ("audio/wav", b"RIFFfake"))

    def test_pinned_language_and_model(self):
        cfg = {"stt": {"language": "es", "wordink_model": "whisper_small"}}
        with Server() as s, tempfile.TemporaryDirectory() as d:
            wordink_local.transcribe(self.wav(d), cfg, path=s.path)
        self.assertEqual(Handler.seen[0][0],
                         "/transcriptions?model=whisper_small&language=es")

    def test_errors_raise_wordinkerror(self):
        with Server() as s, tempfile.TemporaryDirectory() as d:
            Handler.status = 409
            with self.assertRaises(wordink_local.WordinkError) as cm:
                wordink_local.transcribe(self.wav(d), {}, path=s.path)
            self.assertIn("409", str(cm.exception))
            Handler.models = [{"id": "x", "installed": False}]
            with self.assertRaises(wordink_local.WordinkError):
                wordink_local.transcribe(self.wav(d), {}, path=s.path)
            self.assertNotIn(TOKEN, str(cm.exception))
        with self.assertRaises(wordink_local.WordinkError):
            wordink_local.transcribe("x.wav", {},
                                     path="/nonexistent/local-api.json")

    def test_available_needs_an_installed_model(self):
        with Server() as s:
            self.assertTrue(wordink_local.available(s.path))
            Handler.models = [{"id": "x", "installed": False}]
            self.assertFalse(wordink_local.available(s.path))
        self.assertFalse(wordink_local.available("/nonexistent/x.json"))


class Provider(unittest.TestCase):
    CFG = {"stt": {"provider": "wordink"}}

    def test_wordink_local_api_answers_without_the_hosted_stt(self):
        with mock.patch.object(wordink_local, "transcribe",
                               return_value="local words"), \
                mock.patch.object(stage_capture, "_transcribe_openai",
                                  side_effect=AssertionError("cloud")):
            self.assertEqual(stage_capture.transcribe(
                pathlib.Path("u.wav"), self.CFG), "local words")

    def test_failure_falls_back_to_the_hosted_stt(self):
        with mock.patch.object(
                wordink_local, "transcribe",
                side_effect=wordink_local.WordinkError("down")), \
                mock.patch.dict("sys.modules", {"wordink": None}), \
                mock.patch.object(stage_capture, "_transcribe_openai",
                                  return_value="groq") as hosted:
            self.assertEqual(stage_capture.transcribe(
                pathlib.Path("u.wav"), self.CFG), "groq")
        self.assertEqual(hosted.call_args[0][1]["provider"], "openai")

    def test_default_provider_never_touches_wordink(self):
        with mock.patch.object(wordink_local, "transcribe",
                               side_effect=AssertionError("wordink")), \
                mock.patch.object(stage_capture, "_transcribe_openai",
                                  return_value="groq"):
            self.assertEqual(stage_capture.transcribe(
                pathlib.Path("u.wav"), {}), "groq")


class Onboarding(unittest.TestCase):
    def check(self, cfg, found):
        p = onboard.Probes(which=lambda n: "/usr/bin/" + n,
                           whisper_ok=lambda c: True,
                           wordink=lambda: found)
        return onboard.check("mic", cfg, p)

    def test_suggests_when_detected_and_never_requires(self):
        r = self.check({}, True)
        self.assertEqual(r["state"], "ok")
        self.assertIn('provider = "wordink"', r["detail"])

    def test_silent_when_absent_or_already_chosen(self):
        self.assertNotIn("WordInk", self.check({}, False)["detail"])
        self.assertNotIn("WordInk",
                         self.check({"stt": {"provider": "wordink"}},
                                    True)["detail"])





class Deadline(unittest.TestCase):
    def wav(self, d):
        path = pathlib.Path(d) / "u.wav"
        path.write_bytes(b"RIFFfake")
        return path

    def _conn(self):
        return {"base": "http://127.0.0.1:9", "token": TOKEN, "apiVersion": "2"}

    def test_default_timeout_is_under_three_seconds(self):
        self.assertLessEqual(wordink_local.TIMEOUT_S, 3.0)
        self.assertGreater(wordink_local.TIMEOUT_S, 0.2)
        self.assertEqual(wordink_local._timeout_s({}), wordink_local.TIMEOUT_S)
        self.assertEqual(
            wordink_local._timeout_s({"stt": {"wordink_timeout_s": "3"}}), 3.0)
        self.assertEqual(
            wordink_local._timeout_s({"stt": {"wordink_timeout_s": "nope"}}),
            wordink_local.TIMEOUT_S)

    def test_slow_wordink_raises_so_hosted_stt_can_run(self):
        """A hung local API must fail inside the deadline, not wait 30s."""
        def slow_request(*a, **kw):
            import time as _t
            _t.sleep(float(kw.get("timeout", wordink_local.TIMEOUT_S)) + 0.05)
            raise TimeoutError("simulated hang")

        patches = (
            mock.patch.object(wordink_local, "find", return_value=self._conn()),
            mock.patch.object(
                wordink_local, "installed_models",
                return_value=[{"id": "parakeet_v2", "installed": True}]),
            mock.patch.object(wordink_local, "_request", side_effect=slow_request),
        )
        with tempfile.TemporaryDirectory() as d, patches[0], patches[1], patches[2]:
            t0 = __import__("time").monotonic()
            with self.assertRaises(wordink_local.WordinkError) as cm:
                wordink_local.transcribe(self.wav(d), {})
            elapsed = __import__("time").monotonic() - t0
        self.assertIn("deadline", str(cm.exception).lower())
        self.assertLess(elapsed, 5.0)
        self.assertNotIn(TOKEN, str(cm.exception))

    def test_near_deadline_success_is_refused(self):
        """A reply that burns the whole budget still fails over to Groq."""
        def late_ok(conn, path, *, data=None, headers=None, timeout=None,
                    opener=None):
            import time as _t
            _t.sleep(float(timeout))
            return json.dumps({"transcript": "too late"}).encode()

        cfg = {"stt": {"wordink_timeout_s": "0.25"}}
        patches = (
            mock.patch.object(wordink_local, "find", return_value=self._conn()),
            mock.patch.object(
                wordink_local, "installed_models",
                return_value=[{"id": "parakeet_v2", "installed": True}]),
            mock.patch.object(wordink_local, "_request", side_effect=late_ok),
        )
        with tempfile.TemporaryDirectory() as d, patches[0], patches[1], patches[2]:
            with self.assertRaises(wordink_local.WordinkError) as cm:
                wordink_local.transcribe(self.wav(d), cfg)
        self.assertIn("failing over", str(cm.exception).lower())

    def test_timeout_falls_back_to_hosted_in_stage_capture(self):
        err = wordink_local.WordinkError(
            "WordInk exceeded 2.5s first-result deadline")
        patches = (
            mock.patch.object(wordink_local, "transcribe", side_effect=err),
            mock.patch.dict("sys.modules", {"wordink": None}),
            mock.patch.object(stage_capture, "_transcribe_openai",
                              return_value="groq-fast"),
        )
        with patches[0], patches[1], patches[2] as hosted:
            got = stage_capture.transcribe(
                pathlib.Path("u.wav"), {"stt": {"provider": "wordink"}})
            self.assertEqual(got, "groq-fast")
        self.assertEqual(hosted.call_args[0][1]["provider"], "openai")

if __name__ == "__main__":
    unittest.main()
