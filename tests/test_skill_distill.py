"""spike/lfm-local: app-skill distiller mechanics (no network)."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import skill_distill  # noqa: E402
from wisp import brain  # noqa: E402


class CapturesTest(unittest.TestCase):
    def setUp(self):
        self.td = pathlib.Path(tempfile.mkdtemp())
        (self.td / "a.png").write_bytes(b"\x89PNG")
        (self.td / "a.txt").write_text("the settings page")
        (self.td / "b.png").write_bytes(b"\x89PNG")

    def test_crawl_dir_pairs_notes(self):
        caps = skill_distill.captures_from(self.td, None)
        self.assertEqual(len(caps), 2)
        self.assertEqual(caps[0]["note"], "the settings page")
        self.assertEqual(caps[1]["note"], "")

    def test_spec_manifest(self):
        spec = self.td / "m.jsonl"
        spec.write_text(
            json.dumps({"image": "b.png", "page": "inbox"}) + "\n")
        caps = skill_distill.captures_from(self.td, spec)
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["page"], "inbox")


class DistillTest(unittest.TestCase):
    def test_describe_and_merge_call_brain(self):
        td = pathlib.Path(tempfile.mkdtemp())
        (td / "a.png").write_bytes(b"\x89PNG")
        with mock.patch.object(brain, "chat",
                               return_value={"content": "- search box"}) as mc:
            d = skill_distill.describe(
                {"image": td / "a.png", "page": "home", "note": ""},
                "lfm:x", 5)
        self.assertIn("search box", d)
        self.assertEqual(mc.call_count, 1)
        body = skill_distill.merge(
            "TestApp", ["### home\n- search box"], "lfm:x", 5)
        self.assertTrue(body)

    def test_frontmatter_has_name_and_description(self):
        fm = skill_distill.frontmatter("perplexity-app", "Perplexity")
        self.assertIn("name: perplexity-app", fm)
        self.assertIn("description:", fm)


if __name__ == "__main__":
    unittest.main()
