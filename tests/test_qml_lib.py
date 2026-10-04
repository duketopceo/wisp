#!/usr/bin/env python3
"""Run the pure-JS QML lib tests (tests/qml/lib/tst_*.qml) headless under
qmltestrunner. Skipped when qmltestrunner is not installed. The libs have
no Quickshell imports, so no compositor is needed (offscreen platform)."""
import os
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNNER = shutil.which("qmltestrunner") or (
    "/usr/lib/qt6/bin/qmltestrunner"
    if os.path.exists("/usr/lib/qt6/bin/qmltestrunner") else None)


@unittest.skipUnless(RUNNER, "qmltestrunner not installed")
class TestQmlLibs(unittest.TestCase):
    def test_each_file(self):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                   QML_XHR_ALLOW_FILE_READ="1")
        files = sorted((ROOT / "tests" / "qml" / "lib").glob("tst_*.qml"))
        self.assertTrue(files)
        for f in files:
            p = subprocess.run([RUNNER, "-input", str(f)], env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 0, f"{f.name}\n{p.stdout}")


if __name__ == "__main__":
    unittest.main()
