"""U1: the shared install/update preflight. Offline; every probe is a seam."""
import contextlib
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import preflight  # noqa: E402

GB = 1024 ** 3


class Preflight(unittest.TestCase):
    def run_pf(self, **kw):
        base = dict(system="Linux", machine="x86_64", py=(3, 12),
                    disk_free=lambda: 5 * GB,
                    which=lambda n: "/usr/bin/" + n, systemd=lambda: True,
                    record=None)
        base.update(kw)
        home = pathlib.Path(tempfile.gettempdir())
        return preflight.run(home, home / "opt", **base)

    def level(self, rows, id_):
        return next(r["level"] for r in rows if r["id"] == id_)

    def test_a_healthy_machine_has_no_blockers(self):
        self.assertEqual(preflight.blockers(self.run_pf()), [])

    def test_unsafe_home_blocks_source_install(self):
        for home in (pathlib.Path("/"), pathlib.Path("relative-home")):
            with self.subTest(home=home):
                rows = preflight.run(home, home / "opt", system="Linux",
                                     machine="aarch64", py=(3, 14, 8),
                                     disk_free=lambda: 5 * GB,
                                     which=lambda n: "/usr/bin/" + n,
                                     systemd=lambda: True, record={})
                self.assertIn("home", {r["id"] for r in rows})
                self.assertEqual(self.level(rows, "home"), "block")
                self.assertIn("desktop terminal", preflight.refusal(rows))

    def test_filesystem_root_aliases_block_source_install(self):
        with tempfile.TemporaryDirectory() as td:
            directory = pathlib.Path(td)
            root = pathlib.Path(directory.anchor)
            link = directory / "root-link"
            link.symlink_to(root, target_is_directory=True)
            for home in (root / directory.parts[1] / "..", link):
                with self.subTest(home=home):
                    rows = preflight.run(home, record={}, system="Linux",
                                         machine="aarch64", py=(3, 14, 8),
                                         disk_free=lambda: 5 * GB,
                                         which=lambda n: None, systemd=lambda: False)
                    self.assertEqual(self.level(rows, "home"), "block")

    def test_home_metadata_failure_blocks_without_an_unverified_disk_probe(self):
        with tempfile.TemporaryDirectory() as td:
            loop = pathlib.Path(td) / "loop"
            loop.symlink_to("loop", target_is_directory=True)
            cases = ((pathlib.Path(td), PermissionError(13, "denied")),
                     (pathlib.Path(td), OSError(5, "I/O error")), (loop, None))
            for home, error in cases:
                stat = (mock.patch("os.stat", side_effect=error)
                        if error else contextlib.nullcontext())
                with self.subTest(home=home, error=error), stat, \
                        mock.patch("shutil.disk_usage",
                                   side_effect=AssertionError("unverified home disk")):
                    try:
                        rows = preflight.run(home, record={}, system="Linux",
                                             machine="aarch64", py=(3, 14, 8),
                                             which=lambda n: None, systemd=lambda: False)
                    except (OSError, RuntimeError) as exc:
                        self.fail(f"HOME failure escaped: {type(exc).__name__}")
                    self.assertEqual(self.level(rows, "home"), "block")
                    self.assertEqual(self.level(rows, "disk space"), "degraded")

    def test_unsupported_architecture_blocks_with_a_fix(self):
        rows = self.run_pf(machine="riscv64")
        self.assertEqual(self.level(rows, "architecture"), "block")
        self.assertIn("No release is built", preflight.refusal(rows))

    def test_other_oses_block(self):
        self.assertEqual(self.level(self.run_pf(system="Darwin"), "os"),
                         "block")

    def test_python_patch_level_matches_bootstrap_minimum(self):
        for version, expected in (((3, 11, 0), "block"),
                                  ((3, 11, 3), "block"),
                                  ((3, 11, 4), "ok"),
                                  ((3, 14, 8), "ok")):
            with self.subTest(version=version):
                self.assertEqual(self.level(self.run_pf(py=version), "python"),
                                 expected)

    def test_insufficient_space_blocks(self):
        rows = self.run_pf(disk_free=lambda: 10 * 1024 * 1024)
        self.assertEqual(self.level(rows, "disk space"), "block")
        self.assertIn("Free at least", preflight.refusal(rows))

    def test_absent_systemd_degrades_and_does_not_block(self):
        rows = self.run_pf(systemd=lambda: False)
        self.assertEqual(self.level(rows, "systemd user"), "degraded")
        self.assertEqual(preflight.blockers(rows), [])

    def test_desktop_environment_is_not_claimed_as_live_access(self):
        for env, expected in (({}, "degraded"),
                              ({"XDG_RUNTIME_DIR": "/run/user/1000",
                                "WAYLAND_DISPLAY": "wayland-1",
                                "HYPRLAND_INSTANCE_SIGNATURE": "fixture"}, "ok")):
            with self.subTest(env=env), mock.patch.dict("os.environ", env, clear=True):
                rows = self.run_pf()
                self.assertIn("desktop session", {r["id"] for r in rows})
                row = next(r for r in rows if r["id"] == "desktop session")
                self.assertEqual(row["level"], expected)
                self.assertIn("not probed", row["detail"])
                self.assertEqual(preflight.blockers(rows), [])
                if expected == "degraded":
                    self.assertIn("desktop terminal", row["fix"])

    def test_missing_optional_tools_never_block(self):
        rows = self.run_pf(which=lambda n: None)
        self.assertEqual(preflight.blockers(rows), [])
        for name in ("opencode", "ollama", "hyprctl"):
            self.assertEqual(self.level(rows, name), "degraded")

    def test_desktop_audio_and_release_tools_have_actionable_optional_rows(self):
        rows = self.run_pf(which=lambda n: None)
        tools = {"quickshell", "ffmpeg", "wpctl", "wl-copy", "pw-play",
                 "notify-send", "espeak-ng", "gh", "git"}
        self.assertTrue(tools <= {r["id"] for r in rows})
        self.assertEqual(preflight.blockers(rows), [])
        for row in rows:
            if row["id"] in tools:
                self.assertEqual(row["level"], "degraded")
                self.assertIn("separately", row["fix"])

    def test_platform_fallback_tools_are_not_reported_missing(self):
        for name, alternative in (("wtype", "ydotool"),
                                  ("pw-play", "paplay"),
                                  ("pw-play", "aplay"),
                                  ("espeak-ng", "espeak")):
            with self.subTest(name=name, alternative=alternative):
                rows = self.run_pf(which=lambda n: "/usr/bin/" + n
                                   if n == alternative else None)
                row = next(r for r in rows if r["id"] == name)
                self.assertEqual(row["level"], "ok")
                self.assertEqual(row["detail"], "/usr/bin/" + alternative)

    def test_the_current_install_is_reported(self):
        rows = self.run_pf(record={"ref": "v1.2.3", "commit": "a" * 40})
        cur = next(r for r in rows if r["id"] == "current install")
        self.assertIn("v1.2.3", cur["detail"])
        none = next(r for r in self.run_pf(record={}) if
                    r["id"] == "current install")
        self.assertIn("none", none["detail"])

    def test_format_shows_every_row_or_only_problems(self):
        rows = self.run_pf(which=lambda n: None)
        self.assertIn("warn", preflight.format_rows(rows))
        self.assertNotIn(" ok  ", preflight.format_rows(
            rows, only_problems=True))


if __name__ == "__main__":
    unittest.main()
