"""B15: the Omarchy marketplace mirror, and `wispd install --from-plugin`
(nothing is edited until the user says yes)."""
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import cli_env  # noqa: E402
import plugin_mirror as pm  # noqa: E402

ROOT = HERE.parent
PLUGIN_ID = "io.github.duketopceo.wisp"


class Mirror(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.out = self.tmp / "mirror"
        self.res = pm.build(self.out, "v1.2.3")

    def test_the_source_plugin_is_valid(self):
        self.assertEqual(pm.validate(ROOT / "shell-plugin"), [])

    def test_the_mirror_is_valid_and_has_the_files_a_listing_needs(self):
        self.assertEqual(pm.validate(self.out), [])
        for f in ("manifest.json", "README.md", "LICENSE", "preview.png",
                  "WispService.qml", "BarWidget.qml", "Companion.qml"):
            self.assertTrue((self.out / f).is_file(), f)

    def test_version_follows_the_tag_and_id_is_unchanged(self):
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["version"], "1.2.3")
        self.assertEqual(m["id"], PLUGIN_ID)
        self.assertFalse(m["id"].startswith("omarchy."))
        src = json.loads((ROOT / "shell-plugin" / "manifest.json").read_text())
        m["version"] = src["version"]
        self.assertEqual(m, src)              # nothing else differs

    def test_manifest_matches_the_files(self):
        m = json.loads((self.out / "manifest.json").read_text())
        for name, ep in m["entryPoints"].items():
            p = (self.out / ep).resolve()
            self.assertTrue(p.is_file(), name)
            self.assertTrue(str(p).startswith(str(self.out.resolve())))
            self.assertNotIn("..", ep)
        want = {"service": "service", "bar-widget": "barWidget",
                "overlay": "overlay"}
        self.assertEqual(sorted(m["kinds"]), sorted(want))
        for kind in m["kinds"]:
            self.assertIn(want[kind], m["entryPoints"])

    def test_the_readme_has_install_and_removal(self):
        text = (self.out / "README.md").read_text()
        self.assertIn("omarchy plugin add", text)
        self.assertIn("--enable", text)
        self.assertIn(f"omarchy plugin remove {PLUGIN_ID}", text)
        self.assertIn("systemctl --user disable --now wispd.service", text)
        self.assertIn("--from-plugin", text)
        self.assertIn("MIT", text)

    def test_no_python_or_tests_or_symlinks_ride_along(self):
        names = [f for f in self.res["files"]]
        self.assertFalse([n for n in names if n.endswith((".py", ".pyc"))])
        self.assertFalse([p for p in self.out.rglob("*") if p.is_symlink()])
        self.assertLess(self.res["bytes"], 2 * 1024 * 1024)

    def test_building_again_replaces_the_tree(self):
        (self.out / "stale.txt").write_text("x")
        pm.build(self.out, "v1.2.4")
        self.assertFalse((self.out / "stale.txt").exists())
        self.assertEqual(json.loads(
            (self.out / "manifest.json").read_text())["version"], "1.2.4")

    def test_a_bad_version_is_refused(self):
        for bad in ("latest", "1.2", "v1.2.3.4", ""):
            with self.assertRaises(ValueError):
                pm.build(self.tmp / "x", bad)

    def test_the_cli_builds_and_exits_zero(self):
        self.assertEqual(pm.main(["--out", str(self.tmp / "cli"),
                                  "--version", "v0.0.1"]), 0)
        self.assertEqual(pm.main(["--out", str(self.tmp / "cli"),
                                  "--version", "nope"]), 2)


class Validator(unittest.TestCase):
    """The ported checks of `omarchy plugin validate` refuse what it does."""

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = pathlib.Path(td.name) / "p"
        shutil.copytree(ROOT / "shell-plugin", self.dir)
        self.m = json.loads((self.dir / "manifest.json").read_text())

    def put(self, **over):
        m = {**self.m, **over}
        (self.dir / "manifest.json").write_text(json.dumps(m))
        return pm.validate(self.dir)

    def test_each_rule(self):
        self.assertEqual(pm.validate(self.dir), [])
        self.assertTrue(self.put(schemaVersion="1"))
        self.assertTrue(self.put(schemaVersion=2))
        self.assertTrue(self.put(id="omarchy.wisp"))
        self.assertTrue(self.put(id="a/b"))
        self.assertTrue(self.put(id="a..b"))
        self.assertTrue(self.put(kinds=[]))
        self.assertTrue(self.put(entryPoints=[]))
        self.assertTrue(self.put(entryPoints={**self.m["entryPoints"],
                                              "service": "../x.qml"}))
        self.assertTrue(self.put(entryPoints={**self.m["entryPoints"],
                                              "service": "/etc/passwd"}))
        self.assertTrue(self.put(entryPoints={**self.m["entryPoints"],
                                              "service": "Nope.qml"}))
        self.assertTrue(self.put(kinds=[*self.m["kinds"], "panel"]))
        self.assertTrue(self.put(barWidget={"defaultSection": "top"}))
        self.assertEqual(self.put(), [])

    def test_missing_pieces_and_symlinks(self):
        (self.dir / "manifest.json").unlink()
        self.assertTrue(pm.validate(self.dir))
        (self.dir / "manifest.json").write_text("{nope")
        self.assertTrue(pm.validate(self.dir))
        (self.dir / "manifest.json").write_text(json.dumps(self.m))
        os.symlink("/etc/hosts", self.dir / "link")
        self.assertTrue(any("symlink" in p for p in pm.validate(self.dir)))


class FromPlugin(unittest.TestCase):
    """`wispd install --from-plugin`: the plan first, no edit unasked."""

    def setUp(self):
        self.e = cli_env.CliEnv()
        self.e.__enter__()
        self.addCleanup(self.e.__exit__, None, None, None)
        for name in ("systemctl", "hyprctl"):
            self.e.shim(name)
        hypr = self.e.home / ".config" / "hypr"
        hypr.mkdir(parents=True)
        self.bindings = hypr / "bindings.lua"
        self.bindings.write_text('o.bind("SUPER + T", "term", {})\n')
        self.before = self.bindings.read_text()
        self.plugin = (self.e.home / ".config" / "omarchy" / "plugins"
                       / PLUGIN_ID)
        self.plugin.mkdir(parents=True)
        (self.plugin / "owned-by-omarchy.txt").write_text("keep")
        self.opt = self.e.home / ".local" / "opt" / "wisp"

    def test_dry_run_lists_files_and_the_bind_and_writes_nothing(self):
        code, out, err = self.e.run(["install", "--from-plugin", "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertIn("bindings.lua", out)
        self.assertIn("wisp-trigger start", out)
        self.assertIn("wisp-trigger stop", out)
        self.assertIn("would write", out)
        self.assertNotIn(str(self.plugin), out.replace("<HOME>",
                                                       str(self.e.home)))
        self.assertEqual(self.bindings.read_text(), self.before)
        self.assertFalse(self.opt.exists())

    def test_plain_dry_run_now_lists_the_bind_too(self):
        code, out, _ = self.e.run(["install", "--dry-run"])
        self.assertEqual(code, 0)
        self.assertIn("would add to", out)
        self.assertEqual(self.bindings.read_text(), self.before)

    def test_without_a_terminal_and_without_yes_nothing_is_written(self):
        code, out, err = self.e.run(["install", "--from-plugin"], stdin="y\n")
        self.assertNotEqual(code, 0)
        self.assertIn("--yes", out + err)
        self.assertEqual(self.bindings.read_text(), self.before)
        self.assertFalse(self.opt.exists())

    def test_yes_installs_the_daemon_adds_the_bind_and_spares_the_plugin(self):
        code, out, err = self.e.run(["install", "--from-plugin", "--yes"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.opt / "wisp").is_dir())
        text = self.bindings.read_text()
        self.assertIn("wisp-trigger start", text)
        self.assertTrue(text.startswith(self.before))   # the user's line kept
        # the plugin folder is omarchy's (a git checkout): untouched
        self.assertEqual(sorted(p.name for p in self.plugin.iterdir()),
                         ["owned-by-omarchy.txt"])

    def test_the_plain_install_still_lays_the_plugin_down(self):
        code, out, err = self.e.run(["install"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.plugin / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
