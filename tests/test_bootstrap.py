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
    VERIFY_FLAGS = ("--bundle --repo --cert-identity --cert-oidc-issuer "
                    "--source-ref --source-digest --signer-digest "
                    "--deny-self-hosted-runners --digest-alg --custom-trusted-root")
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

    def test_unsafe_home_is_refused_before_network(self):
        bootstrap = self.load()
        for home in ("", "relative-home", "/"):
            with self.subTest(home=home), \
                    mock.patch.dict(os.environ, {"HOME": home, "SUDO_USER": ""}), \
                    mock.patch("os.geteuid", return_value=1000), \
                    mock.patch("platform.system", return_value="Linux"), \
                    mock.patch("platform.machine", return_value="aarch64"), \
                    mock.patch("urllib.request.urlopen") as network, \
                    mock.patch("subprocess.run", side_effect=AssertionError("no process")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(bootstrap.main(["--yes"]), 4)
                network.assert_not_called()
                self.assertIn("HOME", output.getvalue())
                self.assertIn("desktop terminal", output.getvalue())

    def test_filesystem_root_aliases_are_refused_before_network(self):
        bootstrap = self.load()
        with tempfile.TemporaryDirectory() as td:
            directory = pathlib.Path(td)
            root = pathlib.Path(directory.anchor)
            link = directory / "root-link"
            link.symlink_to(root, target_is_directory=True)
            dotdot = root / directory.parts[1] / ".."
            for home in (dotdot, link):
                with self.subTest(home=home), \
                        mock.patch.dict(os.environ, {"HOME": str(home), "SUDO_USER": ""}), \
                        mock.patch("os.geteuid", return_value=1000), \
                        mock.patch("platform.system", return_value="Linux"), \
                        mock.patch("platform.machine", return_value="aarch64"), \
                        mock.patch("shutil.which", return_value="/independent/gh"), \
                        mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"{}")) as network, \
                        mock.patch("subprocess.run", side_effect=AssertionError("no process")), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(bootstrap.main(["--yes"]), 4)
                    network.assert_not_called()
                    self.assertIn("HOME", output.getvalue())

    def test_home_metadata_errors_are_controlled_refusals(self):
        bootstrap = self.load()
        with tempfile.TemporaryDirectory() as td:
            loop = pathlib.Path(td) / "loop"
            loop.symlink_to("loop", target_is_directory=True)
            cases = ((td, PermissionError(13, "denied")),
                     (td, OSError(5, "I/O error")), (str(loop), None))
            for home, error in cases:
                stat = (mock.patch("os.stat", side_effect=error)
                        if error else contextlib.nullcontext())
                with self.subTest(home=home, error=error), stat, \
                        mock.patch.dict(os.environ, {"HOME": home, "SUDO_USER": ""}), \
                        mock.patch("os.geteuid", return_value=1000), \
                        mock.patch("platform.system", return_value="Linux"), \
                        mock.patch("platform.machine", return_value="aarch64"), \
                        mock.patch("urllib.request.urlopen") as network, \
                        mock.patch("subprocess.run", side_effect=AssertionError("no process")), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    try:
                        code = bootstrap.main(["--yes"])
                    except (OSError, RuntimeError) as exc:
                        self.fail(f"HOME failure escaped: {type(exc).__name__}")
                    self.assertEqual(code, 4)
                    network.assert_not_called()
                    self.assertIn("HOME", output.getvalue())

    def test_credential_arguments_are_rejected_without_echoing_values(self):
        bootstrap = self.load()
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as stopped:
            bootstrap.main(["--token", "private-test-value"])
        self.assertEqual(stopped.exception.code, 2)
        self.assertNotIn("private-test-value", err.getvalue())

    def test_missing_independent_verifier_refuses_before_network(self):
        bootstrap = self.load()
        output = io.StringIO()
        with mock.patch("os.geteuid", return_value=1000), \
                mock.patch.dict(os.environ, {"SUDO_USER": ""}), \
                mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="x86_64"), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"{}")) as network, \
                mock.patch("subprocess.run", side_effect=AssertionError("no payload")), \
                contextlib.redirect_stdout(output):
            code = bootstrap.main(["--version", "v1.0.0-rc.1", "--yes"])
        self.assertEqual(code, 4)
        network.assert_not_called()
        self.assertIn("independently", output.getvalue())
        self.assertIn("source", output.getvalue())

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

    def attestation_refusal(self, *, bundle=True, help_flags=None,
                            commit="a" * 40, extra=()):
        """Offline boundary fixture: verifier must refuse, payload forbidden."""
        bootstrap = self.load()
        tag, name, blob = "v1.0.0-rc.1", "wisp-linux-x86_64.tar.gz", b"not an executable archive"
        base = bootstrap.DOWNLOAD + tag + "/"
        assets = [{"name": name, "browser_download_url": base + name,
                   "digest": "sha256:" + hashlib.sha256(blob).hexdigest()}]
        if bundle:
            assets.append({"name": name + ".sigstore.json",
                           "browser_download_url": base + name + ".sigstore.json"})
        requests, calls = [], []

        def response(request, **kw):
            url = request.full_url
            requests.append(url)
            if url.endswith("/tags/" + tag):
                data = json.dumps({"tag_name": tag, "assets": assets}).encode()
            elif url.endswith("/commits/" + tag):
                data = json.dumps({"sha": commit}).encode()
            elif url.endswith(".sigstore.json"):
                data = b'{"untrusted":"fixture"}'
            elif url.endswith(".tar.gz"):
                data = blob
            else:
                raise AssertionError(url)
            return io.BytesIO(data)

        def runner(argv, **kw):
            calls.append((argv, kw))
            self.assertEqual(argv[0], "/independently-installed/gh")
            if argv[-1] == "--help":
                return subprocess.CompletedProcess(
                    argv, 0, self.VERIFY_FLAGS if help_flags is None else help_flags, "")
            return subprocess.CompletedProcess(argv, 1, "", "untrusted signature")

        output = io.StringIO()
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.dict(os.environ, {"HOME": td, "SUDO_USER": "",
                                             "GH_TOKEN": "private-sentinel"}), \
                mock.patch("os.geteuid", return_value=1000), \
                mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="x86_64"), \
                mock.patch("shutil.which", return_value="/independently-installed/gh"), \
                mock.patch("urllib.request.urlopen", side_effect=response), \
                mock.patch("subprocess.run", side_effect=runner), \
                mock.patch.object(bootstrap, "extract", side_effect=AssertionError("payload forbidden")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = bootstrap.main(["--version", tag, "--yes", *extra])
            except SystemExit as exc:
                code = exc.code
        return code, output.getvalue(), calls, requests

    def test_independent_offline_trusted_root_is_forwarded_not_downloaded(self):
        with tempfile.TemporaryDirectory() as td:
            trusted = pathlib.Path(td) / "independent-root.json"
            trusted.write_text('{"fixture":"independently supplied"}')
            code, output, calls, requests = self.attestation_refusal(
                extra=["--trusted-root", str(trusted)])
        self.assertEqual(code, 1)
        command = calls[-1][0]
        self.assertEqual(command[command.index("--custom-trusted-root") + 1], str(trusted))
        self.assertFalse(any("trusted" in url or "root.json" in url for url in requests))
        self.assertIn("No checksum-only downgrade", output)

    def test_missing_bundle_refuses_even_with_publisher_digest(self):
        code, output, calls, _ = self.attestation_refusal(bundle=False)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("attestation bundle is missing", output)

    def test_verification_failure_cannot_be_bypassed_with_sha256(self):
        checksum = hashlib.sha256(b"not an executable archive").hexdigest()
        code, output, calls, _ = self.attestation_refusal(extra=["--sha256", checksum])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertNotIn("GH_TOKEN", calls[-1][1]["env"])
        self.assertIn("Keyless attestation verification failed", output)
        self.assertIn("No checksum-only downgrade", output)

    def test_unsupported_verifier_fails_before_any_verify_or_extract(self):
        code, output, calls, _ = self.attestation_refusal(help_flags="--bundle --repo")
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("lacks required", output)

    def test_invalid_tag_commit_stops_before_verifier_or_extraction(self):
        code, output, calls, _ = self.attestation_refusal(commit="master")
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])
        self.assertIn("exact release-tag source digest", output)

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
            {"name": "wisp-linux-x86_64.tar.gz.sigstore.json", "browser_download_url": base + "wisp-linux-x86_64.tar.gz.sigstore.json"},
            {"name": "SHA256SUMS", "browser_download_url": base + "SHA256SUMS"}]}

        def response(request, **kw):
            url = request.full_url if hasattr(request, "full_url") else request
            if url.endswith(("/tags/v1.0.0-rc.1", "/latest")):
                return io.BytesIO(json.dumps(release).encode())
            if url.endswith("/commits/v1.0.0-rc.1"):
                return io.BytesIO(json.dumps({"sha": "a" * 40}).encode())
            if url.endswith("/SHA256SUMS"):
                return io.BytesIO(f"{sha}  wisp-linux-x86_64.tar.gz\n".encode())
            if url.endswith(".sigstore.json"):
                return io.BytesIO(b'{"fixture":"offline fake, not a real signature"}')
            if url.endswith("/wisp-linux-x86_64.tar.gz"):
                return io.BytesIO(blob)
            raise AssertionError(url)

        with cli_env.CliEnv() as e:
            for name in ("systemctl", "hyprctl"):
                e.shim(name)
            e.shim("gh")
            verifier = str(e.home / "bin/gh")
            verified = []
            real_runner = subprocess.run

            def runner(argv, **kw):
                if argv[0] == verifier:
                    if argv[-1] == "--help":
                        return subprocess.CompletedProcess(argv, 0, self.VERIFY_FLAGS, "")
                    self.assertEqual(argv[1:3], ["attestation", "verify"])
                    self.assertEqual(hashlib.sha256(pathlib.Path(argv[3]).read_bytes()).hexdigest(), sha)
                    self.assertEqual(argv[argv.index("--repo") + 1], "duketopceo/wisp")
                    self.assertEqual(argv[argv.index("--source-ref") + 1], "refs/tags/v1.0.0-rc.1")
                    self.assertEqual(argv[argv.index("--source-digest") + 1], "a" * 40)
                    self.assertEqual(argv[argv.index("--signer-digest") + 1], "a" * 40)
                    self.assertEqual(argv[argv.index("--cert-identity") + 1],
                                     "https://github.com/duketopceo/wisp/.github/workflows/release.yml@refs/tags/v1.0.0-rc.1")
                    self.assertIn("--deny-self-hosted-runners", argv)
                    self.assertEqual(kw["env"]["GH_HOST"], "github.com")
                    self.assertNotIn("GH_TOKEN", kw["env"])
                    self.assertTrue(pathlib.Path(argv[argv.index("--bundle") + 1]).is_file())
                    verified.append(argv)
                    return subprocess.CompletedProcess(argv, 0, "", "")
                self.assertTrue(verified, "payload must never execute before trusted attestation verification")
                return real_runner(argv, **kw)

            with mock.patch.dict(os.environ, e.env, clear=True), \
                    mock.patch("platform.system", return_value="Linux"), \
                    mock.patch("platform.machine", return_value="x86_64"), \
                    mock.patch("os.geteuid", return_value=1000), \
                    mock.patch("urllib.request.urlopen", side_effect=response), \
                    mock.patch("subprocess.run", side_effect=runner), \
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
                    mock.patch("subprocess.run", side_effect=runner), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = update.run_update(
                    dry_run=False, confirm=lambda _: True,
                    service_active=lambda: False,
                    preflight_fn=lambda: [],
                    emit_text=lambda _: None)
                self.assertTrue(result["applied"])
                self.assertTrue(result["verified"])
                self.assertTrue(result["authenticated"])
                self.assertEqual(len(verified), 2)  # bootstrap and update, not rollback
                self.assertEqual(deploy.read()["commit"], "a" * 40)
                restored = update.rollback(confirm=lambda _: True, emit_text=lambda _: None)
                self.assertTrue(restored["rolled_back"], restored)
                self.assertEqual(deploy.read()["ref"], "v0.9.0")
