"""macOS icon (U5): deterministic contract tests (no real icns output)."""
import pathlib
import stat
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "release" / "icon.sh").read_text(encoding="utf-8")
MASTER = ROOT / "assets" / "icons" / "hicolor" / "scalable" / "apps" / "wisp.svg"
SVG = MASTER.read_text(encoding="utf-8")


class MacosIconTest(unittest.TestCase):
    def test_executable(self):
        self.assertTrue((ROOT / "scripts" / "release" / "icon.sh").stat().st_mode
                        & stat.S_IXUSR)

    def test_master_source_exists(self):
        self.assertTrue(MASTER.is_file())

    def test_iconutil_contract(self):
        self.assertIn("iconutil", SCRIPT)
        self.assertIn("-c icns", SCRIPT)
        self.assertIn("--resampleWidth 1024", SCRIPT)

    def test_expected_icns_size(self):
        self.assertIn("--resampleWidth 1024", SCRIPT)
        self.assertIn("for size in 16 32 48 64 128 256 512; do", SCRIPT)

    def test_sips_used_for_slices(self):
        self.assertIn('icon_${size}x${size}.png', SCRIPT)
        self.assertIn('--resampleWidth "$size"', SCRIPT)


if __name__ == "__main__":
    unittest.main()
