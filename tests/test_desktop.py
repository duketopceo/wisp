#!/usr/bin/env python3
"""Launcher entry, desktop actions and idempotent desktop install (W27)."""
import configparser
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import desktop  # noqa: E402

SRC = ROOT / "assets" / "desktop" / "wisp.desktop"
SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def parse(text):
    cp = configparser.RawConfigParser(strict=False)
    cp.optionxform = str
    cp.read_string(text)
    return cp


class Runner:
    """Stub for subprocess: records calls, pretends tools exist."""
    def __init__(self, present=("update-desktop-database",
                                "gtk-update-icon-cache")):
        self.calls = []
        self.present = set(present)

    def which(self, name):
        return f"/usr/bin/{name}" if name in self.present else None

    def run(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")


class TestTemplate(unittest.TestCase):
    def test_validates(self):
        exe = shutil.which("desktop-file-validate")
        if not exe:
            self.skipTest("desktop-file-validate not installed")
        r = subprocess.run([exe, str(SRC)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_rendered_validates(self):
        exe = shutil.which("desktop-file-validate")
        if not exe:
            self.skipTest("desktop-file-validate not installed")
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "wisp.desktop"
            p.write_text(desktop.render(pathlib.Path("/home/a b/.local/opt/wisp")))
            r = subprocess.run([exe, str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_actions_declared_and_defined(self):
        cp = parse(desktop.render(pathlib.Path("/o")))
        self.assertEqual(cp["Desktop Entry"]["Name"], "Wisp")
        acts = cp["Desktop Entry"]["Actions"].rstrip(";").split(";")
        self.assertEqual(acts, ["Listen", "Stop", "Panel"])
        for a in acts:
            self.assertIn(f"Desktop Action {a}", cp)
            self.assertTrue(cp[f"Desktop Action {a}"]["Name"])

    def test_action_command_mapping(self):
        cp = parse(desktop.render(pathlib.Path("/o")))
        self.assertEqual(cp["Desktop Action Listen"]["Exec"],
                         "/o/wispd trigger")
        self.assertEqual(cp["Desktop Action Stop"]["Exec"],
                         "/o/wispd interrupt")
        self.assertEqual(cp["Desktop Action Panel"]["Exec"],
                         "quickshell -n -p /o/shells/debug")
        self.assertEqual(cp["Desktop Entry"]["Exec"],
                         cp["Desktop Action Panel"]["Exec"])

    def test_exec_quoting_for_spaces(self):
        cp = parse(desktop.render(pathlib.Path("/home/a b/opt")))
        self.assertEqual(cp["Desktop Action Listen"]["Exec"],
                         '"/home/a b/opt/wispd" trigger')
        self.assertEqual(cp["Desktop Action Panel"]["Exec"],
                         'quickshell -n -p "/home/a b/opt/shells/debug"')

    def test_exec_quote_escapes(self):
        self.assertEqual(desktop.exec_arg('/a"b'), '"/a\\\\"b"')
        self.assertEqual(desktop.exec_arg("/a$b"), '"/a\\\\$b"')
        self.assertEqual(desktop.exec_arg("/plain"), "/plain")

    def test_no_unexpanded_placeholders(self):
        self.assertNotIn("@", desktop.render(pathlib.Path("/o")).replace(
            "@wisp", ""))


class TestInstall(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self._td.name)
        self.opt = self.home / ".local/opt/wisp"
        self.app = self.home / ".local/share/applications/wisp.desktop"
        self.icons = self.home / ".local/share/icons/hicolor"

    def tearDown(self):
        self._td.cleanup()

    def go(self, **kw):
        r = Runner(**kw.pop("runner", {}))
        res = desktop.install(ROOT, self.home, self.opt, runner=r, **kw)
        return res, r

    def test_writes_desktop_and_icons(self):
        res, r = self.go()
        self.assertTrue(self.app.is_file())
        for n in SIZES:
            self.assertTrue((self.icons / f"{n}x{n}/apps/wisp.png").is_file())
        self.assertTrue((self.icons / "scalable/apps/wisp.svg").is_file())
        self.assertIn("Icon=wisp\n", self.app.read_text())
        self.assertIn(str(self.opt), self.app.read_text())

    def test_idempotent(self):
        self.go()
        before = {p: p.stat().st_mtime_ns for p in self.home.rglob("*")
                  if p.is_file()}
        res, r = self.go()
        after = {p: p.stat().st_mtime_ns for p in self.home.rglob("*")
                 if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(res["written"], [])
        self.assertEqual(r.calls, [])  # nothing changed: no cache refresh
        self.assertEqual(list(self.app.parent.glob("*.bak*")), [])

    def test_upgrade_of_managed_file_no_backup(self):
        self.go()
        self.app.write_text(self.app.read_text().replace(
            "Name=Wisp\n", "Name=Wisp\n", 1))
        # simulate an older managed version: rewrite with valid marker
        old = desktop.stamp("[Desktop Entry]\nName=Old\n")
        self.app.write_text(old)
        self.go()
        self.assertEqual(list(self.app.parent.glob("*.bak*")), [])
        self.assertIn("Actions=", self.app.read_text())

    def test_user_modified_file_backed_up(self):
        self.go()
        mine = self.app.read_text() + "# my edit\n"
        self.app.write_text(mine)
        res, _ = self.go()
        baks = list(self.app.parent.glob("wisp.desktop.bak*"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(), mine)
        self.assertNotIn("my edit", self.app.read_text())

    def test_legacy_unmarked_file_backed_up(self):
        self.app.parent.mkdir(parents=True)
        self.app.write_text("[Desktop Entry]\nName=Wisp\nType=Application\n")
        self.go()
        self.assertEqual(len(list(self.app.parent.glob("wisp.desktop.bak*"))), 1)

    def test_second_backup_does_not_clobber_first(self):
        self.go()
        self.app.write_text("one\n")
        self.go()
        self.app.write_text("two\n")
        self.go()
        texts = sorted(p.read_text() for p in
                       self.app.parent.glob("wisp.desktop.bak*"))
        self.assertEqual(texts, ["one\n", "two\n"])

    def test_dry_run_writes_nothing(self):
        res, r = self.go(dry_run=True)
        self.assertEqual(list(self.home.rglob("*")), [])
        self.assertEqual(r.calls, [])
        self.assertTrue(res["dry_run"])
        self.assertTrue(any(str(self.app) == w for w in res["written"]))

    def test_dry_run_reports_backup(self):
        self.app.parent.mkdir(parents=True)
        self.app.write_text("custom\n")
        res, _ = self.go(dry_run=True)
        self.assertEqual(self.app.read_text(), "custom\n")
        self.assertEqual(res["backups"], [str(self.app) + ".bak"])

    def test_cache_tools_run_when_present(self):
        _, r = self.go()
        names = [pathlib.Path(c[0]).name for c in r.calls]
        self.assertIn("update-desktop-database", names)
        self.assertIn("gtk-update-icon-cache", names)

    def test_cache_tools_skipped_when_absent(self):
        _, r = self.go(runner={"present": ()})
        self.assertEqual(r.calls, [])
        self.assertTrue(self.app.is_file())

    def test_icon_sizes_present_in_source(self):
        for n in SIZES:
            self.assertTrue(
                (ROOT / f"assets/icons/hicolor/{n}x{n}/apps/wisp.png").is_file())

    def test_install_files_wires_in(self):
        import importlib.machinery
        import importlib.util
        from wisp import config
        loader = importlib.machinery.SourceFileLoader("wispd_mod", str(ROOT / "wispd"))
        spec = importlib.util.spec_from_loader("wispd_mod", loader)
        w = importlib.util.module_from_spec(spec)
        loader.exec_module(w)
        with mock.patch.object(config, "HOME", self.home), \
             mock.patch.object(w.subprocess, "run"), \
             mock.patch("wisp.platform.current", return_value="linux"):
            w.install_files()
        self.assertIn("Actions=Listen;Stop;Panel;", self.app.read_text())
        with mock.patch.object(config, "HOME", self.home), \
             mock.patch("wisp.platform.current", return_value="linux"):
            before = self.app.read_text()
            w.install_files(dry_run=True)
            self.assertEqual(before, self.app.read_text())


class TestTrayDetect(unittest.TestCase):
    def test_host_present(self):
        out = "NAME PID\norg.kde.StatusNotifierWatcher 7533 quickshell\n"
        r = mock.Mock(return_value=subprocess.CompletedProcess([], 0, out, ""))
        self.assertTrue(desktop.sni_host_present(run=r, which=lambda n: "/b"))

    def test_host_absent_or_no_busctl(self):
        r = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "x\n", ""))
        self.assertFalse(desktop.sni_host_present(run=r, which=lambda n: "/b"))
        self.assertFalse(desktop.sni_host_present(run=r, which=lambda n: None))

    def test_detection_is_read_only(self):
        r = mock.Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        desktop.sni_host_present(run=r, which=lambda n: "/b")
        cmd = r.call_args[0][0]
        self.assertEqual(cmd[:3], ["busctl", "--user", "list"])


if __name__ == "__main__":
    unittest.main()
