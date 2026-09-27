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
        self.assertEqual(self.m["id"], "io.github.duketopceo.dim")

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


if __name__ == "__main__":
    unittest.main()
