#!/usr/bin/env python3
"""Owned icon, bar-glyph and mark set (DESIGN-v2 3.2 A2-A6, 5.6; plan U6).

Sources: assets/icons/src/*.svg and assets/brand/mark.svg, compiled by
scripts/assets/build_icons.py into shell-plugin/lib/icons.js.
"""
import json
import pathlib
import re
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "assets"))

import build_icons  # noqa: E402

ICONS_JS = ROOT / "shell-plugin" / "lib" / "icons.js"
A3 = ["bar-idle", "bar-listening", "bar-thinking", "bar-acting",
      "bar-needs-you", "bar-error", "bar-offline"]
A4 = ["mic", "mic-off", "stop", "check", "cross", "undo", "pin", "unpin",
      "collapse", "expand", "talk", "act", "agent", "point", "guide",
      "connect", "link-broken", "eye", "skill", "history", "gauge",
      "settings", "warning", "external"]
OTHER = ["mark", "ghost-cursor", "beacon"]

STROKE_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}">{body}'
              '</svg>')
PATH = ('<path fill="none" stroke="currentColor" stroke-width="1.5" '
        'stroke-linecap="square" stroke-linejoin="miter" d="M1 1 L2 2"/>')


def shipped():
    text = ICONS_JS.read_text()
    m = re.search(r"^var ICONS = (\{.*\})$", text, re.M)
    return json.loads(m.group(1))


class TestShippedSet(unittest.TestCase):
    def test_every_named_icon_exists(self):
        icons = shipped()
        for name in A3 + A4 + OTHER:
            self.assertIn(name, icons)
        self.assertEqual(len(A4), 24)

    def test_every_source_validates(self):
        for path in build_icons.sources():
            build_icons.validate(path)

    def test_only_marks_are_filled_and_round(self):
        for name, ic in shipped().items():
            mark_family = name == "mark" or name.startswith("bar-")
            if ic["fill"]:
                self.assertIn(name, build_icons.FILLED, name)
            if ic["stroke"]:
                self.assertEqual(ic["width"], 1.5, name)
                if not mark_family:
                    self.assertEqual((ic["cap"], ic["join"]),
                                     ("square", "miter"), name)

    def test_qml_icon_names_resolve(self):
        icons = shipped()
        used = set()
        for qml in (ROOT / "shell-plugin").rglob("*.qml"):
            for m in re.finditer(r'\bIcon\s*\{[^}]*?\bname:\s*"([^"]+)"',
                                 qml.read_text(), re.S):
                used.add((qml.name, m.group(1)))
        missing = [u for u in used if u[1] not in icons]
        self.assertEqual(missing, [])

    def test_wordmark_is_single_current_color_path(self):
        text = (ROOT / "assets" / "brand" / "wordmark.svg").read_text()
        self.assertEqual(text.count("<path"), 1)
        self.assertIn('stroke="currentColor"', text)
        self.assertNotRegex(text, r"#[0-9a-fA-F]{3,6}\b")


class TestValidation(unittest.TestCase):
    def _bad(self, name, body, vb="0 0 16 16"):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / f"{name}.svg"
            p.write_text(STROKE_SVG.format(vb=vb, body=body))
            with self.assertRaises(build_icons.IconError) as cm:
                build_icons.validate(p)
        self.assertIn(f"{name}.svg", str(cm.exception))

    def test_two_paths_fail(self):
        self._bad("twopaths", PATH + PATH)

    def test_wrong_viewbox_fails(self):
        self._bad("bigbox", PATH, vb="0 0 24 24")

    def test_other_shapes_fail(self):
        self._bad("circle", PATH + '<circle cx="8" cy="8" r="2"/>')

    def test_fill_on_ui_icon_fails(self):
        self._bad("filled", PATH.replace('fill="none"', 'fill="currentColor"'))

    def test_round_caps_on_ui_icon_fail(self):
        self._bad("roundcap", PATH.replace("square", "round"))

    def test_hex_color_fails(self):
        self._bad("hexcolor", PATH.replace('stroke="currentColor"',
                                           'stroke="#ffffff"'))


@unittest.skipUnless(shutil.which("svgo"), "svgo not on PATH")
class TestBuild(unittest.TestCase):
    def test_build_is_deterministic_and_committed_file_is_fresh(self):
        a = build_icons.render()
        b = build_icons.render()
        self.assertEqual(a, b)
        self.assertEqual(ICONS_JS.read_text(), a,
                         "icons.js is stale: run "
                         "python scripts/assets/build_icons.py")


if __name__ == "__main__":
    unittest.main()
