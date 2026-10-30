"""Release payload tests: real source files, no network or desktop session."""
import hashlib
import io
import json
import pathlib
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BUILD = ROOT / "scripts" / "release" / "build.py"
VERIFY = ROOT / "scripts" / "release" / "verify.py"
COMMIT = "a" * 40
VERSION = "v1.2.3"
EPOCH = "1793383200"


class ReleasePackagingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = pathlib.Path(self.temp.name)
        self.binary = self.work / "wispd-rs"
        # A synthetic ELF header tests staging, never execution of a fake daemon.
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", header, 18, 62)
        self.binary.write_bytes(header)
        self.binary.chmod(0o755)

    def bundle(self, out="dist", source=ROOT, binary=None, target="linux-x86_64"):
        dest = self.work / out
        result = subprocess.run(
            [sys.executable, str(BUILD), "bundle", "--source", str(source),
             "--binary", str(binary or self.binary), "--target", target,
             "--version", VERSION, "--commit", COMMIT, "--epoch", EPOCH,
             "--out", str(dest)],
            text=True, capture_output=True, timeout=60,
        )
        return result, dest / f"wisp-{target}.tar.gz"

    def test_bundle_contains_fresh_install_runtime_payload(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(archive) as tf:
            prefix = "wisp-linux-x86_64/"
            names = {m.name.removeprefix(prefix) for m in tf.getmembers()}
            required = {
                "wispd", "bin/wispd-rs", "CHANGELOG.md", "LICENSE",
                "THIRD_PARTY_NOTICES.md", "pyproject.toml",
                "wisp/budgets.json", "wisp/skills_seed/apps/github/SKILL.md",
                "wisp/skills_seed/self-checkup/SKILL.md",
                "assets/desktop/wisp.desktop",
                "assets/icons/hicolor/scalable/apps/wisp.svg",
                "shell-plugin/shaders/wisp.frag.qsb",
                "shells/debug/components/Icon.qml",
                "shells/debug/WispService.qml",
                "scripts/units/wispd.service", "scripts/cua/PIN",
                "scripts/cua/install.sh", "scripts/cua/cua-driver.service",
                "scripts/build_harness.py", "scripts/fetch_whisper.sh",
                "scripts/bootstrap/install.py",
                "browser-extension/manifest.json", "browser-extension/lib.js",
                "browser-extension/background.js", "browser-extension/popup.js",
                "browser-extension/popup.html",
                "release.json", "payload.json", "docs/INSTALL.md",
            }
            self.assertFalse(required - names, sorted(required - names))
            for file in (ROOT / "wisp").rglob("*"):
                if file.is_file() and file.suffix in {".py", ".md", ".json"}:
                    self.assertIn(str(file.relative_to(ROOT)), names)
            self.assertTrue(all(not m.issym() and not m.islnk()
                                for m in tf.getmembers()))
            self.assertEqual(tf.getmember(prefix + "bin/wispd-rs").mode, 0o755)
            self.assertEqual(tf.getmember(prefix + "wispd").mode, 0o755)
            metadata = json.load(tf.extractfile(prefix + "release.json"))
            self.assertEqual(metadata["version"], VERSION)
            self.assertEqual(metadata["commit"], COMMIT)
            self.assertEqual(metadata["target"], "linux-x86_64")
            self.assertEqual(metadata["source_date_epoch"], int(EPOCH))
            manifest = json.load(tf.extractfile(prefix + "shell-plugin/manifest.json"))
            self.assertEqual(manifest["version"], VERSION[1:])

    def test_release_checksums_are_sorted_and_reproducible(self):
        first, one = self.bundle("one")
        second, two = self.bundle("two")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(one.read_bytes(), two.read_bytes())
        # Same content, deliberately reversed input order.
        other = one.with_name("wisp-plugin-v1.2.3.tar.gz")
        other.write_bytes(b"plugin asset")
        sums = one.parent / "SHA256SUMS"
        result = subprocess.run(
            [sys.executable, str(BUILD), "checksums", "--out", str(sums),
             str(other), str(one)], text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                           for p in sorted((one, other)))
        self.assertEqual(sums.read_text(), expected)
        with tarfile.open(one) as tf:
            entries = {m.name.split("/", 1)[1]: m for m in tf.getmembers()}
            inventory = json.load(tf.extractfile(entries["payload.json"]))["files"]
            self.assertEqual(set(inventory), set(entries) - {"payload.json"})
            for name, row in inventory.items():
                content = tf.extractfile(entries[name]).read()
                self.assertEqual(hashlib.sha256(content).hexdigest(), row["sha256"])
                self.assertEqual(len(content), row["size"])
                self.assertEqual(entries[name].mode, row["mode"])
                self.assertEqual(entries[name].mtime, int(EPOCH))
                self.assertEqual((entries[name].uid, entries[name].gid), (0, 0))

    def source_copy(self):
        source = self.work / "source"
        source.mkdir()
        for name in ("wisp", "shells", "shell-plugin", "assets", "docs", "scripts",
                     "browser-extension"):
            shutil.copytree(ROOT / name, source / name, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                         "release", "build"))
        for name in ("wispd", "LICENSE", "README.md", "CHANGELOG.md",
                     "THIRD_PARTY_NOTICES.md", "pyproject.toml"):
            shutil.copy2(ROOT / name, source / name)
        return source

    def test_unwanted_local_files_are_not_packaged(self):
        source = self.source_copy()
        forbidden = ("wisp/.env", "wisp/.env.production", "assets/node_modules/x",
                     "shell-plugin/build/bundle.js", "wisp/cache/token",
                     "wisp/__pycache__/config.pyc", "docs/.cache/render",
                     "scripts/cua/dist/helper", "wisp/.venv/key")
        for name in forbidden:
            p = source / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("private sentinel")
        result, archive = self.bundle(source=source)
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(archive) as tf:
            names = {m.name.split("/", 1)[1] for m in tf.getmembers()}
            self.assertFalse(set(forbidden) & names)
            self.assertFalse(any(b"private sentinel" in tf.extractfile(m).read()
                                 for m in tf.getmembers()))

    def test_source_links_must_stay_inside_source(self):
        source = self.source_copy()
        secret = self.work / "secret"
        secret.write_text("do not ship")
        (source / "wisp" / "leak.py").symlink_to(secret)
        result, archive = self.bundle(source=source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("escapes source", result.stderr)
        self.assertFalse(archive.exists())

    def test_output_cannot_be_inside_a_packaged_source_tree(self):
        source = self.source_copy()
        result, archive = self.bundle(out=str(source / "wisp"), source=source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("output", result.stderr)
        self.assertFalse(archive.exists())

    def test_binary_must_match_the_selected_linux_architecture(self):
        for binary, target in ((ROOT / "wispd", "linux-x86_64"),
                               (self.binary, "linux-aarch64")):
            with self.subTest(binary=binary, target=target):
                result, archive = self.bundle(binary=binary, target=target)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ELF", result.stderr)
                self.assertFalse(archive.exists())
        link = self.work / "linked-binary"
        link.symlink_to(self.binary)
        result, archive = self.bundle(binary=link)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a symlink", result.stderr)
        self.assertFalse(archive.exists())

    def verify(self, archive):
        return subprocess.run(
            [sys.executable, str(VERIFY), "--archive", str(archive),
             "--sha256", hashlib.sha256(archive.read_bytes()).hexdigest(),
             "--version", VERSION, "--commit", COMMIT,
             "--target", "linux-x86_64"],
            text=True, capture_output=True, timeout=60,
        )

    def test_extracted_release_passes_real_cli_install_dry_run_offline(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.verify(archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["version"], VERSION)
        self.assertEqual(report["commit"], COMMIT)
        self.assertEqual(report["target"], "linux-x86_64")
        self.assertEqual(report["install_dry_run"], "passed")
        self.assertEqual(report["network_and_processes"], "denied")
        self.assertEqual(report["rust_binary_executed"], False)
        self.assertEqual(report["desktop_and_voice_smoke"], "not run")
        self.assertGreater(report["files_verified"], 100)

    def test_archive_installs_complete_resources_in_an_isolated_home(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.verify(archive)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report.get("isolated_install"), "passed")
        self.assertEqual(report.get("installed_version"), VERSION)
        self.assertGreater(report.get("installed_files_verified", 0), 100)

    def test_plugin_asset_uses_the_same_deterministic_archive_format(self):
        mirror = self.work / "mirror"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "plugin_mirror.py"),
             "--out", str(mirror), "--version", VERSION, "--commit", COMMIT],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        archives = []
        for name in ("plugin-one", "plugin-two"):
            out = self.work / name
            result = subprocess.run(
                [sys.executable, str(BUILD), "plugin", "--source", str(mirror),
                 "--out", str(out), "--epoch", EPOCH, "--version", VERSION],
                text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            archives.append(out / f"wisp-plugin-{VERSION}.tar.gz")
        self.assertEqual(archives[0].read_bytes(), archives[1].read_bytes())
        with tarfile.open(archives[0]) as tf:
            manifest = json.load(tf.extractfile("mirror/manifest.json"))
            self.assertEqual(manifest["version"], VERSION[1:])
            self.assertIn(COMMIT, tf.extractfile("mirror/README.md").read().decode())
            self.assertTrue(all(m.mtime == int(EPOCH) for m in tf.getmembers()))

    def rewrite_archive(self, archive, changes):
        """Preserve a valid inventory when testing the offline CLI guard."""
        with tarfile.open(archive) as tf:
            members = {m.name: (tf.extractfile(m).read(), m.mode)
                       for m in tf.getmembers()}
        prefix = "wisp-linux-x86_64/"
        members.update({prefix + name: (data, members[prefix + name][1])
                        for name, data in changes.items()})
        inventory = json.loads(members[prefix + "payload.json"][0])
        for name, data in changes.items():
            inventory["files"][name]["sha256"] = hashlib.sha256(data).hexdigest()
            inventory["files"][name]["size"] = len(data)
        members[prefix + "payload.json"] = (json.dumps(inventory).encode(), 0o644)
        rewritten = self.work / "rewritten.tar.gz"
        with tarfile.open(rewritten, "w:gz") as tf:
            for name, (data, mode) in sorted(members.items()):
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                tf.addfile(info, io.BytesIO(data))
        return rewritten

    def test_verifier_rejects_payload_tampering(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        altered = self.rewrite_archive(archive, {"wispd": b"print('changed')\n"})
        # Remove the deliberately refreshed inventory hash to simulate corruption.
        with tarfile.open(altered) as tf:
            rows = {m.name: (tf.extractfile(m).read(), m.mode)
                    for m in tf.getmembers()}
        path = "wisp-linux-x86_64/wispd"
        rows[path] = (b"print('tampered')\n", rows[path][1])
        with tarfile.open(altered, "w:gz") as tf:
            for name, (data, mode) in rows.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                tf.addfile(info, io.BytesIO(data))
        result = self.verify(altered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inventory mismatch: wispd", result.stderr)

    def test_verifier_denies_network_even_with_a_valid_inventory(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        altered = self.rewrite_archive(archive, {
            "wispd": b"import socket\nsocket.socket().connect(('127.0.0.1', 9))\n",
        })
        result = self.verify(altered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("denied side effect: socket.", result.stderr)

    def test_verifier_denies_child_processes_even_with_a_valid_inventory(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        altered = self.rewrite_archive(archive, {
            "wispd": b"import subprocess\nsubprocess.run(['/usr/bin/true'])\n",
        })
        result = self.verify(altered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("denied side effect: subprocess.Popen", result.stderr)

    def test_verifier_denies_file_writes_even_with_a_valid_inventory(self):
        result, archive = self.bundle()
        self.assertEqual(result.returncode, 0, result.stderr)
        altered = self.rewrite_archive(archive, {
            "wispd": b"from pathlib import Path\nPath('sentinel').write_text('bad')\n",
        })
        result = self.verify(altered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("denied file write", result.stderr)

    def test_verifier_rejects_unsafe_archive_members_before_extraction(self):
        archive = self.work / "unsafe.tar.gz"
        for name, kind in (("../outside", tarfile.REGTYPE),
                           ("/tmp/outside", tarfile.REGTYPE),
                           ("wisp-linux-x86_64/link", tarfile.SYMTYPE)):
            with self.subTest(name=name):
                with tarfile.open(archive, "w:gz") as tf:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = "/tmp/outside" if kind == tarfile.SYMTYPE else ""
                    tf.addfile(info, io.BytesIO(b""))
                result = self.verify(archive)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "unsafe|non-regular")

    def test_aarch64_payload_is_validated_without_executing_the_binary(self):
        data = bytearray(self.binary.read_bytes())
        struct.pack_into("<H", data, 18, 183)
        self.binary.write_bytes(data)
        result, archive = self.bundle(target="linux-aarch64")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            [sys.executable, str(VERIFY), "--archive", str(archive),
             "--sha256", hashlib.sha256(archive.read_bytes()).hexdigest(),
             "--version", VERSION, "--commit", COMMIT,
             "--target", "linux-aarch64"],
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["rust_binary_executed"])


if __name__ == "__main__":
    unittest.main()
