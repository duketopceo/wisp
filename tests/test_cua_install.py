"""W10: scripts/cua/install.sh under a fake HOME. curl, systemctl and
hyprctl are stubs on PATH; nothing real runs, no network."""
import hashlib
import io
import os
import pathlib
import shutil
import subprocess
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cua" / "install.sh"
UNIT = ROOT / "scripts" / "cua" / "cua-driver.service"
PIN = ROOT / "scripts" / "cua" / "PIN"
PAYLOAD = b"#!/bin/sh\necho cua-driver 0.33.1\n"


def stub(path, name, body=""):
    f = path / name
    f.write_text(f'#!/bin/sh\necho "{name} $*" >> "$STUB_LOG"\n{body}\n')
    f.chmod(0o755)


def make_tar(path, members, prefix=""):
    """members: {name: bytes}; the driver goes in as an executable."""
    with tarfile.open(path, "w:gz") as t:
        for name, data in members.items():
            ti = tarfile.TarInfo(prefix + name)
            ti.size = len(data)
            ti.mode = 0o755 if name == "cua-driver" else 0o644
            t.addfile(ti, io.BytesIO(data))


GOOD = {"cua-driver": PAYLOAD, "libcua_driver_sdk.so": b"sdk",
        "wayland-helper/README.md": b"hi"}


class Rig:
    def __init__(self, sha=None, members=None, prefix="", bin_sha=None):
        self.td = tempfile.TemporaryDirectory()
        t = pathlib.Path(self.td.name)
        self.home, self.bin = t / "home", t / "bin"
        self.home.mkdir()
        self.bin.mkdir()
        self.log = t / "stub.log"
        self.log.touch()
        make_tar(t / "payload", members or GOOD, prefix)
        stub(self.bin, "systemctl")
        stub(self.bin, "hyprctl")
        stub(self.bin, "curl",
             'out=""; while [ $# -gt 0 ]; do '
             'if [ "$1" = -o ]; then out="$2"; fi; shift; done; '
             'cp "$STUB_PAYLOAD" "$out"')
        self.pin = t / "PIN"
        good = hashlib.sha256((t / "payload").read_bytes()).hexdigest()
        sha = sha or good
        bsha = bin_sha or hashlib.sha256(PAYLOAD).hexdigest()
        self.pin.write_text(
            "CUA_VERSION=0.33.1\n"
            "CUA_URL_AARCH64=https://example.invalid/cua-driver-aarch64\n"
            f"CUA_SHA256_AARCH64={sha}\n"
            f"CUA_BIN_SHA256_AARCH64={bsha}\n"
            "CUA_URL_X86_64=https://example.invalid/cua-driver-x86_64\n"
            f"CUA_SHA256_X86_64={sha}\n")
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin",
                    "HOME": str(self.home), "STUB_LOG": str(self.log),
                    "STUB_PAYLOAD": str(t / "payload"),
                    "CUA_PIN_FILE": str(self.pin), "TMPDIR": str(t)}

    def run(self, *args):
        return subprocess.run(["bash", str(SCRIPT), *args], env=self.env,
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        return self.log.read_text().splitlines()

    @property
    def binary(self):
        return self.home / ".local/share/cua-driver/cua-driver"

    @property
    def unit(self):
        return self.home / ".config/systemd/user/cua-driver.service"

    def tree(self):
        return sorted(str(p.relative_to(self.home))
                      for p in self.home.rglob("*"))

    def close(self):
        self.td.cleanup()


class Installer(unittest.TestCase):
    def setUp(self):
        self.r = Rig()
        self.addCleanup(self.r.close)

    def test_install_writes_binary_unit_and_registers(self):
        p = self.r.run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.r.binary.read_bytes(), PAYLOAD)
        self.assertTrue(os.access(self.r.binary, os.X_OK))
        sib = self.r.binary.parent
        self.assertEqual((sib / "libcua_driver_sdk.so").read_bytes(), b"sdk")
        self.assertTrue((sib / "wayland-helper/README.md").exists())
        unit = self.r.unit.read_text()
        self.assertIn("ExecStart=%h/.local/share/cua-driver/cua-driver serve",
                      unit)
        self.assertIn("Slice=session.slice", unit)
        self.assertIn("MemoryMax=512M", unit)
        link = self.r.home / ".local/bin/cua-driver"
        self.assertEqual(os.path.realpath(link), str(self.r.binary))
        calls = self.r.calls()
        self.assertTrue(any(c.startswith("curl") for c in calls))
        self.assertIn("systemctl --user daemon-reload", calls)
        self.assertIn("systemctl --user enable --now cua-driver.service",
                      calls)
        self.assertFalse(any("sudo" in c for c in calls))

    def test_second_run_is_idempotent(self):
        self.assertEqual(self.r.run().returncode, 0)
        tree1 = self.r.tree()
        mtime = self.r.binary.stat().st_mtime_ns
        self.r.log.write_text("")
        p = self.r.run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.r.tree(), tree1)
        self.assertEqual(self.r.binary.stat().st_mtime_ns, mtime)
        self.assertFalse(any(c.startswith("curl") for c in self.r.calls()),
                         "second run must not download again")
        self.assertIn("already", p.stdout)

    def test_checksum_mismatch_refuses_and_writes_nothing(self):
        bad = Rig(sha="0" * 64)
        self.addCleanup(bad.close)
        p = bad.run()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("checksum", (p.stdout + p.stderr).lower())
        self.assertFalse(bad.binary.exists())
        self.assertFalse(bad.unit.exists())
        self.assertFalse(any(c.startswith("systemctl")
                             for c in bad.calls()))

    def test_nested_layout_is_located(self):
        n = Rig(prefix="pkg/")
        self.addCleanup(n.close)
        p = n.run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(n.binary.read_bytes(), PAYLOAD)

    def test_path_traversal_member_refused(self):
        bad = Rig(members=dict(GOOD, **{"../evil": b"x"}))
        self.addCleanup(bad.close)
        p = bad.run()
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("refusing", p.stderr)
        self.assertFalse(bad.binary.exists())
        self.assertFalse(bad.unit.exists())
        self.assertFalse((bad.home.parent / "evil").exists())

    def test_absolute_member_refused(self):
        bad = Rig(members=dict(GOOD, **{"/tmp/w10-evil": b"x"}))
        self.addCleanup(bad.close)
        self.assertNotEqual(bad.run().returncode, 0)
        self.assertFalse(bad.binary.exists())

    def test_binary_sha_mismatch_refused(self):
        bad = Rig(bin_sha="1" * 64)
        self.addCleanup(bad.close)
        self.assertNotEqual(bad.run().returncode, 0)
        self.assertFalse(bad.binary.exists())

    def test_no_driver_in_archive_refused(self):
        bad = Rig(members={"readme": b"x"})
        self.addCleanup(bad.close)
        self.assertNotEqual(bad.run().returncode, 0)

    def test_existing_wrong_binary_is_replaced_only_by_verified_one(self):
        self.r.binary.parent.mkdir(parents=True)
        self.r.binary.write_bytes(b"old")
        p = self.r.run()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.r.binary.read_bytes(), PAYLOAD)

    def test_dry_run_prints_plan_and_writes_nothing(self):
        p = self.r.run("--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.r.tree(), [])
        self.assertEqual(self.r.calls(), [])
        for word in ("0.33.1", "cua-driver.service", "sha256",
                     "example.invalid"):
            self.assertIn(word, p.stdout)
        self.assertIn("dry run", p.stdout.lower())

    def test_missing_pin_for_arch_refuses(self):
        self.r.pin.write_text("CUA_VERSION=0.33.1\n")
        p = self.r.run()
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(self.r.binary.exists())

    def test_unknown_flag_is_usage_error(self):
        p = self.r.run("--bogus")
        self.assertEqual(p.returncode, 2)


class Shipped(unittest.TestCase):
    def test_pin_has_version_and_both_arches(self):
        t = PIN.read_text()
        self.assertRegex(t, r"(?m)^CUA_VERSION=\d+\.\d+\.\d+$")
        self.assertRegex(t, r"(?m)^CUA_SHA256_AARCH64=[0-9a-f]{64}$")
        self.assertRegex(t, r"(?m)^CUA_BIN_SHA256_AARCH64=[0-9a-f]{64}$")
        self.assertRegex(t, r"(?m)^CUA_SHA256_X86_64=[0-9a-f]{64}$")
        self.assertIn("cua-driver-rs-v", t)

    def test_unit_template_matches_machine_unit_plus_limits(self):
        t = UNIT.read_text()
        self.assertIn("CUA_DRIVER_RS_ENABLE_WAYLAND=1", t)
        self.assertIn("Restart=on-failure", t)
        self.assertIn("WantedBy=default.target", t)

    def test_script_is_executable_shell(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        p = subprocess.run(["bash", "-n", str(SCRIPT)])
        self.assertEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
