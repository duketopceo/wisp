"""U2: pinned ori/OpenCode installer. The fetch is injected and the
payloads are local fixtures with computed hashes; no network."""
import hashlib
import io
import os
import pathlib
import tarfile
import tempfile
import unittest

from wisp import agent_install, agent_pins


def script(version):
    return f"#!/bin/sh\necho {version}\n".encode()


def tar_bytes(members, links=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name, data in members.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))
        for name, target in links:
            ti = tarfile.TarInfo(name)
            ti.type = tarfile.SYMTYPE
            ti.linkname = target
            t.addfile(ti)
    return buf.getvalue()


class Rig:
    """A served payload per tool, hashed into the pin the installer sees."""

    def __init__(self, test, opencode=None, ori=None):
        self.td = tempfile.TemporaryDirectory()
        test.addCleanup(self.td.cleanup)
        self.root = pathlib.Path(self.td.name) / "agent-runtime"
        self.served = {
            "opencode": opencode if opencode is not None else tar_bytes(
                {"opencode": script("2.2.0")}),
            "ori": ori if ori is not None else script("ori 0.16.1")}
        self.fetched = []

    def pin(self, tool, arch):
        if arch not in ("arm64", "x64"):
            return None
        data = self.served[tool]
        ver = {"ori": agent_pins.ORI_VERSION,
               "opencode": agent_pins.OPENCODE_VERSION}[tool]
        return {"version": ver, "url": f"https://example.invalid/{tool}",
                "sha256": hashlib.sha256(data).hexdigest(),
                "archive": tool == "opencode"}

    def fetch(self, url, dest):
        self.fetched.append(url)
        pathlib.Path(dest).write_bytes(self.served[url.rsplit("/", 1)[1]])

    def install(self, tool, arch="arm64"):
        return agent_install.install(tool, arch, fetch=self.fetch,
                                     dest_root=self.root, pin_fn=self.pin)

    def tree(self):
        return sorted(p for p in self.root.rglob("*")) \
            if self.root.exists() else []


class InstallTests(unittest.TestCase):
    def test_match_installs_and_flips_current(self):
        r = Rig(self)
        res = r.install("opencode")
        self.assertEqual(res.status, "installed", res.reason)
        vdir = r.root / "opencode" / "2.2.0"
        self.assertTrue((vdir / "opencode").exists())
        cur = r.root / "opencode" / "current"
        self.assertTrue(cur.is_symlink())
        self.assertEqual(cur.resolve(), vdir.resolve())
        self.assertEqual(agent_pins.runtime_paths(r.root)["opencode"],
                         cur / "opencode")
        self.assertTrue(os.access(cur / "opencode", os.X_OK))

    def test_bare_binary_ori_installs(self):
        r = Rig(self)
        self.assertEqual(r.install("ori").status, "installed")
        self.assertTrue(
            (r.root / "ori" / "current" / "ori").exists())

    def test_digest_mismatch_writes_nothing(self):
        r = Rig(self)
        real = r.pin

        def bad(tool, arch):
            p = real(tool, arch)
            p["sha256"] = "0" * 64
            return p
        res = agent_install.install("opencode", "x64", fetch=r.fetch,
                                    dest_root=r.root, pin_fn=bad)
        self.assertEqual(res.status, "failed")
        self.assertIn("opencode", res.reason)
        self.assertEqual(r.tree(), [])

    def test_unsafe_tar_members_refused(self):
        for label, data in (
                ("absolute", tar_bytes({"/etc/evil": b"x"})),
                ("dotdot", tar_bytes({"../evil": b"x"})),
                ("symlink", tar_bytes({"opencode": script("2.2.0")},
                                      links=[("lnk", "/etc/passwd")]))):
            with self.subTest(label):
                r = Rig(self, opencode=data)
                res = r.install("opencode")
                self.assertEqual(res.status, "failed")
                self.assertEqual(r.tree(), [])

    def test_second_install_is_already_without_fetching(self):
        r = Rig(self)
        r.install("opencode")
        r.fetched.clear()
        self.assertEqual(r.install("opencode").status, "already")
        self.assertEqual(r.fetched, [])

    def test_opencode_v1_is_not_promoted(self):
        r = Rig(self, opencode=tar_bytes({"opencode": script("1.19.5")}))
        res = r.install("opencode")
        self.assertEqual(res.status, "failed")
        self.assertIn("1.19.5", res.reason)
        self.assertFalse((r.root / "opencode" / "current").exists())

    def test_unsupported_arch(self):
        r = Rig(self)
        res = r.install("ori", "riscv64")
        self.assertEqual(res.status, "failed")
        self.assertIn("no build for riscv64", res.reason)

    def test_placeholder_pin_refuses_to_run(self):
        # the shipped pins stay placeholders until the orchestrator fills
        # them; install must refuse rather than skip verification
        r = Rig(self)
        fetched = []
        res = agent_install.install(
            "ori", "arm64", fetch=lambda u, d: fetched.append(u),
            dest_root=r.root,
            pin_fn=lambda t, a: {**r.pin(t, a),
                                 "sha256": "TODO-fill-from-SHA256SUMS"})
        self.assertEqual(res.status, "failed")
        self.assertIn("placeholder", res.reason)
        self.assertEqual(fetched, [])
        self.assertEqual(r.tree(), [])


class PinsTests(unittest.TestCase):
    def test_pin_table_shape(self):
        p = agent_pins.pin("opencode", "arm64")
        self.assertEqual(p["version"], "2.2.0")
        self.assertIn("anomalyco/opencode/releases/download/v2.2.0/"
                      "opencode-linux-arm64.tar.gz", p["url"])
        q = agent_pins.pin("ori", "x64")
        self.assertIn("cli-0.16.1-91f9f29/ori-linux-x64", q["url"])
        self.assertIsNone(agent_pins.pin("ori", "mips"))
        self.assertEqual(agent_pins.OPENCODE_MAJOR, 2)

    def test_is_placeholder(self):
        self.assertFalse(agent_pins.is_placeholder("a" * 64))
        self.assertTrue(agent_pins.is_placeholder("TODO"))


if __name__ == "__main__":
    unittest.main()
