"""U1: the shared install/update preflight. Offline; every probe is a seam."""
import pathlib
import sys
import tempfile
import unittest

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

    def test_unsupported_architecture_blocks_with_a_fix(self):
        rows = self.run_pf(machine="riscv64")
        self.assertEqual(self.level(rows, "architecture"), "block")
        self.assertIn("No release is built", preflight.refusal(rows))

    def test_other_oses_block(self):
        self.assertEqual(self.level(self.run_pf(system="Darwin"), "os"),
                         "block")

    def test_insufficient_space_blocks(self):
        rows = self.run_pf(disk_free=lambda: 10 * 1024 * 1024)
        self.assertEqual(self.level(rows, "disk space"), "block")
        self.assertIn("Free at least", preflight.refusal(rows))

    def test_absent_systemd_degrades_and_does_not_block(self):
        rows = self.run_pf(systemd=lambda: False)
        self.assertEqual(self.level(rows, "systemd user"), "degraded")
        self.assertEqual(preflight.blockers(rows), [])

    def test_missing_optional_tools_never_block(self):
        rows = self.run_pf(which=lambda n: None)
        self.assertEqual(preflight.blockers(rows), [])
        for name in ("opencode", "ollama", "hyprctl"):
            self.assertEqual(self.level(rows, name), "degraded")

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
