"""Offline bootstrap contract; all installs use isolated HOME and fake tools."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap/install.py"


class BootstrapTests(unittest.TestCase):
    def load(self):
        self.assertTrue(SCRIPT.is_file(), "bootstrap is missing")
        spec = importlib.util.spec_from_file_location("wisp_bootstrap", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_version_pinned_preview_has_no_network_or_writes(self):
        bootstrap = self.load()
        with tempfile.TemporaryDirectory() as td:
            home = pathlib.Path(td) / "home"
            home.mkdir()
            output = io.StringIO()
            with mock.patch.dict(os.environ, {"HOME": str(home)}), \
                    mock.patch("platform.system", return_value="Linux"), \
                    mock.patch("platform.machine", return_value="aarch64"), \
                    mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                    mock.patch("subprocess.run", side_effect=AssertionError("service")), \
                    contextlib.redirect_stdout(output):
                rc = bootstrap.main(["--version", "v1.0.0-rc.1", "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertIn("v1.0.0-rc.1", output.getvalue())
            self.assertIn("wisp-linux-aarch64.tar.gz", output.getvalue())
            self.assertEqual(list(home.iterdir()), [])

    def test_bootstrap_refuses_unsafe_archives_before_extraction(self):
        bootstrap = self.load()
        for name, kind, link in (
                ("../escape", tarfile.REGTYPE, ""),
                ("/absolute", tarfile.REGTYPE, ""),
                ("wisp/link", tarfile.SYMTYPE, "wispd"),
                ("wisp/hard", tarfile.LNKTYPE, "wisp/wispd"),
                ("wisp/device", tarfile.CHRTYPE, ""),
                ("wisp/.env", tarfile.REGTYPE, "")):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                work = pathlib.Path(td)
                archive = work / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as tf:
                    member = tarfile.TarInfo(name)
                    member.type, member.linkname = kind, link
                    tf.addfile(member, io.BytesIO(b""))
                with self.assertRaises(ValueError):
                    bootstrap.extract(archive, work / "tree")
                self.assertFalse((work / "tree").exists())

    def test_root_install_is_refused_before_network(self):
        bootstrap = self.load()
        with mock.patch("os.geteuid", return_value=0), \
                mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="x86_64"), \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("network")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bootstrap.main(["--yes"]), 4)

    def test_credential_arguments_are_rejected_without_echoing_values(self):
        bootstrap = self.load()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stopped:
            bootstrap.main(["--token", "private-test-value"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("private-test-value", err.getvalue())

    def test_missing_digest_stops_before_archive_download(self):
        bootstrap = self.load()
        tag = "v1.0.0-rc.1"
        release = {"tag_name": tag, "assets": [{
            "name": "wisp-linux-x86_64.tar.gz",
            "browser_download_url": bootstrap.DOWNLOAD + tag + "/wisp-linux-x86_64.tar.gz"}]}
        output = io.StringIO()
        with mock.patch("os.geteuid", return_value=1000), \
                mock.patch.dict(os.environ, {"SUDO_USER": ""}), \
                mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="x86_64"), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(release).encode())) as fetch, \
                mock.patch("subprocess.run", side_effect=AssertionError("install")), \
                contextlib.redirect_stdout(output):
            self.assertEqual(bootstrap.main(["--version", tag, "--yes"]), 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("No valid release SHA-256", output.getvalue())

    def test_verified_staged_archive_runs_real_installer_in_isolated_home(self):
        bootstrap = self.load()
        import cli_env
        spec = importlib.util.spec_from_file_location("release_build", ROOT / "scripts/release/build.py")
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        files = builder.collect(ROOT)
        files["release.json"] = (json.dumps({"version": "v1.0.0-rc.1",
                                             "commit": "a" * 40}).encode(), 0o644)
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as tf:
            for name, (data, mode) in files.items():
                info = tarfile.TarInfo("wisp-linux-x86_64/" + name)
                info.size, info.mode = len(data), mode
                tf.addfile(info, io.BytesIO(data))
        blob = payload.getvalue()
        sha = hashlib.sha256(blob).hexdigest()
        base = "https://github.com/duketopceo/wisp/releases/download/v1.0.0-rc.1/"
        release = {"tag_name": "v1.0.0-rc.1", "assets": [
            {"name": "wisp-linux-x86_64.tar.gz", "browser_download_url": base + "wisp-linux-x86_64.tar.gz"},
            {"name": "SHA256SUMS", "browser_download_url": base + "SHA256SUMS"}]}

        def response(request, **kw):
            url = request.full_url if hasattr(request, "full_url") else request
            if url.endswith(("/tags/v1.0.0-rc.1", "/latest")):
                return io.BytesIO(json.dumps(release).encode())
            if url.endswith("/SHA256SUMS"):
                return io.BytesIO(f"{sha}  wisp-linux-x86_64.tar.gz\n".encode())
            if url.endswith("/wisp-linux-x86_64.tar.gz"):
                return io.BytesIO(blob)
            raise AssertionError(url)

        with cli_env.CliEnv() as e:
            for name in ("systemctl", "hyprctl"):
                e.shim(name)
            with mock.patch.dict(os.environ, e.env, clear=True), \
                    mock.patch("platform.system", return_value="Linux"), \
                    mock.patch("platform.machine", return_value="x86_64"), \
                    mock.patch("os.geteuid", return_value=1000), \
                    mock.patch("urllib.request.urlopen", side_effect=response), \
                    mock.patch("sys.stdin.isatty", return_value=True), \
                    mock.patch("builtins.input", return_value="yes"), \
                    contextlib.redirect_stdout(io.StringIO()):
                rc = bootstrap.main(["--version", "v1.0.0-rc.1"])
            self.assertEqual(rc, 0)
            opt = e.home / ".local/opt/wisp"
            self.assertTrue((opt / "wispd").is_file())
            self.assertTrue((opt / "docs/dev-tasks/starter.txt").is_file())
            self.assertTrue((opt / "docs/INSTALL.md").is_file())
            self.assertTrue((e.home / ".local/bin/wispd").is_file())
            self.assertTrue((e.home / ".config/systemd/user/wispd.service").is_file())
            self.assertTrue((e.home / ".config/omarchy/plugins/io.github.duketopceo.wisp/manifest.json").is_file())
            self.assertEqual(json.loads((opt / "deploy.json").read_text())["ref"],
                             "v1.0.0-rc.1")
            # Exercise updater with the real staged installer, not mirror().
            from wisp import config, deploy, update
            rec = json.loads((opt / "deploy.json").read_text())
            rec["ref"] = "v0.9.0"
            (opt / "deploy.json").write_text(json.dumps(rec))
            with mock.patch.dict(os.environ, e.env, clear=True), \
                    mock.patch.object(config, "HOME", e.home), \
                    mock.patch.object(update, "asset_name", return_value="wisp-linux-x86_64.tar.gz"), \
                    mock.patch("urllib.request.urlopen", side_effect=response), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = update.run_update(
                    dry_run=False, confirm=lambda _: True,
                    service_active=lambda: False,
                    preflight_fn=lambda: [],
                    emit_text=lambda _: None)
                self.assertTrue(result["applied"])
                self.assertTrue(result["verified"])
                self.assertEqual(deploy.read()["commit"], "a" * 40)
                restored = update.rollback(confirm=lambda _: True, emit_text=lambda _: None)
                self.assertTrue(restored["rolled_back"], restored)
                self.assertEqual(deploy.read()["ref"], "v0.9.0")
