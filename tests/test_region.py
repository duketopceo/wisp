import io
import json
import unittest

from wisp import brain, region
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


if __name__ == "__main__":
    unittest.main()
