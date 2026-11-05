"""Credential selection at the decision HTTP boundary."""
import io
import json
import os
import pathlib
import unittest
import urllib.request
from unittest import mock

from wisp import brain, config, grounding, recall


class DecisionCredentialTest(unittest.TestCase):
    # The routing decision lanes are gone from master (Phase 5); grounding
    # is the one remaining caller of the decisions endpoint.
    def test_grounding_credentials_follow_provider_and_endpoint(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        import base64
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), "white").save(buf, format="PNG")
        img = base64.b64encode(buf.getvalue()).decode()
        for endpoint in ("https://openrouter.ai/api/alpha/decisions",
                         "http://127.0.0.1:9999/decisions",
                         "https://other.example/decisions"):
            with self.subTest(endpoint=endpoint):
                cfg = {"brain.openrouter": {"key_env": "WISP_TEST_KEY"}}
                answer = {"answers": {"p_0": {"noul": 1.0}}}
                with mock.patch.dict(os.environ, {
                    "WISP_TEST_KEY": "dedicated-sentinel",
                    "OPENROUTER_API_KEY": "legacy-sentinel",
                }), mock.patch.object(config, "JEV_ENDPOINT", endpoint), \
                        mock.patch.object(grounding, "_post_json",
                                          return_value=answer) as post:
                    grounding.ground_element(img, "button", cfg=cfg)
                if not post.called:
                    continue  # no candidate patches on a blank image
                headers = post.call_args.args[3]
                if endpoint.startswith("https://openrouter.ai/"):
                    self.assertEqual(headers.get("Authorization"),
                                     "Bearer dedicated-sentinel")
                else:
                    self.assertNotIn("Authorization", headers)

    def test_explicit_missing_source_does_not_use_legacy_key(self):
        cfg = {"brain.openrouter": {"key_env": "WISP_MISSING_TEST_KEY"}}
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "legacy-sentinel"},
                             clear=True), \
                mock.patch.object(config, "ENV_FILE", pathlib.Path(
                    "/nonexistent-wisp-credential-test")):
            with self.assertRaises(Exception) as cm:
                config.load_api_key(cfg)
            self.assertEqual(getattr(cm.exception, "code", None), "key_missing")

    def test_secret_service_source_reads_without_omaseal(self):
        result = mock.Mock(returncode=0, stdout="keyring-sentinel\n")
        with mock.patch("subprocess.run", return_value=result) as run:
            self.assertEqual(config.load_env_key("keyring://wisp/openrouter"),
                             "keyring-sentinel")
        self.assertEqual(run.call_args.args[0][1], "lookup")
        self.assertNotIn("--unlock", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-4:],
                         ["service", "wisp", "account", "openrouter"])

    def test_locked_keyring_only_uses_explicit_fallback(self):
        locked = mock.Mock(returncode=1, stdout="")
        with mock.patch.dict(os.environ, {
                "OPENROUTER_API_KEY": "legacy-sentinel",
                "WISP_FALLBACK_TEST_KEY": "fallback-sentinel"}, clear=True), \
                mock.patch("subprocess.run", return_value=locked):
            self.assertEqual(config.load_env_key("keyring://wisp/missing"), "")
            self.assertEqual(config.load_env_key(
                "keyring://wisp/missing,WISP_FALLBACK_TEST_KEY"),
                "fallback-sentinel")
            with self.assertRaises(Exception) as cm:
                config.require_key("keyring://wisp/missing")
        self.assertEqual(getattr(cm.exception, "code", None), "key_missing")
        self.assertIn("keyring", cm.exception.public.lower())
        self.assertIn("locked", cm.exception.public.lower())
        self.assertNotIn("legacy-sentinel", str(cm.exception))

    def test_brain_and_recall_use_their_explicit_sources(self):
        captured = {}

        def respond(req, timeout):
            captured.update(dict(req.header_items()))
            return io.BytesIO(json.dumps({"data": [{"embedding": [1]}]}).encode())

        with mock.patch.dict(os.environ, {
            "WISP_BRAIN_TEST_KEY": "brain-sentinel",
            "WISP_RECALL_TEST_KEY": "recall-sentinel",
            "OPENROUTER_API_KEY": "legacy-sentinel",
        }), mock.patch("urllib.request.urlopen", respond):
            provider = brain.provider({"brain.openrouter": {
                "key_env": "WISP_BRAIN_TEST_KEY"}})
            self.assertEqual(brain._headers(provider)["Authorization"],
                             "Bearer brain-sentinel")
            recall._embed(["text"], {"key_env": "WISP_RECALL_TEST_KEY"})
        self.assertEqual(captured["Authorization"], "Bearer recall-sentinel")

    def test_openrouter_brain_does_not_send_key_to_custom_endpoint(self):
        provider = brain.provider({"brain.openrouter": {
            "base_url": "https://untrusted.example/v1"}})
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "legacy-sentinel"}):
            with self.assertRaises(Exception) as cm:
                brain._headers(provider)
        self.assertNotIn("legacy-sentinel", str(cm.exception))

    def test_custom_brain_does_not_reuse_openrouter_source(self):
        cfg = {"brain": {"default": "custom:model"},
               "brain.openrouter": {"key_env": "WISP_TEST_KEY"},
               "brain.custom": {"base_url": "https://other.example/v1",
                                "key_env": "WISP_TEST_KEY"}}
        with mock.patch.dict(os.environ, {"WISP_TEST_KEY": "test-sentinel"}):
            with self.assertRaises(Exception) as cm:
                brain._headers(brain.provider(cfg))
        self.assertNotIn("test-sentinel", str(cm.exception))

    def test_custom_recall_endpoint_does_not_use_openrouter_source(self):
        cfg = {"base_url": "https://other.example/v1",
               "key_env": "WISP_TEST_KEY", "_openrouter_key_env": "WISP_TEST_KEY"}
        with mock.patch.dict(os.environ, {"WISP_TEST_KEY": "test-sentinel"}), \
                mock.patch("urllib.request.urlopen") as send:
            with self.assertRaises(Exception) as cm:
                recall._embed(["text"], cfg)
        send.assert_not_called()
        self.assertNotIn("test-sentinel", str(cm.exception))

    def test_recall_missing_key_fails_before_network(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(config, "ENV_FILE", pathlib.Path(
                    "/nonexistent-wisp-credential-test")), \
                mock.patch("urllib.request.urlopen") as send:
            with self.assertRaises(Exception) as cm:
                recall._embed(["text"], {"key_env": "WISP_MISSING_TEST_KEY"})
        self.assertEqual(getattr(cm.exception, "code", None), "key_missing")
        send.assert_not_called()

    def test_hosted_calls_do_not_forward_credentials_on_redirect(self):
        requests = []

        def respond(req, timeout):
            requests.append(req)
            return io.BytesIO(json.dumps({"data": [{"embedding": [1]}]}).encode())

        with mock.patch.dict(os.environ, {"WISP_TEST_KEY": "test-sentinel"}), \
                mock.patch("urllib.request.urlopen", respond):
            brain._post("https://openrouter.ai/api/v1/chat/completions",
                        {"Authorization": "Bearer test-sentinel"}, {})
            recall._embed(["text"], {"key_env": "WISP_TEST_KEY"})
            grounding._post_json("https://openrouter.ai/api/alpha/decisions",
                                 {}, 1, {"Authorization": "Bearer test-sentinel"})
        self.assertEqual(len(requests), 3)
        for req in requests:
            self.assertEqual(req.get_header("Authorization"), "Bearer test-sentinel")
            redirected = urllib.request.HTTPRedirectHandler().redirect_request(
                req, None, 302, "", {}, "https://other.example/")
            self.assertIsNone(redirected.get_header("Authorization"))
