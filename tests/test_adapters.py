#!/usr/bin/env python3
"""Adapter catalog tests — the app catalog must work off Linux too."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from wisp.tools import adapters  # noqa: E402


class MacCatalogTest(unittest.TestCase):
    """macOS has no .desktop entries — the catalog comes from .app bundles."""

    def _fake_dirs(self, tmp):
        apps = pathlib.Path(tmp) / "Applications"
        utils = pathlib.Path(tmp) / "Utilities"
        for d in (apps, utils):
            d.mkdir(parents=True)
        for name in ("Safari", "Google Chrome", "Cursor"):
            (apps / f"{name}.app").mkdir()
        # nested bundle: Terminal lives under Utilities on a real Mac
        (utils / "Terminal.app").mkdir()
        # dot-bundles are noise
        (apps / ".hidden.app").mkdir()
        return [apps, utils]

    def test_builds_open_a_launch_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._fake_dirs(tmp)
            with mock.patch.object(adapters, "_os", return_value="macos"), \
                 mock.patch.object(adapters, "MAC_APP_DIRS", dirs), \
                 mock.patch.object(adapters, "_MAC_EXTRA_APPS", {}):
                cat = adapters.generic_catalog()

        self.assertIn("Safari", cat)
        self.assertEqual(cat["Safari"]["launch"], "open -a 'Safari'")
        self.assertIn("cues", cat["Safari"])
        # multi-word bundle names survive intact
        self.assertEqual(cat["Google Chrome"]["launch"],
                         "open -a 'Google Chrome'")
        # nested Utilities dir is scanned
        self.assertIn("Terminal", cat)
        # dot-bundles skipped
        self.assertNotIn(".hidden", cat)

    def test_launch_token_is_which_able(self):
        """desktop.launch() guards on which(launch.split()[0]) — `open`
        must be the first token or every macOS launch skips."""
        with tempfile.TemporaryDirectory() as tmp:
            dirs = self._fake_dirs(tmp)
            with mock.patch.object(adapters, "_os", return_value="macos"), \
                 mock.patch.object(adapters, "MAC_APP_DIRS", dirs), \
                 mock.patch.object(adapters, "_MAC_EXTRA_APPS", {}):
                cat = adapters.generic_catalog()
        for entry in cat.values():
            self.assertEqual(entry["launch"].split()[0], "open")

    def test_linux_path_untouched(self):
        with mock.patch.object(adapters, "_os", return_value="linux"), \
             mock.patch.object(adapters, "_linux_catalog",
                               return_value={"code": {"launch": "code"}}):
            self.assertEqual(adapters.generic_catalog(),
                             {"code": {"launch": "code"}})

    def test_extra_apps_included_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = pathlib.Path(tmp) / "Finder.app"
            real.mkdir()
            with mock.patch.object(adapters, "_os", return_value="macos"), \
                 mock.patch.object(adapters, "MAC_APP_DIRS", []), \
                 mock.patch.object(adapters, "_MAC_EXTRA_APPS",
                                   {"Finder": real}):
                cat = adapters.generic_catalog()
        self.assertEqual(cat["Finder"]["launch"], "open -a 'Finder'")

    def test_extra_apps_skipped_when_absent(self):
        missing = pathlib.Path("/nope/NotThere.app")
        with mock.patch.object(adapters, "_os", return_value="macos"), \
             mock.patch.object(adapters, "MAC_APP_DIRS", []), \
             mock.patch.object(adapters, "_MAC_EXTRA_APPS",
                               {"NotThere": missing}):
            self.assertEqual(adapters.generic_catalog(), {})


if __name__ == "__main__":
    unittest.main()