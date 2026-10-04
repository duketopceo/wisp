#!/usr/bin/env python3
"""App icon sources, generated hicolor PNGs and desktop install (plan U9)."""
import importlib.machinery
import importlib.util
import pathlib
import re
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import config  # noqa: E402

APP = ROOT / "assets" / "icons" / "app"
HICOLOR = ROOT / "assets" / "icons" / "hicolor"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
HINT = (16, 24, 32, 48)


def load_wispd():
    loader = importlib.machinery.SourceFileLoader("wispd_mod", str(ROOT / "wispd"))
    spec = importlib.util.spec_from_loader("wispd_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def png_size(path):
    data = pathlib.Path(path).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", data[16:24])


class TestSources(unittest.TestCase):
    def test_sources_exist_and_parse(self):
        files = [APP / "wisp.svg", APP / "wisp-light.svg"]
        files += [APP / "hint" / f"{n}.svg" for n in HINT]
        for f in files:
            self.assertTrue(f.is_file(), f)
            ET.parse(f)

    def test_small_sizes_are_separate_drawings(self):
        base = (APP / "wisp.svg").read_text()
        bodies = {n: (APP / "hint" / f"{n}.svg").read_text() for n in HINT}
        for n, body in bodies.items():
            self.assertNotEqual(body, base)
            root = ET.fromstring(body)
            self.assertEqual(root.get("viewBox"), f"0 0 {n} {n}")
        self.assertEqual(len(set(bodies.values())), len(HINT))

    def test_dark_and_light_variants_differ(self):
        self.assertNotEqual((APP / "wisp.svg").read_text(),
                            (APP / "wisp-light.svg").read_text())

    def test_hand_authored_vector_only(self):
        for f in APP.rglob("*.svg"):
            text = f.read_text()
            self.assertNotIn("<image", text, f)
            self.assertNotIn("data:", text, f)
            self.assertIsNone(re.search(r"[^\x00-\x7f]", text), f)


class TestHicolor(unittest.TestCase):
    def test_every_size_has_exact_pixels(self):
        for n in SIZES:
            p = HICOLOR / f"{n}x{n}" / "apps" / "wisp.png"
            self.assertTrue(p.is_file(), p)
            self.assertEqual(png_size(p), (n, n), p)

    def test_scalable_svg_shipped(self):
        self.assertTrue((HICOLOR / "scalable" / "apps" / "wisp.svg").is_file())


class TestInstall(unittest.TestCase):
    def test_install_writes_icon_and_every_size(self):
        wispd = load_wispd()
        with tempfile.TemporaryDirectory() as td:
            home = pathlib.Path(td)
            with mock.patch.object(config, "HOME", home), \
                 mock.patch.object(wispd.subprocess, "run"), \
                 mock.patch("wisp.platform.current", return_value="linux"):
                wispd.install_files()
            desktop = (home / ".local/share/applications/wisp.desktop").read_text()
            self.assertIn("\nIcon=wisp\n", desktop)
            base = home / ".local/share/icons/hicolor"
            for n in SIZES:
                p = base / f"{n}x{n}" / "apps" / "wisp.png"
                self.assertTrue(p.is_file(), p)
                self.assertEqual(png_size(p), (n, n))
            self.assertTrue((base / "scalable/apps/wisp.svg").is_file())


if __name__ == "__main__":
    unittest.main()
