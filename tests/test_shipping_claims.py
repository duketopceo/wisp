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

    def test_enhanced_validation_does_not_deploy_to_github_pages(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn('"site-3d/**"', text)
        self.assertIn("scripts/site/build_3d.py", text)
        self.assertIn("scripts/site/build.py", text)
        self.assertNotIn("actions/deploy-pages", text)
        self.assertNotIn("actions/upload-pages-artifact", text)
        self.assertNotIn("PAGES_ENABLED", text)

    def test_light_gates_stay_in_the_browser_test_path(self):
        workflow = (ROOT / ".github/workflows/pages.yml").read_text()
        package = (ROOT / "tests/browser/package.json").read_text()
        self.assertIn("working-directory: tests/browser", workflow)
        self.assertIn("npm test", workflow)
        self.assertIn("node light.mjs", package)
        self.assertTrue((ROOT / "tests/browser/light-budget.json").is_file())

    def test_worker_artifact_waits_for_both_lanes(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("needs: [build, enhanced]", text)
        self.assertIn("scripts/site/build_workers.py", text)
        self.assertIn("path: build/published", text)
        self.assertIn("name: wisp-workers-assets", text)

    def test_published_installer_is_the_reviewed_self_contained_bootstrap(self):
        text = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn('"scripts/bootstrap/**"', text)
        self.assertIn("scripts/site/build_workers.py", text)
        # Real byte-for-byte bootstrap coverage is in test_site_workers.
