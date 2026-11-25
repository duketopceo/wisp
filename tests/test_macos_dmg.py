"""macOS DMG release tooling (U3): deterministic script-contract tests."""
import pathlib
import stat
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "release" / "dmg.sh").read_text(encoding="utf-8")


class MacosDmgTest(unittest.TestCase):
    def test_executable(self):
        self.assertTrue(pathlib.Path(ROOT / "scripts" / "release" /
                                     "dmg.sh").stat().st_mode
                        & stat.S_IXUSR)

    def test_sign_contract(self):
        self.assertIn("codesign -s", SCRIPT)
        self.assertIn("--options runtime", SCRIPT)
        self.assertIn("--timestamp", SCRIPT)
        self.assertIn("--force", SCRIPT)

    def test_notarization_contract(self):
        self.assertIn("notarytool submit", SCRIPT)
        self.assertIn("--wait", SCRIPT)
        self.assertIn("stapler staple", SCRIPT)

    def test_verify_contract(self):
        self.assertIn("codesign --verify --deep --strict", SCRIPT)
        self.assertIn("stapler validate", SCRIPT)

    def test_no_deep_sign_on_sign_path(self):
        for line in SCRIPT.splitlines():
            if line.lstrip().startswith("#") or "--deep" not in line:
                continue
            self.assertIn("verify", line,
                          f"--deep used on a signing line: {line}")


if __name__ == "__main__":
    unittest.main()
