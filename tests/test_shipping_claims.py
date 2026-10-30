"""Public readiness claims must match the intentionally limited release scope."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlatformClaims(unittest.TestCase):
    def test_platform_docs_do_not_claim_an_unverified_full_port(self):
        for name in ("MACOS.md", "WINDOWS.md"):
            text = (ROOT / "docs" / name).read_text()
            with self.subTest(name=name):
                self.assertIn("experimental", text.lower())
                self.assertNotIn("supported second platform", text)
                self.assertNotIn("macos-latest", text)
                self.assertNotIn("dim/platform.py", text)
                self.assertNotIn("DimAgent", text)

    def test_roadmap_preserves_real_release_gates(self):
        text = (ROOT / "ROADMAP.md").read_text()
        self.assertIn("wisp.observer", text)
        self.assertIn("not yet shipped", text)
        self.assertIn("50", text)
        self.assertNotIn("wisp.casa", text)

    def test_enhanced_validation_does_not_replace_pages_publish_gates(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn('"site-3d/**"', text)
        self.assertIn("scripts/site/build_3d.py", text)
        self.assertIn("scripts/site/build.py", text)
        self.assertIn("vars.PAGES_ENABLED == 'true'", text)
        self.assertIn("github.ref == 'refs/heads/master'", text)

    def test_pages_publication_waits_for_both_lanes_and_retains_plain_site(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("needs: [build, enhanced]", text)
        self.assertIn("build_3d.py --out build/published", text)
        self.assertIn("build.py --out build/published/plain", text)
        self.assertIn("path: build/published", text)
        self.assertLess(text.index("build_3d.py --out build/published"),
                        text.index("build.py --out build/published/plain"))

    def test_published_installer_is_the_reviewed_self_contained_bootstrap(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn('"scripts/bootstrap/**"', text)
        self.assertIn("install -m 644 scripts/bootstrap/install.py "
                      "build/published/install.py", text)
