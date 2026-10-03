"""U6 brain providers — parsing, capability gating, wire shapes."""
import io
import json
import pathlib
import unittest
import unittest.mock as mock

from wisp import brain, agents


class ProviderTest(unittest.TestCase):
    def test_default_parsing(self):
        p = brain.provider({"brain": {"default": "ollama:llama3.1"}})
        self.assertEqual(p["name"], "ollama")
        self.assertEqual(p["model"], "llama3.1")
        self.assertEqual(p["kind"], "ollama")
        self.assertEqual(p["base_url"], "http://localhost:11434")

    def test_fallback_legacy_answer_model(self):
        p = brain.provider({"agent": {"answer_model": "foo/bar"}})
        self.assertEqual(p["name"], "openrouter")
        self.assertEqual(p["model"], "foo/bar")
        self.assertTrue(brain.supports_vision(
            {"agent": {"answer_model": "x"}}))

    def test_custom_section_overrides(self):
        cfg = {"brain": {"default": "vllm:qwen"},
               "brain.vllm": {"kind": "openai_compat",
                              "base_url": "http://gpu:8000/v1",
                              "key_env": "", "vision": "true"}}
        p = brain.provider(cfg)
        self.assertEqual(p["base_url"], "http://gpu:8000/v1")
        self.assertTrue(brain.supports_vision(cfg))

    def test_name_only_default_uses_legacy_model(self):
        p = brain.provider({"brain": {"default": "lmstudio"},
                            "agent": {"answer_model": "m"}})
        self.assertEqual(p["name"], "lmstudio")
        self.assertEqual(p["model"], "m")


def _fake_resp(payload: dict):
    return io.BytesIO(json.dumps(payload).encode())


class ChatTest(unittest.TestCase):
    def _capture(self):
        captured = {}
        def fake(req, timeout=60):
            if isinstance(req, str):  # probe GET — succeeds silently
                return _fake_resp({"tags": [], "models": []})
            captured["url"] = req.full_url
            captured["headers"] = dict(req.header_items())
            captured["body"] = json.loads(req.data)
            return _fake_resp({"choices": [{"message":
                                           {"content": "ok"}}],
                               "message": {"content": "ok"},
                               "done": True})
        return captured, mock.patch.object(
            brain.urllib.request, "urlopen", fake)

    def test_openai_compat_wire(self):
        cfg = {"brain": {"default": "vllm:q"},
               "brain.vllm": {"kind": "openai_compat",
                              "base_url": "http://gpu:8000/v1"}}
        captured, p = self._capture()
        with p:
            out = brain.chat([{"role": "user", "content": "hi"}], cfg)
        self.assertEqual(out["content"], "ok")
        self.assertEqual(captured["url"],
                         "http://gpu:8000/v1/chat/completions")
        self.assertNotIn("Authorization", captured["headers"])  # keyless

    def test_ollama_native_wire(self):
        cfg = {"brain": {"default": "ollama:llama3.2-vision"},
               "brain.ollama": {"vision": "true"}}
        captured, p = self._capture()
        with p:
            out = brain.chat(
                [{"role": "user",
                  "content": [{"type": "text", "text": "look"},
                              {"type": "image_url", "image_url":
                               {"url": "data:image/png;base64,AA=="}}]}],
                cfg)
        self.assertEqual(captured["url"],
                         "http://localhost:11434/api/chat")
        msg = captured["body"]["messages"][0]
        self.assertEqual(msg["content"], "look")
        self.assertEqual(msg["images"], ["AA=="])
        self.assertEqual(out["content"], "ok")

    def test_ollama_probe_failure_explicit(self):
        cfg = {"brain": {"default": "ollama:x"}}
        def boom(req, timeout=2):
            raise ConnectionRefusedError("down")
        with mock.patch.object(brain.urllib.request, "urlopen", boom):
            with self.assertRaises(RuntimeError) as cm:
                brain.chat([{"role": "user", "content": "hi"}], cfg)
        self.assertIn("unreachable", str(cm.exception))
        self.assertIn("11434", str(cm.exception))

    def test_missing_base_url_error(self):
        cfg = {"brain": {"default": "openai_compat:m"}}
        with self.assertRaises(RuntimeError) as cm:
            brain.chat([{"role": "user", "content": "hi"}], cfg)
        self.assertIn("base_url", str(cm.exception))


class RuntimeProbeTest(unittest.TestCase):
    def test_missing_runtime_explicit_skip(self):
        cfg = {"brain": {"agent_runtime": "codex"}}
        with mock.patch("shutil.which", return_value=None):
            out = agents._runtime_cmd(cfg, "task", "")
        self.assertIsNone(out)  # spawn() turns this into SKIP(...)

    def test_opencode_template(self):
        cfg = {"brain": {"agent_runtime": "opencode"}}
        with mock.patch("shutil.which", return_value="/usr/bin/ori"):
            cmd = agents._runtime_cmd(cfg, "do thing", "m/x")
        self.assertEqual(cmd[:2], ["ori", "opencode"])
        self.assertIn("--model", cmd)
        self.assertIn("run", cmd)
        self.assertIn("do thing", cmd)

    def test_codex_template(self):
        cfg = {"brain": {"agent_runtime": "codex"}}
        with mock.patch("shutil.which", return_value="/usr/bin/codex"):
            cmd = agents._runtime_cmd(cfg, "do thing", "m/x")
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertIn("-m", cmd)

    def test_unknown_runtime_falls_back(self):
        cfg = {"brain": {"agent_runtime": "weird"}}
        with mock.patch("shutil.which", return_value="/x"):
            cmd = agents._runtime_cmd(cfg, "t", "")
        self.assertEqual(cmd[:2], ["ori", "opencode"])

    def test_config_set_nested_brain_section(self):
        import tempfile
        from wisp import config
        with tempfile.TemporaryDirectory() as td:
            f = pathlib.Path(td) / "config.toml"
            f.write_text("[brain]\ndefault = \"openrouter:x\"\n")
            old = config.CFG_FILE
            config.CFG_FILE = f
            try:
                config.set_config("brain.ollama", "base_url",
                                  "http://gpu:11434")
            finally:
                config.CFG_FILE = old
            text = f.read_text()
            assert "[brain.ollama]" in text
            assert 'base_url = "http://gpu:11434"' in text


class TestChatStream(unittest.TestCase):
    def _sse(self, chunks):
        lines = []
        for c in chunks:
            lines.append("data: " + json.dumps(
                {"choices": [{"delta": {"content": c}}]}))
        lines.append("data: [DONE]")
        body = ("\n".join(lines) + "\n").encode()

        class Resp:
            def __enter__(self): return iter(body.splitlines(keepends=True))
            def __exit__(self, *a): return False
        return Resp()

    def test_openai_compat_streams_deltas(self):
        from wisp import brain
        cfg = {"brain": {"default": "openai_compat:m"},
               "brain.openai_compat":
               {"base_url": "http://x.test/v1"}}
        got = []
        with mock.patch("urllib.request.urlopen",
                        return_value=self._sse(["Hel", "lo ", "world"])):
            out = brain.chat_stream([{"role": "user", "content": "hi"}],
                                    cfg, on_delta=got.append)
        self.assertEqual(out["content"], "Hello world")
        self.assertEqual(got, ["Hel", "Hello ", "Hello world"])

    def test_ollama_falls_back_single_delta(self):
        from wisp import brain
        cfg = {"brain": {"default": "ollama:m"}}
        got = []
        with mock.patch.object(brain, "_probe"), \
             mock.patch.object(brain, "chat",
                               return_value={"content": "one-shot",
                                             "raw": {}}) as ch:
            out = brain.chat_stream([{"role": "user", "content": "hi"}],
                                    cfg, on_delta=got.append)
        ch.assert_called_once()
        self.assertEqual(out["content"], "one-shot")
        self.assertEqual(got, ["one-shot"])


if __name__ == "__main__":
    unittest.main()


class LocalPresets(unittest.TestCase):
    def test_uitars_preset_shape(self):
        cfg = {"brain": {"default": "uitars:ui-tars-7b"},
               "brain.uitars": {"kind": "openai_compat",
                                "base_url": "http://127.0.0.1:8081/v1",
                                "vision": "true", "tools": "false",
                                "action_text": "true"}}
        p = brain.provider(cfg)
        self.assertEqual(p["name"], "uitars")
        self.assertFalse(brain.supports_tools(cfg))
        self.assertTrue(brain.action_text(cfg))
        self.assertTrue(brain.supports_vision(cfg))

    def test_llama_local_preset_shape(self):
        cfg = {"brain": {"default": "llama_local:ornith"},
               "brain.llama_local": {"kind": "openai_compat",
                                     "base_url":
                                     "http://127.0.0.1:8080/v1",
                                     "vision": "true", "tools": "true"}}
        p = brain.provider(cfg)
        self.assertEqual(p["name"], "llama_local")
        self.assertTrue(brain.supports_tools(cfg))
        self.assertFalse(brain.action_text(cfg))

    def test_default_config_mentions_presets(self):
        from wisp import config
        self.assertIn("brain.uitars", config.DEFAULT_CONFIG)
        self.assertIn("action_text", config.DEFAULT_CONFIG)
        self.assertIn("WISP_JEV_ENDPOINT", config.DEFAULT_CONFIG)
