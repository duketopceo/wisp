"""Release installer preflight; disposable HOME, no services, processes or Git."""
import contextlib
import importlib.machinery
import importlib.util
import io
import pathlib
import tempfile
import unittest
from unittest import mock

from wisp import config

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOADER = importlib.machinery.SourceFileLoader("wispd_release_edges", str(ROOT / "wispd"))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
WISPD = importlib.util.module_from_spec(SPEC)
LOADER.exec_module(WISPD)


class InstallReleaseEdges(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.work = pathlib.Path(temp.name)
        self.source = self.work / "source"
        files = {
            "wispd": "#!/usr/bin/env python3\n",
            "wisp/marker.py": "VERSION = 2\n",
            "wisp/nested/marker.py": "nested = True\n",
            "shells/debug/Main.qml": "// shell\n",
            "assets/desktop/wisp.desktop":
                (ROOT / "assets/desktop/wisp.desktop").read_text(),
            "assets/icons/hicolor/scalable/apps/wisp.svg": "<svg/>\n",
            "bin/wispd-rs": "synthetic binary, never executed\n",
            "scripts/units/wispd.service":
                (ROOT / "scripts/units/wispd.service").read_text(),
            "scripts/cua/PIN": "fixture\n",
            "scripts/bootstrap/install.py": "# fixture\n",
            "scripts/build_harness.py": "# fixture\n",
            "scripts/fetch_whisper.sh": "# fixture\n",
            "docs/INSTALL.md": "# fixture\n",
            "CHANGELOG.md": "# fixture\n",
        }
        for name, text in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def install(self, home, dry_run=False):
        with mock.patch.object(config, "HOME", home), \
                mock.patch("wisp.svc.shutil.which", return_value=None), \
                mock.patch("subprocess.run", side_effect=AssertionError("process denied")), \
                contextlib.redirect_stdout(io.StringIO()):
            WISPD.install_files(
                src=self.source, plugin=False, dry_run=dry_run,
                cfg={"local": {"enabled": "false"}},
                deploy={"repo": None, "ref": "v1.2.3", "commit": "a" * 40})

    def snapshot(self, home):
        return {str(path.relative_to(home)):
                None if path.is_dir() else path.read_bytes()
                for path in home.rglob("*")}

    def test_managed_directory_conflicts_are_rejected_before_any_writes(self):
        conflicts = (
            ".local/opt/wisp/assets",
            ".local/opt/wisp/wisp/nested",
            ".local/opt/wisp/shells/debug",
            ".local/opt/wisp/bin",
            ".local/opt/wisp/scripts",
            ".local/opt/wisp/scripts/units",
            ".local/opt/wisp/scripts/cua",
            ".local/opt/wisp/scripts/bootstrap",
            ".local/opt/wisp/docs",
            ".local/bin",
            ".local/share/applications",
            ".local/share/icons/hicolor/scalable/apps",
            ".config/systemd/user",
            ".local/opt/wisp",
        )
        for index, rel in enumerate(conflicts):
            with self.subTest(path=rel):
                home = self.work / f"home-{index}"
                conflict = home / rel
                conflict.parent.mkdir(parents=True)
                conflict.write_text("preserve existing user file")
                before = self.snapshot(home)
                caught = None
                try:
                    self.install(home)
                except (OSError, ValueError) as error:
                    caught = error
                self.assertEqual(self.snapshot(home), before,
                                 "preflight must precede every managed write")
                self.assertIsInstance(caught, ValueError)
                self.assertIn("Install path conflict", str(caught))
                self.assertIn(str(conflict), str(caught))

    def test_regular_file_destination_conflicts_preserve_the_existing_install(self):
        for index, rel in enumerate(("wisp/marker.py", "wispd", "plugin-mode",
                                     "build_harness.py", "deploy.json")):
            with self.subTest(path=rel):
                home = self.work / f"file-home-{index}"
                opt = home / ".local/opt/wisp"
                conflict = opt / rel
                conflict.mkdir(parents=True)
                (conflict / "user-content").write_text("keep")
                (opt / "old-runtime.txt").write_text("keep old version")
                before = self.snapshot(home)
                with self.assertRaisesRegex(ValueError, "Install path conflict"):
                    self.install(home)
                self.assertEqual(self.snapshot(home), before)

    def test_dry_run_reports_conflicts_without_mutation(self):
        home = self.work / "preview-home"
        conflict = home / ".local/opt/wisp/assets"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("keep")
        before = self.snapshot(home)
        with self.assertRaisesRegex(ValueError, "Install path conflict"):
            self.install(home, dry_run=True)
        self.assertEqual(self.snapshot(home), before)

    def test_valid_layout_installs_without_executing_services(self):
        home = self.work / "fresh-home"
        home.mkdir()
        self.install(home)
        opt = home / ".local/opt/wisp"
        self.assertEqual((opt / "wispd").read_bytes(),
                         (self.source / "wispd").read_bytes())
        self.assertTrue((opt / "deploy.json").is_file())
        self.assertTrue((home / ".local/bin/wispd").is_file())
        self.assertTrue((home / ".config/systemd/user/wispd.service").is_file())


if __name__ == "__main__":
    unittest.main()
