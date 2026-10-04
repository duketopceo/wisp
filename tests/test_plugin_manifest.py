#!/usr/bin/env python3
"""Shell-plugin manifest + packaging sanity checks."""
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "shell-plugin"


class TestManifest(unittest.TestCase):
    def setUp(self):
        self.m = json.loads((PLUGIN / "manifest.json").read_text())

    def test_required_fields(self):
        for k in ("schemaVersion", "id", "name", "version", "author",
                  "license", "kinds", "entryPoints"):
            self.assertIn(k, self.m)

    def test_id_namespaced(self):
        self.assertEqual(self.m["id"], "io.github.duketopceo.wisp")

    def test_kinds_have_entry_points(self):
        ep = self.m["entryPoints"]
        kind_to_key = {"service": "service", "bar-widget": "barWidget",
                       "overlay": "overlay", "panel": "panel"}
        for kind in self.m["kinds"]:
            key = kind_to_key[kind]
            self.assertIn(key, ep, f"kind {kind} missing entry point")
            self.assertTrue((PLUGIN / ep[key]).exists(),
                            f"entry point {ep[key]} missing")

    def test_bar_widget_section(self):
        self.assertIn(self.m["barWidget"]["defaultSection"],
                      ("left", "center", "right"))


def _code(path):
    import re
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)(^|[^:\"'\\])//.*$", lambda m: m.group(1), src)


class TestBarWidget(unittest.TestCase):
    """W23: the bar mark reads only WispService and polls nothing."""

    def setUp(self):
        self.m = json.loads((PLUGIN / "manifest.json").read_text())
        self.src = _code(PLUGIN / "BarWidget.qml")

    def test_version_is_semver_and_bumped_past_the_old_bar(self):
        parts = self.m["version"].split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))
        self.assertGreaterEqual(tuple(map(int, parts)), (0, 4, 0))

    def test_bar_widget_manifest_block(self):
        bw = self.m["barWidget"]
        for k in ("displayName", "description", "category",
                  "allowMultiple", "defaultSection"):
            self.assertIn(k, bw)
        self.assertFalse(bw["allowMultiple"])
        self.assertNotIn("\u2014", bw["description"])

    def test_declares_service_kind_the_bar_reads(self):
        self.assertIn("service", self.m["kinds"])
        self.assertIn("bar-widget", self.m["kinds"])

    def test_no_polling_and_no_own_io(self):
        import re
        for rx in (r"\bTimer\s*\{", r"\bFileView\s*\{", r"\bProcess\s*\{",
                   r"\bSocket\s*\{", r"state\.json", r"wispd\.sock",
                   r"setInterval", r"hyprctl"):
            self.assertIsNone(re.search(rx, self.src), rx)

    def test_reads_the_plugin_service_and_uses_the_bar_components(self):
        self.assertIn("serviceFor(moduleName)", self.src)
        self.assertIn("BarMark", self.src)
        self.assertIn("BarActions", self.src)
        self.assertIn("tooltipLines", self.src)

    def test_no_literal_colors_or_copy_in_bar_files(self):
        import re
        for p in (PLUGIN / "BarWidget.qml", PLUGIN / "components" / "BarMark.qml",
                  PLUGIN / "components" / "BarActions.qml",
                  PLUGIN / "lib" / "bar.js"):
            src = _code(p)
            self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", src), p.name)

    def test_bar_copy_lives_in_the_copy_table(self):
        import sys
        sys.path.insert(0, str(ROOT))
        from wisp import copy as wcopy
        for k in ("ui.bar.ok", "ui.bar.down", "ui.bar.spend", "ui.bar.hint"):
            self.assertIn(k, wcopy.STRINGS)


if __name__ == "__main__":
    unittest.main()
