import unittest

from wisp import model_catalog as MC

ALL_TAGS = {"hf.co/LiquidAI/LFM2.5-VL-1.6B-GGUF:Q8_0",
            "hf.co/ggml-org/SmolVLM2-2.2B-Instruct-GGUF:Q8_0",
            "hf.co/ggml-org/SmolLM3-3B-GGUF:Q8_0",
            "qwen3:1.7b-q8_0", "nomic-embed-text:latest"}


class CatalogShapeTests(unittest.TestCase):
    def test_every_lane_has_openrouter(self):
        for lane, opts in MC.CATALOG.items():
            self.assertTrue(any(o["provider"] == "openrouter" for o in opts), lane)

    def test_catalog_never_exceeds_three(self):
        for lane, opts in MC.CATALOG.items():
            self.assertLessEqual(len(opts), 3, lane)


class DetectedTests(unittest.TestCase):
    def test_cap_and_openrouter_guarantee(self):
        for lane in MC.CATALOG:
            got = MC.detected(lane, tags=ALL_TAGS)
            self.assertLessEqual(len(got), MC.MAX_OPTIONS, lane)
            self.assertTrue(any(o["provider"] == "openrouter" for o in got), lane)

    def test_ollama_entries_filtered_by_pulled_weights(self):
        got = MC.detected("eyes", tags=set())  # nothing pulled
        self.assertEqual([o["id"] for o in got], ["google/gemini-2.5-flash"])

    def test_local_off_hides_local_entries(self):
        got = MC.detected("speech", local=False, tags=ALL_TAGS)
        self.assertFalse(any(o["provider"] in ("local", "ollama") for o in got))
        self.assertTrue(any(o["provider"] == "openrouter" or o["provider"] == "groq" for o in got))

    def test_unknown_lane_empty(self):
        self.assertEqual(MC.detected("nope", tags=ALL_TAGS), [])

    def test_all_local_lane_still_shows_openrouter(self):
        # embeddings has two hosted + one local; eyes has two local + one hosted
        got = MC.detected("eyes", tags=ALL_TAGS)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[-1]["provider"], "openrouter")


if __name__ == "__main__":
    unittest.main()
