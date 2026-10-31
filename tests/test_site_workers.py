"""Exercise the public Workers asset bundle, without deploying anything."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class WorkersBundle(unittest.TestCase):
    def test_primary_domain_footer_reflects_completed_worker_cutover(self):
        html = (ROOT / "site-3d/index.html").read_text()
        self.assertNotIn("deployment pending", html)
        self.assertIn("wisp.observer · Cloudflare Workers", html)

    def test_worker_configuration_serves_assets_without_spa_fallback(self):
        path = ROOT / "wrangler.json"
        self.assertTrue(path.is_file(), "missing Workers deployment configuration")
        config = json.loads(path.read_text())
        self.assertEqual("wisp-observer", config["name"])
        self.assertEqual("./build/published", config["assets"]["directory"])
        self.assertEqual("none", config["assets"]["not_found_handling"])
        self.assertNotIn("main", config)  # No request-processing backend needed.
        self.assertEqual(
            {"wisp.observer", "www.wisp.observer"},
            {route["pattern"] for route in config["routes"]
             if route.get("custom_domain") is True},
        )

    def test_bundle_carries_security_headers_and_noncacheable_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "published"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/site/build_workers.py"),
                 "--out", str(out)], check=True, capture_output=True,
            )
            self.assertTrue((out / "_headers").is_file(), "missing Workers headers")
            headers = (out / "_headers").read_text()
            self.assertIn("X-Content-Type-Options: nosniff", headers)
            self.assertIn("script-src 'self'", headers)
            self.assertIn("microphone=()", headers)
            self.assertIn("/install.py\n  Cache-Control: no-store", headers)

    def test_repository_sources_are_refused_before_any_build(self):
        spec = importlib.util.spec_from_file_location(
            "build_workers", ROOT / "scripts/site/build_workers.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Never allow a negative test to delete real repository sources.
        with mock.patch.object(module.subprocess, "run") as run:
            with mock.patch.object(module.shutil, "copyfile") as copy:
                for out in (ROOT, ROOT / "site", ROOT / "site-3d",
                            ROOT / "scripts/site", ROOT / "docs/generated"):
                    with self.subTest(out=out):
                        with self.assertRaisesRegex(ValueError, "output"):
                            module.build(out)
                run.assert_not_called()
                copy.assert_not_called()

    def test_build_contains_enhanced_plain_and_reviewed_bootstrap(self):
        script = ROOT / "scripts/site/build_workers.py"
        self.assertTrue(script.is_file(), "missing reproducible Workers asset builder")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "published"
            result = subprocess.run(
                [sys.executable, str(script), "--out", str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("scene.mjs", (out / "index.html").read_text()
                          + (out / "app.mjs").read_text())
            self.assertTrue((out / "vendor/three.module.js").is_file())
            plain = (out / "plain/index.html").read_text()
            self.assertNotIn("<script", plain)
            self.assertEqual(
                (ROOT / "scripts/bootstrap/install.py").read_bytes(),
                (out / "install.py").read_bytes(),
            )
            self.assertFalse((out / ".env").exists())
            self.assertFalse((out / "DESIGN.md").exists())
