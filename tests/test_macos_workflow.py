"""Deterministic checks for the mac-dmg job in .github/workflows/release.yml."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
YML = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


class MacosWorkflowTest(unittest.TestCase):
    def test_macos_job_present(self):
        self.assertIn("mac-dmg:", YML)
        self.assertIn("runs-on: macos-15", YML)

    def test_arm64_assertion_step(self):
        self.assertIn('[[ "$(uname -m)" == "arm64" ]]', YML)

    def test_dmg_pipeline_steps(self):
        self.assertIn("scripts/release/macos.py --build", YML)
        self.assertIn("scripts/release/dmg.sh build", YML)
        self.assertIn("scripts/release/dmg.sh verify", YML)
        self.assertIn("wisp-macos-arm64", YML)

    def test_needs_build(self):
        macos_block = YML.split("mac-dmg:")[1].split("plugin:")[0]
        self.assertIn("needs: build", macos_block)


if __name__ == "__main__":
    unittest.main()
