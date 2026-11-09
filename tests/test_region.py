import http.client
import io
import json
import unittest
import unittest.mock as mock
import urllib.error

from wisp import brain, copy, errors_codes, region
from wisp.cli import diagnose

US = {"brain.openrouter": {"region": "us"}}
FIXTURE = {"data": [{"id": "qwen/qwen3-vl-235b-a22b-instruct"},
                    {"id": "google/gemma-4-31b-it"},
                    {"id": "particle-ai/particle-1"}]}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class RegionUrl(unittest.TestCase):
    def test_default_is_global(self):
        self.assertEqual(region.region({}), "global")
        self.assertEqual(region.region({"brain.openrouter": {"region": "mars"}}),
                         "global")
        self.assertEqual(brain.provider({})["base_url"],
                         "https://openrouter.ai/api/v1")

    def test_us_moves_every_openrouter_provider(self):
        cfg = {**US, "brain": {"default": "openrouter:google/gemma-4-31b-it"}}
        self.assertEqual(brain.provider(cfg)["base_url"],
                         "https://us.openrouter.ai/api/v1")
        # explicit global base_url in the config table is still moved
        cfg["brain.openrouter"]["base_url"] = "https://openrouter.ai/api/v1"
        self.assertEqual(brain.provider(cfg)["base_url"],
                         "https://us.openrouter.ai/api/v1")

    def test_other_hosts_untouched(self):
        self.assertEqual(region.apply(US, "http://localhost:11434"),
                         "http://localhost:11434")
        self.assertEqual(region.apply(US, "https://us.openrouter.ai/api/v1"),
                         "https://us.openrouter.ai/api/v1")
        self.assertEqual(region.apply(US, "https://evil.openrouter.ai.x/api"),
                         "https://evil.openrouter.ai.x/api")

    def test_ollama_provider_not_rewritten(self):
        cfg = {**US, "brain": {"default": "ollama:x"}}
        self.assertEqual(brain.provider(cfg)["base_url"],
                         "http://localhost:11434")

    def test_grounding_and_sense_brains_follow(self):
        cfg = {**US, "ground": {"vlm_brain": "openrouter:qwen/qwen3-vl-235b-a22b-instruct"}}
        from wisp import suggest
        self.assertEqual(
            brain.provider(suggest._sense_cfg(cfg))["base_url"],
            "https://us.openrouter.ai/api/v1")


class Models(unittest.TestCase):
    CFG = {**US,
           "brain": {"default": "openrouter:qwen/qwen3-vl-235b-a22b-instruct",
                     "fallback": "openrouter:google/gemini-2.5-flash, ollama:x",
                     "fast_model": "openai/gpt-4.1-mini"},
           "ground": {"vlm_brain": "openrouter:qwen/qwen3-vl-235b-a22b-instruct"},
           "sense": {"model": "openrouter:google/gemma-4-31b-it"},
           "agent": {"model": "typesafe/jev-1.13"}}

    def test_configured_models_skip_other_providers(self):
        got = {m for _s, m in region.configured_models(self.CFG)}
        self.assertEqual(got, {"qwen/qwen3-vl-235b-a22b-instruct",
                               "google/gemini-2.5-flash",
                               "openai/gpt-4.1-mini", "google/gemma-4-31b-it",
                               "typesafe/jev-1.13"})

    def test_fetch_parses_fixture_and_missing(self):
        seen = {}

        def opener(req, timeout):
            seen["url"] = req.full_url
            seen["ua"] = req.get_header("User-agent")
            return Resp(json.dumps(FIXTURE).encode())
        have = region.fetch_models(self.CFG, "k", opener=opener)
        self.assertEqual(seen["url"], "https://us.openrouter.ai/api/v1/models")
        self.assertEqual(seen["ua"], "wisp/1.0")
        missing = {m for _s, m in region.models_missing(self.CFG, have)}
        self.assertEqual(missing, {"google/gemini-2.5-flash",
                                   "openai/gpt-4.1-mini",
                                   "typesafe/jev-1.13"})


class DoctorRows(unittest.TestCase):
    def rows(self, cfg, fetch=None):
        out = []

        def row(label, value, ok=True, level=None, detail=None, fix=""):
            out.append((label, value, ok, level, fix))
        diagnose._region_rows(row, cfg, fetch)
        return out

    def test_global_makes_no_fetch(self):
        def boom(*a):
            raise AssertionError("network")
        r = self.rows({}, boom)
        self.assertEqual(len(r), 1)
        self.assertIn("global", r[0][1])

    def test_us_lists_missing(self):
        r = self.rows(Models.CFG, lambda cfg, key: {"google/gemma-4-31b-it"})
        names = [x[0] for x in r]
        self.assertIn("not in us: brain.fallback", names)
        self.assertTrue(all(not x[2] for x in r if x[0].startswith("not in")))

    def test_us_all_served(self):
        cfg = {**US, "brain": {"default": "openrouter:google/gemma-4-31b-it"}}
        r = self.rows(cfg, lambda c, k: {"google/gemma-4-31b-it"})
        self.assertEqual(r[-1][0], "models in region")

    def test_fetch_failure_is_a_warning(self):
        def bad(c, k):
            raise OSError("down")
        r = self.rows(Models.CFG, bad)
        self.assertEqual(r[-1][3], "warn")


def _http_error(url, code, body):
    return urllib.error.HTTPError(url, code, "Forbidden", {},
                                  io.BytesIO(body) if body is not None
                                  else None)


US_URL = "https://us.openrouter.ai/api/v1/chat/completions"
GL_URL = "https://openrouter.ai/api/v1/chat/completions"
KEY = "sk-or-v1-" + "a1b2c3d4" * 6


class Denied(unittest.TestCase):
    MSGS = [{"role": "user", "content": "hi"}]

    def chat(self, cfg, errs):
        """Run brain.chat with every urlopen raising the next of errs."""
        it = iter(errs)

        def fake(req, timeout=60):
            raise next(it)
        with mock.patch.object(brain.cancel, "urlopen", fake), \
                mock.patch.object(brain.config, "require_key",
                                  lambda n: "k"):
            return brain.chat(self.MSGS, cfg)

    def cfg(self, extra=None):
        return {**US, "brain": {"default": "openrouter:a/b", **(extra or {})}}

    def test_regional_403_raises_region_denied(self):
        e = _http_error(US_URL, 403, json.dumps(
            {"error": {"message": "Business plan required"}}).encode())
        with self.assertRaises(errors_codes.WispError) as cm:
            self.chat(self.cfg(), [e])
        self.assertEqual(cm.exception.code, "region_denied")
        msg, hint = copy.ERRORS["region_denied"]
        self.assertIn("us", msg)
        self.assertIn('region = "global"', hint)
        # the provider body may echo what the user said, so it stays out of
        # the logged detail; the detail names the region and points at the
        # `doctor --live` probe, whose fixed prompt makes the body safe
        self.assertNotIn("Business plan required", cm.exception.detail)
        self.assertIn("us.openrouter.ai", cm.exception.detail)
        self.assertIn("doctor --live", cm.exception.detail)

    def test_empty_and_non_json_body_stay_clean(self):
        for body in (None, b"", b"<html>nope</html>"):
            with self.assertRaises(errors_codes.WispError) as cm:
                self.chat(self.cfg(), [_http_error(US_URL, 403, body)])
            self.assertEqual(cm.exception.code, "region_denied")
            self.assertIn("403", cm.exception.detail)

    def test_secret_in_body_is_redacted(self):
        e = _http_error(US_URL, 401, json.dumps({"error": {
            "message": f"bad key {KEY} sent as Bearer {KEY}"}}).encode())
        with self.assertRaises(errors_codes.WispError) as cm:
            self.chat(self.cfg(), [e])
        self.assertNotIn(KEY, cm.exception.detail)
        self.assertNotIn("a1b2c3d4", cm.exception.detail)

    def test_global_403_stays_brain_down_without_hint(self):
        e = _http_error(GL_URL, 403, b'{"error":{"message":"nope"}}')
        cfg = {"brain": {"default": "openrouter:a/b"}}
        with self.assertRaises(errors_codes.WispError) as cm:
            self.chat(cfg, [e])
        self.assertEqual(cm.exception.code, "brain_down")
        self.assertNotIn("region", cm.exception.detail.lower())

    def test_skipped_fallback_does_not_hide_region_denied(self):
        # default allow_paid = "false": the openrouter fallback is skipped
        # without a request, so the only refusal came from the US region
        cfg = self.cfg({"fallback": "openrouter:c/d", "allow_paid": "false"})
        errs = [_http_error(US_URL, 403, b"{}")]
        with self.assertRaises(errors_codes.WispError) as cm:
            self.chat(cfg, errs)
        self.assertEqual(cm.exception.code, "region_denied")

    def test_fallback_without_key_does_not_hide_region_denied(self):
        # the fallback's key is missing, so it fails before any request
        # goes out: only the US refusal counts, and it names the fix
        cfg = self.cfg({"fallback": "openrouter:c/d", "allow_paid": "true"})
        keys = iter(["k"])

        def require_key(name):
            k = next(keys, None)
            if k is None:
                raise errors_codes.WispError("key_missing", "no key")
            return k
        sent = []

        def fake(req, timeout=60):
            sent.append(req.full_url)
            raise _http_error(US_URL, 403, b"{}")
        with mock.patch.object(brain.cancel, "urlopen", fake), \
                mock.patch.object(brain.config, "require_key", require_key):
            with self.assertRaises(errors_codes.WispError) as cm:
                brain.chat(self.MSGS, cfg)
        self.assertEqual(len(sent), 1)
        self.assertEqual(cm.exception.code, "region_denied")

    def test_mixed_chain_stays_brain_down(self):
        cfg = self.cfg({"fallback": "openrouter:c/d", "allow_paid": "true"})
        errs = [_http_error(US_URL, 403, b"{}"), TimeoutError("slow")]
        with self.assertRaises(errors_codes.WispError) as cm:
            self.chat(cfg, errs)
        self.assertEqual(cm.exception.code, "brain_down")

    def test_streaming_403_names_region_too(self):
        def fake(req, timeout=60):
            raise _http_error(US_URL, 403,
                              b'{"error":{"message":"streamed no"}}')
        with mock.patch.object(brain.cancel, "urlopen", fake), \
                mock.patch.object(brain.config, "require_key",
                                  lambda n: "k"):
            with self.assertRaises(errors_codes.WispError) as cm:
                brain.chat_stream(self.MSGS, self.cfg(), lambda t: None)
        self.assertEqual(cm.exception.code, "region_denied")
        self.assertNotIn("streamed no", cm.exception.detail)
        self.assertIn("us.openrouter.ai", cm.exception.detail)


class LiveRow(unittest.TestCase):
    CFG = {**US, "brain": {"default": "openrouter:a/b",
                           "fallback": "openrouter:c/d, ollama:x"}}

    def rows(self, cfg, live, opener=None):
        out = []

        def row(label, value, ok=True, level=None, detail=None, fix=""):
            out.append((label, value, ok, level, fix))
        diagnose._region_rows(row, cfg, lambda c, k: set(), live=live,
                              opener=opener)
        return [r for r in out if r[0].startswith("us chat")]

    def test_pass(self):
        seen = []

        def opener(req, timeout):
            seen.append((req.full_url, json.loads(req.data)))
            return Resp(b'{"choices":[]}')
        r = self.rows(self.CFG, True, opener)
        self.assertEqual([x[2] for x in r], [True, True])
        self.assertEqual({u for u, _ in seen}, {US_URL})
        self.assertEqual({b["model"] for _, b in seen}, {"a/b", "c/d"})
        self.assertTrue(all(b["max_tokens"] == 1 for _, b in seen))

    def test_fail_shows_body_text(self):
        def opener(req, timeout):
            raise _http_error(US_URL, 403,
                              b'{"error":{"message":"zone blocked"}}')
        r = self.rows(self.CFG, True, opener)
        self.assertTrue(all(not x[2] for x in r))
        self.assertIn("zone blocked", r[0][1])
        self.assertIn("Business", r[0][1])
        self.assertIn('region = "global"', r[0][4])

    def test_truncated_body_is_a_row_and_the_rest_continue(self):
        calls = []

        class Short(Resp):
            def read(self, *a):
                raise http.client.IncompleteRead(b"par", 100)

        def opener(req, timeout):
            calls.append(json.loads(req.data)["model"])
            return Short(b"") if len(calls) == 1 else Resp(b"{}")
        r = self.rows(self.CFG, True, opener)
        self.assertEqual(calls, ["a/b", "c/d"])
        self.assertEqual([x[2] for x in r], [False, True])
        self.assertIn("IncompleteRead", r[0][1])

    def test_skips_in_global_mode(self):
        def boom(*a, **k):
            raise AssertionError("network")
        self.assertEqual(self.rows({"brain": {"default": "openrouter:a/b"}},
                                   True, boom), [])

    def test_not_run_without_live(self):
        def boom(*a, **k):
            raise AssertionError("network")
        r = self.rows(self.CFG, False, boom)
        self.assertEqual(len(r), 1)
        self.assertIn("live check not run", r[0][1])


if __name__ == "__main__":
    unittest.main()
