"""macOS packaging (U2): deterministic, no real Mach-O payloads."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
MACOS = ROOT / "scripts" / "release" / "macos.py"


def load():
    spec = importlib.util.spec_from_file_location("wisp_macos_packaging", MACOS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MacosPackagingTest(unittest.TestCase):
    def load(self):
        return load()

    def test_assert_arm64_accepts_lipo(self):
        macos = self.load()
        out = "Non-fat file: /tmp/wispd is architecture arm64"
        with mock.patch.object(macos.shutil, "which", return_value="/usr/bin/lipo"), \
                mock.patch.object(macos, "_run", return_value=out):
            self.assertEqual(macos.assert_arm64(pathlib.Path("/tmp/wispd")),
                             "arm64")

    def test_assert_arm64_rejects_x86_64(self):
        macos = self.load()
        with mock.patch.object(macos.shutil, "which",
                               return_value="/usr/bin/lipo"), \
                mock.patch.object(macos, "_run",
                                  return_value="x86_64 Mach-O executable"):
            with self.assertRaises(ValueError):
                macos.assert_arm64(pathlib.Path("/tmp/wispd"))

    def test_assert_arm64_falls_back_to_file(self):
        macos = self.load()
        with mock.patch.object(macos.shutil, "which", return_value=None), \
                mock.patch.object(macos, "_run",
                                  return_value="Mach-O 64-bit executable arm64"):
            self.assertEqual(macos.assert_arm64(pathlib.Path("/tmp/wispd")),
                             "arm64")

    def test_otool_check_runs_otool(self):
        macos = self.load()
        with mock.patch.object(macos, "_run") as run:
            macos.otool_check(pathlib.Path("/tmp/wispd"))
        run.assert_called_once_with(["otool", "-L", "/tmp/wispd"])

    def test_cli_check_missing_path_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, str(MACOS), "--check",
                 str(pathlib.Path(tmp) / "nope")],
                text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 1)
            self.assertIn("Error", result.stderr)


if __name__ == "__main__":
    unittest.main()
