"""B9: `wispd update` verifies, previews, and never installs unasked."""
import hashlib
import io
import json
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import config, deploy, preflight, update  # noqa: E402

ORIG_INSTALLED_VERSION = update.installed_version
NAME = "wisp-linux-x86_64.tar.gz"
URL = update.DOWNLOAD_PREFIX + "v2.0.0/" + NAME


def make_tar(files: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, data in files.items():
            ti = tarfile.TarInfo(f"wisp-linux-x86_64/{rel}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


NEW = {"wispd": b"new launcher", "wisp/a.py": b"A2", "wisp/b.py": b"B",
       "shells/x.qml": b"Q"}


class Fixture(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.tmp = pathlib.Path(td.name)
        self.opt = self.tmp / "opt"
        (self.opt / "wisp").mkdir(parents=True)
        (self.opt / "shells").mkdir()
        (self.opt / "wispd").write_bytes(b"old launcher")
        (self.opt / "wisp" / "a.py").write_bytes(b"A1")
        (self.opt / "wisp" / "gone.py").write_bytes(b"G")
        (self.opt / "shells" / "x.qml").write_bytes(b"Q")
        self.blob = make_tar(NEW)
        self.sha = hashlib.sha256(self.blob).hexdigest()
        self.downloads = 0
        self.source_commit = "b" * 40
        self.bundle = json.dumps({"fixture": "fake public bundle",
                                  "source_commit": self.source_commit}).encode()
        self.verifier_calls = []
        self.verifier_status = 0
        self.verifier_flags = ("--bundle --repo --cert-identity --cert-oidc-issuer "
                               "--source-ref --source-digest --signer-digest "
                               "--deny-self-hosted-runners --digest-alg")
        self.state = self.tmp / "state"
        for p in (mock.patch.object(config, "HOME", self.tmp),
                  mock.patch.object(update, "opt_dir", lambda: self.opt),
                  mock.patch.object(update, "state_dir",
                                    lambda: self.state),
                  mock.patch.object(deploy, "record_path",
                                    lambda: self.opt / "deploy.json"),
                  mock.patch.object(update, "outside_changes",
                                    lambda root, home=None: []),
                  mock.patch.object(update, "asset_name", lambda: NAME),
                  mock.patch.object(update, "installed_version",
                                    lambda: "v1.0.0"),
                  mock.patch.object(update, "installed_record",
                                    lambda: {"ref": "v1.0.0",
                                             "commit": "a" * 40}),
                  mock.patch("shutil.which", return_value="/independent/gh"),
                  mock.patch("subprocess.run", side_effect=self.verifier_runner)):
            p.start()
            self.addCleanup(p.stop)

    def verifier_runner(self, argv, **kw):
        self.assertEqual(argv[0], "/independent/gh", "host process forbidden")
        self.assertEqual(argv[1:3], ["attestation", "verify"])
        if argv[-1] == "--help":
            return SimpleNamespace(returncode=0, stdout=self.verifier_flags)
        self.assertEqual(argv[argv.index("--source-ref") + 1], "refs/tags/v2.0.0")
        self.assertEqual(argv[argv.index("--source-digest") + 1], self.source_commit)
        self.assertEqual(argv[argv.index("--signer-digest") + 1], self.source_commit)
        self.assertEqual(argv[argv.index("--cert-identity") + 1],
                         "https://github.com/duketopceo/wisp/.github/workflows/release.yml@refs/tags/v2.0.0")
        self.assertEqual(argv[argv.index("--repo") + 1], "duketopceo/wisp")
        self.assertIn("--deny-self-hosted-runners", argv)
        self.assertEqual(pathlib.Path(argv[argv.index("--bundle") + 1]).read_bytes(),
                         self.bundle)
        self.assertTrue(pathlib.Path(argv[3]).is_file())
        self.assertEqual(kw["env"]["GH_HOST"], "github.com")
        self.assertNotIn("GH_TOKEN", kw["env"])
        self.verifier_calls.append(argv)
        return SimpleNamespace(returncode=self.verifier_status, stdout="")

    def release(self, digest=True, sums=None, bundle=True):
        a = {"name": NAME, "browser_download_url": URL}
        if digest:
            a["digest"] = "sha256:" + self.sha
        assets = [a]
        if bundle:
            assets.append({"name": NAME + ".sigstore.json",
                           "browser_download_url": URL + ".sigstore.json"})
        if sums:
            assets.append({"name": "SHA256SUMS",
                           "browser_download_url": update.DOWNLOAD_PREFIX
                           + "v2.0.0/SHA256SUMS"})
        return {"tag_name": "v2.0.0", "assets": assets}

    def seams(self, rel, blob=None, sums=""):
        blob = self.blob if blob is None else blob

        def fetch_file(url, dest):
            self.downloads += 1
            data = self.bundle if url == URL + ".sigstore.json" else blob
            self.assertIn(url, (URL, URL + ".sigstore.json"))
            pathlib.Path(dest).write_bytes(data)
            return hashlib.sha256(data).hexdigest()

        def fetch_json(url):
            if url == update.API:
                return rel
            if url == update.API_LIST:
                return [rel]
            self.assertEqual(url, "https://api.github.com/repos/duketopceo/wisp/commits/v2.0.0")
            return {"sha": self.source_commit}

        return dict(fetch_json=fetch_json, fetch_file=fetch_file,
                    fetch_text=lambda u: sums,
                    preflight_fn=lambda: self.pf_rows,
                    service_active=lambda: False)
    pf_rows = [{"id": "os", "level": "ok", "detail": "Linux", "fix": ""}]

    def mirror(self, root):
        """What `wispd install` does to the opt dir, for a verified tree."""
        for rel in list(update._managed(self.opt)):
            if rel != "deploy.json":
                (self.opt / rel).unlink()
        for rel in update._managed(root, staged=True):
            src = root / ("scripts/build_harness.py"
                          if rel == "build_harness.py" else rel)
            (self.opt / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.opt / rel).write_bytes(src.read_bytes())
        return 0


class AuthenticatedUpdate(Fixture):
    def test_failed_attestation_refuses_before_extraction_or_managed_writes(self):
        self.verifier_status = 1
        before = {str(p): p.read_bytes() for p in self.opt.rglob("*") if p.is_file()}
        with mock.patch.object(update, "_extract",
                               side_effect=AssertionError("candidate extraction forbidden")):
            with self.assertRaisesRegex(update.UpdateError, "[Aa]ttestation"):
                update.run_update(dry_run=False, force=True, sha256=self.sha,
                                  confirm=lambda _: True, **self.seams(self.release()))
        self.assertEqual(len(self.verifier_calls), 1)
        self.assertFalse(self.state.exists())
        self.assertEqual(before, {str(p): p.read_bytes()
                                 for p in self.opt.rglob("*") if p.is_file()})

    def test_missing_bundle_cannot_be_bypassed_with_force_or_checksum(self):
        with self.assertRaisesRegex(update.UpdateError, "attestation bundle"):
            update.run_update(dry_run=False, force=True, sha256=self.sha,
                              confirm=lambda _: True,
                              **self.seams(self.release(bundle=False)))
        self.assertEqual(self.downloads, 0)
        self.assertFalse(self.state.exists())

    def test_missing_independent_verifier_is_truthful_in_dry_run(self):
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        with mock.patch("shutil.which", return_value=None):
            with self.assertRaisesRegex(update.UpdateError, "Authentication unavailable"):
                update.run_update(dry_run=True, **self.seams(self.release()))
        self.assertEqual(self.downloads, 0)
        self.assertEqual(before, sorted(str(p) for p in self.tmp.rglob("*")))

    def test_unsafe_local_helper_is_not_loaded_from_candidate(self):
        trusted = self.tmp / "trusted"
        (trusted / "scripts/bootstrap").mkdir(parents=True)
        (trusted / "wisp").mkdir()
        outside = self.tmp / "outside.py"
        outside.write_text("raise AssertionError('untrusted helper executed')")
        helper = trusted / "scripts/bootstrap/install.py"
        for symlink in (False, True):
            if symlink:
                helper.symlink_to(outside)
            with mock.patch.object(update, "__file__", str(trusted / "wisp/update.py")):
                with self.assertRaisesRegex(update.UpdateError, "trusted local bootstrap"):
                    update.run_update(dry_run=True, **self.seams(self.release()))
        self.assertEqual(self.downloads, 0)

    def test_invalid_source_digest_refuses_before_download(self):
        seams = self.seams(self.release())
        fetch = seams["fetch_json"]
        seams["fetch_json"] = lambda u: fetch(u) if u == update.API else {"sha": "short"}
        with self.assertRaisesRegex(update.UpdateError, "source commit digest"):
            update.run_update(dry_run=True, **seams)
        self.assertEqual(self.downloads, 0)

    def test_unsupported_verifier_refuses_before_extracting_candidate_helper(self):
        self.verifier_flags = "--bundle --repo"
        files = dict(NEW)
        files["scripts/bootstrap/install.py"] = b"raise AssertionError('candidate executed')"
        blob = make_tar(files)
        self.sha = hashlib.sha256(blob).hexdigest()
        with mock.patch.object(update, "_extract",
                               side_effect=AssertionError("candidate extraction forbidden")):
            with self.assertRaisesRegex(update.UpdateError, "lacks required"):
                update.run_update(dry_run=True, **self.seams(self.release(), blob=blob))
        self.assertEqual(self.verifier_calls, [])

    def test_verified_plan_identifies_authentication_separately_from_integrity(self):
        out = []
        result = update.run_update(dry_run=True, emit_text=out.append,
                                   **self.seams(self.release()))
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["source_commit"], self.source_commit)
        self.assertIn("authentication: GitHub/Sigstore", "\n".join(out))
        self.assertEqual(len(self.verifier_calls), 1)

    def test_apply_records_authenticated_source_commit_not_installer_claim(self):
        def installer(root):
            self.assertEqual(len(self.verifier_calls), 1)
            self.mirror(root)
            deploy.write(None, "v2.0.0", "c" * 40)
            return 0
        result = update.run_update(dry_run=False, install_fn=installer,
                                   confirm=lambda _: True, emit_text=lambda _: None,
                                   **self.seams(self.release()))
        self.assertTrue(result["applied"])
        self.assertEqual(deploy.read()["commit"], self.source_commit)


class DryRun(Fixture):
    def run_it(self, **kw):
        out = []
        seams = self.seams(kw.pop("rel", self.release()), **kw)
        res = update.run_update(dry_run=True, emit_text=out.append, **seams)
        return res, "\n".join(out)

    def test_prints_version_digest_and_files_and_writes_nothing(self):
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        res, text = self.run_it()
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob("*")), before)
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A1")
        self.assertIn("v2.0.0", text)
        self.assertIn(self.sha, text)
        self.assertIn("~ wisp/a.py", text)
        self.assertIn("+ wisp/b.py", text)
        self.assertIn("- wisp/gone.py", text)
        self.assertNotIn("shells/x.qml", text)        # unchanged
        self.assertEqual(res["changes"]["changed"], ["wisp/a.py", "wispd"])
        self.assertFalse(res["applied"])
        self.assertIn("nothing was written", text)

    def test_preview_reports_retained_runtime_resource_changes(self):
        (self.opt / "assets").mkdir()
        (self.opt / "assets/icon.svg").write_bytes(b"old")
        self.blob = make_tar({**NEW, "assets/icon.svg": b"new",
                              "docs/baselines/new.json": b"{}"})
        self.sha = hashlib.sha256(self.blob).hexdigest()
        res, _ = self.run_it()
        self.assertIn("assets/icon.svg", res["changes"]["changed"])
        self.assertIn("docs/baselines/new.json", res["changes"]["added"])

    def test_a_wrong_digest_aborts(self):
        rel = self.release()
        rel["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(update.UpdateError) as c:
            self.run_it(rel=rel)
        self.assertIn("mismatch", str(c.exception))

    def test_a_tampered_download_aborts(self):
        with self.assertRaises(update.UpdateError):
            self.run_it(blob=make_tar({**NEW, "wisp/a.py": b"EVIL"}))

    def test_a_release_with_no_digest_aborts(self):
        with self.assertRaises(update.UpdateError) as c:
            self.run_it(rel=self.release(digest=False))
        self.assertIn("no SHA-256", str(c.exception))
        self.assertEqual(self.downloads, 0)       # nothing fetched unverified

    def test_a_sha256sums_asset_is_used(self):
        res, _ = self.run_it(rel=self.release(digest=False, sums=True),
                             sums=f"{self.sha}  {NAME}\n")
        self.assertEqual(res["digest_source"], "SHA256SUMS")

    def test_an_explicit_sha256_flag(self):
        out = []
        res = update.run_update(
            dry_run=True, sha256=self.sha, emit_text=out.append,
            **self.seams(self.release(digest=False)))
        self.assertEqual(res["digest_source"], "--sha256")
        with self.assertRaises(update.UpdateError):
            update.run_update(dry_run=True, sha256="nothex",
                              emit_text=out.append,
                              **self.seams(self.release(digest=False)))

    def test_the_download_url_must_stay_in_the_repo(self):
        rel = self.release()
        rel["assets"][0]["browser_download_url"] = "https://evil.test/x.tgz"
        seams = self.seams(rel)
        seams["fetch_file"] = update.fetch_file       # the real guard
        with self.assertRaises(update.UpdateError):
            update.run_update(dry_run=True, emit_text=lambda t: None,
                              **seams)

    def test_missing_asset_for_this_machine(self):
        with self.assertRaises(update.UpdateError):
            self.run_it(rel={"tag_name": "v2", "assets": []})

    def test_a_non_wisp_archive_is_refused(self):
        blob = make_tar({"hello.txt": b"x"})
        rel = self.release()
        rel["assets"][0]["digest"] = "sha256:" + hashlib.sha256(
            blob).hexdigest()
        with self.assertRaises(update.UpdateError):
            self.run_it(rel=rel, blob=blob)

    def test_even_in_tree_archive_symlinks_are_refused(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            file = tarfile.TarInfo("wisp/wispd")
            file.size = 1
            tf.addfile(file, io.BytesIO(b"x"))
            link = tarfile.TarInfo("wisp/link")
            link.type, link.linkname = tarfile.SYMTYPE, "wispd"
            tf.addfile(link)
        blob = buf.getvalue()
        rel = self.release()
        rel["assets"][0]["digest"] = "sha256:" + hashlib.sha256(blob).hexdigest()
        with self.assertRaises(update.UpdateError):
            self.run_it(rel=rel, blob=blob)


class FirstInstall(Fixture):
    def test_with_nothing_installed_every_file_is_new(self):
        empty = self.tmp / "none"
        empty.mkdir()
        with mock.patch.object(update, "opt_dir", lambda: empty):
            res = update.run_update(dry_run=True, emit_text=lambda t: None,
                                    **self.seams(self.release()))
        self.assertEqual(sorted(res["changes"]["added"]), sorted(NEW))


class Install(Fixture):
    def go(self, answer, **kw):
        asked, ran = [], []
        res = update.run_update(
            dry_run=False, emit_text=lambda t: None,
            confirm=lambda q: asked.append(q) or answer,
            install_fn=lambda root: ran.append(root) or self.mirror(root),
            **self.seams(self.release()), **kw)
        return res, asked, ran

    def test_no_means_nothing_runs(self):
        res, asked, ran = self.go(False)
        self.assertEqual(len(asked), 1)
        self.assertEqual(ran, [])
        self.assertFalse(res["applied"])

    def test_yes_runs_the_installer_from_the_verified_tree(self):
        seen = []

        def install_fn(root):
            seen.append((root / "wispd").read_bytes())
            return self.mirror(root)
        res = update.run_update(
            dry_run=False, emit_text=lambda t: None, confirm=lambda q: True,
            install_fn=install_fn, **self.seams(self.release()))
        self.assertEqual(seen, [b"new launcher"])
        self.assertTrue(res["applied"])

    def test_no_confirm_callback_never_installs(self):
        ran = []
        res = update.run_update(
            dry_run=False, emit_text=lambda t: None, confirm=None,
            install_fn=lambda r: ran.append(r) or 0,
            **self.seams(self.release()))
        self.assertEqual(ran, [])
        self.assertFalse(res["applied"])

    def test_a_failing_installer_is_an_error(self):
        with self.assertRaises(update.UpdateError):
            update.run_update(
                dry_run=False, emit_text=lambda t: None,
                confirm=lambda q: True, install_fn=lambda r: 3,
                **self.seams(self.release()))

    def test_a_non_terminal_cannot_answer(self):
        with mock.patch.object(sys, "stdin", io.StringIO("y\n")):
            with self.assertRaises(update.UpdateError):
                update.tty_confirm("ok? ")

    def test_up_to_date_does_not_ask(self):
        for rel, data in NEW.items():
            p = self.opt / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (self.opt / "wisp" / "gone.py").unlink()
        with mock.patch.object(update, "installed_version",
                               lambda: "v2.0.0"), \
                mock.patch.object(update, "installed_record",
                                  lambda: {"ref": "v2.0.0"}):
            res, asked, ran = self.go(True, force=True)
        self.assertEqual((asked, ran), ([], []))


class NeverBackwards(Fixture):
    """A release that is not newer than the install is refused before the
    download, unless --force; a dry run still previews it with a warning."""

    COMMIT = "336976f" + "0" * 33

    def go(self, record, *, dry_run=False, force=False, compare=None,
           answer=True):
        asked, ran, urls = [], [], []
        seams = self.seams(self.release())
        base = seams["fetch_json"]

        def fetch_json(url):
            urls.append(url)
            if "/compare/" in url:
                if isinstance(compare, Exception):
                    raise compare
                return compare
            return base(url)
        seams["fetch_json"] = fetch_json
        with mock.patch.object(update, "installed_record", lambda: record):
            res = update.run_update(
                dry_run=dry_run, force=force, emit_text=lambda t: None,
                confirm=lambda q: asked.append(q) or answer,
                install_fn=lambda root: ran.append(root) or self.mirror(root), **seams)
        return res, asked, ran, urls

    def refused(self, record, **kw):
        with self.assertRaises(update.UpdateError) as c:
            self.go(record, **kw)
        self.assertEqual(self.downloads, 0)       # stopped before download
        self.assertIn("Nothing was installed", str(c.exception))
        self.assertIn("--force", str(c.exception))
        return str(c.exception)

    def test_an_older_release_than_the_installed_version_is_refused(self):
        msg = self.refused({"ref": "v3.1.0"})
        self.assertIn("downgrade", msg)

    def test_the_same_version_is_refused(self):
        self.assertIn("already what is installed",
                      self.refused({"ref": "v2.0.0"}))

    def test_a_newer_release_installs(self):
        res, asked, ran, _ = self.go({"ref": "v1.9.9"})
        self.assertTrue(res["applied"])
        self.assertEqual(res["ordering"], "newer")
        self.assertFalse(res["forced"])

    def test_versions_compare_numerically_and_prereleases_sort_below(self):
        self.refused({"ref": "v10.0.0"})
        res, *_ = self.go({"ref": "v2.0.0-rc1"})
        self.assertTrue(res["applied"])           # rc1 < 2.0.0
        self.assertLess(update.parse_version("v1.9.0"),
                        update.parse_version("v1.10.0"))
        self.assertIsNone(update.parse_version("master"))

    def test_prerelease_ids_order_per_semver(self):
        pv = update.parse_version
        self.assertLess(pv("v1.0.0-rc.2"), pv("v1.0.0-rc.3"))
        self.assertLess(pv("v1.0.0-rc.9"), pv("v1.0.0-rc.10"))
        self.assertLess(pv("v1.0.0-rc.10"), pv("v1.0.0"))
        self.assertLess(pv("v1.0.0-alpha"), pv("v1.0.0-beta"))
        self.assertLess(pv("v1.0.0-1"), pv("v1.0.0-rc"))
        self.assertEqual(pv("v1.0.0-rc.2"), pv("1.0.0-rc.2"))
        self.assertTrue(update.is_prerelease("v1.0.0-rc.2"))
        self.assertFalse(update.is_prerelease("v1.0.0"))

    def test_an_rc_install_looks_past_githubs_latest(self):
        # GitHub's "latest" never names a pre-release
        seen = []
        rels = [{"tag_name": "v1.0.0-rc.3"}, {"tag_name": "v0.9.0"},
                {"tag_name": "v1.0.0-rc.4", "draft": True},
                {"tag_name": "v1.0.0-rc.2"}]

        def fj(url):
            seen.append(url)
            return rels if url == update.API_LIST else {"tag_name": "v0.9.0"}

        got = update.latest_release(fj, {"ref": "v1.0.0-rc.2"})
        self.assertEqual(got["tag_name"], "v1.0.0-rc.3")
        self.assertEqual(seen, [update.API_LIST])
        got = update.latest_release(fj, {"ref": "v0.9.0"})
        self.assertEqual(got["tag_name"], "v0.9.0")
        self.assertEqual(seen[-1], update.API)

    def test_a_master_install_ahead_of_the_tag_is_refused(self):
        # the install is a commit on master, past v2.0.0: compare says ahead
        rec = {"ref": "master", "commit": self.COMMIT}
        self.refused(rec, compare={"status": "ahead"})

    def test_identical_to_the_tag_is_refused(self):
        self.refused({"ref": "master", "commit": self.COMMIT},
                     compare={"status": "identical"})

    def test_diverged_is_refused_and_says_so(self):
        msg = self.refused({"ref": "master", "commit": self.COMMIT},
                           compare={"status": "diverged"})
        self.assertIn("diverged", msg)

    def test_a_commit_behind_the_tag_installs(self):
        res, _, ran, urls = self.go({"ref": "master", "commit": self.COMMIT},
                                    compare={"status": "behind"})
        self.assertTrue(res["applied"])
        self.assertEqual(len(ran), 1)
        self.assertTrue(any(f"/compare/v2.0.0...{self.COMMIT}" in u
                            for u in urls))

    def test_when_the_comparison_fails_it_fails_closed(self):
        rec = {"ref": "master", "commit": self.COMMIT}
        self.refused(rec, compare=OSError("offline"))
        self.refused(rec, compare={"message": "Not Found"})
        self.refused({"ref": "master", "commit": "unknown"})
        self.refused({})

    def test_force_installs_an_older_release_and_says_it_was_forced(self):
        res, asked, ran, _ = self.go({"ref": "v3.1.0"}, force=True)
        self.assertTrue(res["applied"])
        self.assertTrue(res["forced"])
        self.assertEqual(res["ordering"], "older")
        self.assertEqual(len(asked), 1)           # still asks for the yes

    def test_force_without_a_yes_still_installs_nothing(self):
        res, _, ran, _ = self.go({"ref": "v3.1.0"}, force=True, answer=False)
        self.assertEqual(ran, [])
        self.assertFalse(res["applied"])

    def test_a_dry_run_previews_an_older_release_with_a_warning(self):
        out = []
        seams = self.seams(self.release())
        with mock.patch.object(update, "installed_record",
                               lambda: {"ref": "v3.1.0"}):
            res = update.run_update(dry_run=True, emit_text=out.append,
                                    **seams)
        text = "\n".join(out)
        self.assertEqual(res["ordering"], "older")
        self.assertIn("refuses it without --force", text)
        self.assertFalse(res["applied"])

    def test_the_cli_exposes_force(self):
        from wisp.cli import registry
        cmd = registry.commands()["daemon update"]
        import argparse
        p = argparse.ArgumentParser()
        cmd.args(p)
        self.assertTrue(p.parse_args(["--force"]).force)
        self.assertFalse(p.parse_args([]).force)



class Transaction(Fixture):
    """U2: backup, verified apply, rollback. Everything in a temp tree."""

    def apply(self, install_fn=None, **kw):
        out = []
        res = update.run_update(
            dry_run=False, emit_text=out.append, confirm=lambda q: True,
            install_fn=install_fn or self.mirror,
            **self.seams(self.release()), **kw)
        self.out = "\n".join(out)
        return res

    def manifest(self):
        import json
        d = sorted(self.state.iterdir())[-1]
        return json.loads((d / "manifest.json").read_text())

    def rollback(self, answer=True, **kw):
        out = []
        res = update.rollback(confirm=lambda q: answer, emit_text=out.append,
                              state=self.state, **kw)
        self.out = "\n".join(out)
        return res

    def test_a_digest_mismatch_writes_nothing_anywhere(self):
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        rel = self.release()
        rel["assets"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaises(update.UpdateError):
            update.run_update(dry_run=False, emit_text=lambda t: None,
                              confirm=lambda q: True, install_fn=self.mirror,
                              **self.seams(rel))
        self.assertEqual(sorted(str(p) for p in self.tmp.rglob("*")), before)
        self.assertFalse(self.state.exists())

    def test_no_consent_writes_no_backup(self):
        update.run_update(dry_run=False, emit_text=lambda t: None,
                          confirm=lambda q: False, install_fn=self.mirror,
                          **self.seams(self.release()))
        self.assertFalse(self.state.exists())

    def test_a_verified_update_saves_a_private_backup_and_the_version(self):
        res = self.apply()
        self.assertTrue(res["applied"] and res["verified"])
        self.assertEqual(self.manifest()["phase"], "verified")
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A2")
        d = pathlib.Path(res["backup"])
        self.assertEqual((d / "files" / "wisp" / "a.py").read_bytes(), b"A1")
        self.assertEqual(oct(d.stat().st_mode & 0o777), "0o700")
        self.assertEqual(oct((d / "manifest.json").stat().st_mode & 0o777),
                         "0o600")
        self.assertEqual(oct((d / "files" / "wispd").stat().st_mode & 0o777),
                         "0o600")
        self.assertEqual((deploy.read() or {}).get("ref"), "v2.0.0")
        with mock.patch.object(deploy, "read", lambda: deploy_rec(self)):
            self.assertEqual(ORIG_INSTALLED_VERSION(), "v2.0.0")
        self.assertIn("not restarted", self.out)

    def test_the_backup_holds_only_managed_files(self):
        (self.opt / "notes.txt").write_text("mine")
        (self.tmp / "config.toml").write_text("keep")
        res = self.apply()
        names = sorted(str(p.relative_to(pathlib.Path(res["backup"])
                                         / "files"))
                       for p in (pathlib.Path(res["backup"]) / "files")
                       .rglob("*") if p.is_file())
        self.assertNotIn("notes.txt", names)
        self.assertIn("wisp/gone.py", names)

    def test_an_installer_failure_leaves_an_unfinished_update_to_roll_back(
            self):
        def half(root):
            (self.opt / "wisp" / "a.py").write_bytes(b"A2")
            (self.opt / "wisp" / "gone.py").unlink()
            (self.opt / "wisp" / "b.py").write_bytes(b"par")   # half-written
            return 3
        with self.assertRaises(update.UpdateError) as c:
            self.apply(half)
        self.assertIn("--rollback", str(c.exception))
        self.assertEqual(self.manifest()["phase"], "applying")
        res = self.rollback()
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A1")
        self.assertEqual((self.opt / "wisp" / "gone.py").read_bytes(), b"G")
        self.assertTrue(res["rolled_back"])
        self.assertEqual(self.manifest()["phase"], "restored")

    def test_a_pending_update_blocks_the_next_one(self):
        with self.assertRaises(update.UpdateError):
            self.apply(lambda root: 1)
        self.downloads = 0
        with self.assertRaises(update.UpdateError) as c:
            self.apply()
        self.assertIn("did not finish", str(c.exception))
        self.assertEqual(self.downloads, 0)

    def test_a_mismatch_after_install_is_not_reported_as_success(self):
        def bad(root):
            self.mirror(root)
            (self.opt / "wisp" / "a.py").write_bytes(b"torn")
            return 0
        with self.assertRaises(update.UpdateError) as c:
            self.apply(bad)
        self.assertIn("not verified", str(c.exception))
        self.assertIn("wisp/a.py", str(c.exception))
        self.assertEqual(self.manifest()["phase"], "verify-failed")

    def test_rollback_restores_and_is_idempotent(self):
        self.apply()
        res = self.rollback()
        self.assertTrue(res["rolled_back"])
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A1")
        self.assertEqual((self.opt / "wisp" / "gone.py").read_bytes(), b"G")
        self.assertFalse((self.opt / "wisp" / "b.py").exists())
        again = self.rollback()
        self.assertFalse(again["rolled_back"])
        self.assertIn("already", self.out)

    def test_rollback_declined_changes_nothing(self):
        self.apply()
        self.rollback(answer=False)
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A2")
        self.assertEqual(self.manifest()["phase"], "verified")

    def test_a_file_the_user_changed_since_the_update_is_kept(self):
        self.apply()
        (self.opt / "wisp" / "a.py").write_bytes(b"my edit")
        (self.opt / "wisp" / "b.py").write_bytes(b"my edit too")
        res = self.rollback()
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(),
                         b"my edit")
        self.assertEqual((self.opt / "wisp" / "b.py").read_bytes(),
                         b"my edit too")             # added by the update
        self.assertEqual((self.opt / "wisp" / "gone.py").read_bytes(), b"G")
        self.assertFalse(res["rolled_back"])
        self.assertIn("wisp/a.py", self.out)
        self.assertEqual(self.manifest()["phase"], "restored-partial")

    def test_a_second_rollback_never_overwrites_an_edit_the_first_kept(self):
        self.apply()
        (self.opt / "wisp" / "a.py").write_bytes(b"my edit")
        self.rollback()
        self.rollback()
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(),
                         b"my edit")
        self.assertIn("kept by an earlier rollback", self.out)

    def test_an_update_is_not_blocked_after_a_rollback_that_kept_edits(self):
        self.apply()
        (self.opt / "wisp" / "a.py").write_bytes(b"my edit")
        self.rollback()
        self.assertIsNone(update.unfinished(self.state))
        self.downloads = 0
        self.apply()
        self.assertEqual(self.downloads, 2)       # archive and public bundle

    def test_a_failed_verification_is_rolled_back_in_full(self):
        def bad(root):
            self.mirror(root)
            (self.opt / "wisp" / "a.py").write_bytes(b"torn")
            return 0
        with self.assertRaises(update.UpdateError):
            self.apply(bad)
        self.assertEqual(self.manifest()["phase"], "verify-failed")
        self.assertIsNotNone(update.unfinished(self.state))
        res = self.rollback()
        self.assertTrue(res["rolled_back"])
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A1")

    def test_a_failed_restore_stays_unsettled_and_never_touches_kept_files(
            self):
        self.apply()
        (self.opt / "wisp" / "b.py").write_bytes(b"my edit")   # kept
        def boom(src, dst, **kw):
            raise OSError("disk full")
        with mock.patch.object(update.shutil, "copyfileobj", boom):
            res = self.rollback()
        self.assertFalse(res["rolled_back"])
        self.assertEqual(self.manifest()["phase"], "restore-incomplete")
        self.assertEqual(list(self.opt.rglob(".*.tmp")), [])
        self.rollback()                         # retry now works
        self.assertEqual((self.opt / "wisp" / "a.py").read_bytes(), b"A1")
        self.assertEqual((self.opt / "wisp" / "b.py").read_bytes(),
                         b"my edit")

    def test_rollback_restores_the_original_file_modes(self):
        os.chmod(self.opt / "wispd", 0o755)
        os.chmod(self.opt / "wisp" / "a.py", 0o644)
        res = self.apply()
        self.assertEqual(oct((pathlib.Path(res["backup"]) / "files"
                              / "wispd").stat().st_mode & 0o777), "0o600")
        os.chmod(self.opt / "wispd", 0o600)      # whatever the update left
        self.rollback()
        self.assertEqual((self.opt / "wispd").stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.opt / "wisp" / "a.py").stat().st_mode & 0o777,
                         0o644)

    def test_unowned_and_runtime_files_are_never_touched(self):
        self.apply()
        (self.opt / "wisp" / "runtime.cache").write_text("x")
        (self.opt / "notes.txt").write_text("mine")
        (self.opt / "wisp" / "__pycache__").mkdir()
        (self.opt / "wisp" / "__pycache__" / "a.pyc").write_bytes(b"c")
        self.rollback()
        for rel in ("wisp/runtime.cache", "notes.txt",
                    "wisp/__pycache__/a.pyc"):
            self.assertTrue((self.opt / rel).exists(), rel)
        self.assertNotIn("runtime.cache", self.out)

    def test_a_symlinked_managed_path_is_never_followed(self):
        outside = self.tmp / "outside.txt"
        outside.write_text("secret-ish")
        os.symlink(outside, self.opt / "wisp" / "link.py")
        res = self.apply()
        files = pathlib.Path(res["backup"]) / "files" / "wisp"
        self.assertFalse((files / "link.py").exists())
        self.assertIsNone(update._safe(self.opt, "wisp/link.py"))
        self.assertEqual(outside.read_text(), "secret-ish")

    def test_a_tampered_manifest_path_is_skipped_and_listed(self):
        import json
        self.apply()
        man = self.manifest()
        man["before"]["../outside.txt"] = "0" * 64
        man["before"]["/etc/passwd"] = "0" * 64
        plan = update.plan_rollback(man, self.opt)
        keys = [k for k, _ in plan["keep"]]
        self.assertIn("../outside.txt", keys)
        self.assertIn("/etc/passwd", keys)
        self.assertNotIn("../outside.txt", plan["restore"])

    def test_the_daemon_is_not_restarted_without_the_flag(self):
        calls = []
        with mock.patch.object(update, "restart_service",
                               lambda run=None: calls.append(1) or True):
            self.apply()
        self.assertEqual(calls, [])

    def test_restart_with_a_yes_checks_the_daemon_answers(self):
        calls = []
        seams = self.seams(self.release())
        seams["service_active"] = lambda: True
        with mock.patch.object(update, "restart_service",
                               lambda run=None: calls.append(1) or True), \
                mock.patch.object(update, "ipc_ok", lambda o, r=None: True):
            res = update.run_update(dry_run=False, restart=True,
                                    emit_text=lambda t: None,
                                    confirm=lambda q: True,
                                    install_fn=self.mirror, **seams)
        self.assertEqual(calls, [1])
        self.assertTrue(res["ipc_ok"])

    def test_restart_declined_does_not_restart(self):
        calls = []
        seams = self.seams(self.release())
        seams["service_active"] = lambda: True
        answers = iter([True, False])
        with mock.patch.object(update, "restart_service",
                               lambda run=None: calls.append(1) or True):
            update.run_update(dry_run=False, restart=True,
                              emit_text=lambda t: None,
                              confirm=lambda q: next(answers),
                              install_fn=self.mirror, **seams)
        self.assertEqual(calls, [])

    def test_an_ipc_failure_after_restart_points_at_rollback(self):
        seams = self.seams(self.release())
        seams["service_active"] = lambda: True
        with mock.patch.object(update, "restart_service",
                               lambda run=None: True), \
                mock.patch.object(update, "ipc_ok", lambda o, r=None: False):
            with self.assertRaises(update.UpdateError) as c:
                update.run_update(dry_run=False, restart=True,
                                  emit_text=lambda t: None,
                                  confirm=lambda q: True,
                                  install_fn=self.mirror, **seams)
        self.assertIn("--rollback --restart", str(c.exception))

    def test_rollback_after_a_failed_restart_offers_one_and_verifies(self):
        seams = self.seams(self.release())
        seams["service_active"] = lambda: True
        update.run_update(dry_run=False, emit_text=lambda t: None,
                          confirm=lambda q: True, install_fn=self.mirror,
                          **seams)
        calls = []
        with mock.patch.object(update, "restart_service",
                               lambda run=None: calls.append(1) or True), \
                mock.patch.object(update, "ipc_ok", lambda o, r=None: True):
            res = self.rollback(restart=True)
        self.assertEqual(calls, [1])
        self.assertTrue(res["ipc_ok"])
        self.assertIn("answers", self.out)

    def test_rollback_without_an_update_says_so(self):
        with self.assertRaises(update.UpdateError):
            self.rollback()

    def test_the_scope_of_rollback_is_stated(self):
        self.apply()
        self.rollback()
        self.assertIn("not rolled back", self.out)
        self.assertIn("shell plugin", self.out)

    def test_changes_outside_the_opt_dir_are_called_out(self):
        with mock.patch.object(update, "outside_changes",
                               lambda root, home=None: ["shell plugin"]):
            self.apply()
        self.assertIn("also changed shell plugin", self.out)


def deploy_rec(t):
    import json
    return json.loads((t.opt / "deploy.json").read_text())


class PreflightGate(Fixture):
    def test_a_blocking_row_stops_before_any_download(self):
        self.pf_rows = [{"id": "disk space", "level": "block",
                         "detail": "1 MiB free", "fix": "Free space."}]
        with self.assertRaises(update.UpdateError) as c:
            update.run_update(dry_run=True, emit_text=lambda t: None,
                              **self.seams(self.release()))
        self.assertIn("nothing was written", str(c.exception))
        self.assertEqual(self.downloads, 0)

    def test_degraded_rows_are_shown_and_do_not_stop_a_dry_run(self):
        self.pf_rows = [{"id": "opencode", "level": "degraded",
                         "detail": "not found", "fix": ""}]
        out = []
        res = update.run_update(dry_run=True, emit_text=out.append,
                                **self.seams(self.release()))
        self.assertIn("opencode", "\n".join(out))
        self.assertFalse(res["applied"])


class ExternalRecovery(Fixture):
    def test_rollback_does_not_follow_preseeded_temporary_symlink(self):
        root = self.tmp / "release"
        root.mkdir()
        (root / "wispd").write_bytes(b"new launcher")
        man = update.protect(self.opt, root, "v1", "v2", False, state=self.state)
        (self.opt / "wispd").write_bytes(b"new launcher")
        update._save(man, "verified")
        victim = self.tmp / "user-data"
        victim.write_bytes(b"keep user data")
        collision = self.opt / f".wispd.{os.getpid()}.tmp"
        collision.symlink_to(victim)
        with mock.patch("subprocess.run", side_effect=AssertionError("offline rollback only")):
            result = update.rollback(confirm=lambda _: True, emit_text=lambda _: None,
                                     opt=self.opt, state=self.state)
        self.assertTrue(result["rolled_back"], result)
        self.assertEqual(victim.read_bytes(), b"keep user data")
        self.assertFalse((self.opt / "wispd").is_symlink())
        self.assertEqual((self.opt / "wispd").read_bytes(), b"old launcher")
        self.assertTrue(collision.is_symlink())

    def test_backups_have_unique_ids_even_with_the_same_clock_tick(self):
        root = self.tmp / "release"
        root.mkdir()
        with mock.patch.object(update.time, "strftime", return_value="same-tick"):
            first = update.protect(self.opt, root, "v1", "v2", False)
            second = update.protect(self.opt, root, "v2", "v3", False)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(update._manifests(self.state)), 2)

    def test_linked_backup_state_is_refused_before_writes(self):
        root = self.tmp / "release"
        root.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        self.state.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(update.UpdateError):
            update.protect(self.opt, root, "v1", "v2", False)
        self.assertEqual(list(outside.iterdir()), [])

    def test_interrupted_apply_keeps_external_user_edits_and_reports_partial(self):
        plug = self.tmp / ".config/omarchy/plugins/io.github.duketopceo.wisp"
        plug.mkdir(parents=True)
        (plug / "main.qml").write_bytes(b"old")
        root = self.tmp / "release"
        (root / "shell-plugin").mkdir(parents=True)
        (root / "shell-plugin/main.qml").write_bytes(b"new")
        man = update.protect(self.opt, root, "v1", "v2", False)
        update._save(man, "applying")
        (plug / "main.qml").write_bytes(b"user edit after failure")
        out = []
        res = update.rollback(confirm=lambda _: True, emit_text=out.append)
        self.assertFalse(res["rolled_back"])
        self.assertIn("@plugin/main.qml", res["kept"])
        self.assertEqual((plug / "main.qml").read_bytes(), b"user edit after failure")
        again = update.rollback(confirm=lambda _: True, emit_text=out.append)
        self.assertIn("@plugin/main.qml", again["kept"])
        self.assertTrue(any("incomplete" in s for s in out), out)

    def test_failed_apply_restores_attributable_plugin_and_unit_files(self):
        plugin = self.tmp / ".config/omarchy/plugins/io.github.duketopceo.wisp"
        unit = self.tmp / ".config/systemd/user/wispd.service"
        plugin.mkdir(parents=True)
        unit.parent.mkdir(parents=True)
        (plugin / "main.qml").write_bytes(b"old plugin")
        (plugin / "my-extra.qml").write_bytes(b"user addition")
        unit.write_bytes(b"old unit")
        unit.chmod(0o640)
        files = {**NEW, "shell-plugin/main.qml": b"new plugin",
                 "scripts/units/wispd.service": b"new unit"}
        self.blob = make_tar(files)
        self.sha = hashlib.sha256(self.blob).hexdigest()

        def fail(root):
            self.mirror(root)
            (plugin / "main.qml").write_bytes(b"new plugin")
            unit.write_bytes(b"new unit")
            return 9

        with self.assertRaises(update.UpdateError):
            update.run_update(dry_run=False, confirm=lambda _: True,
                              emit_text=lambda _: None, install_fn=fail,
                              **self.seams(self.release()))
        manifest = update._manifests(self.state)[-1]
        self.assertEqual(manifest.get("after_modes", {}).get("@units/wispd.service"), 0o640)
        result = update.rollback(confirm=lambda _: True, emit_text=lambda _: None)
        self.assertTrue(result["rolled_back"], result)
        self.assertEqual((plugin / "main.qml").read_bytes(), b"old plugin")
        self.assertEqual(unit.read_bytes(), b"old unit")
        self.assertEqual(unit.stat().st_mode & 0o777, 0o640)
        self.assertEqual((plugin / "my-extra.qml").read_bytes(), b"user addition")


class RollbackUnitReload(Fixture):
    def prepare_unit(self, *, added=False):
        unit = self.tmp / ".config/systemd/user/wispd.service"
        unit.parent.mkdir(parents=True)
        if not added:
            unit.write_bytes(b"old unit directives")
        root = self.tmp / "release-unit"
        (root / "scripts/units").mkdir(parents=True)
        (root / "scripts/units/wispd.service").write_bytes(b"new unit directives")
        man = update.protect(self.opt, root, "v1", "v2", True)
        unit.write_bytes(b"new unit directives")
        update._save(man, "verified")
        return unit

    def test_consented_restart_loads_restored_directives_before_starting(self):
        unit = self.prepare_unit()
        calls, loaded = [], [b"new unit directives"]

        def manager(argv, **kw):
            calls.append(argv)
            if argv == ["systemctl", "--user", "daemon-reload"]:
                loaded[0] = unit.read_bytes()
            elif argv == ["systemctl", "--user", "restart", "wispd"]:
                self.assertEqual(loaded[0], b"old unit directives")
            else:
                self.assertEqual(argv[-2:], ["status", "--quiet"])
            return SimpleNamespace(returncode=0)

        with mock.patch("subprocess.run", side_effect=AssertionError("host process forbidden")):
            result = update.rollback(confirm=lambda _: True, restart=True,
                                     run=manager, emit_text=lambda _: None)
        self.assertTrue(result["rolled_back"])
        self.assertTrue(result["ipc_ok"])
        self.assertEqual(calls[:2], [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "restart", "wispd"]])

    def test_reload_failure_preserves_disk_success_without_restart_or_probe(self):
        unit = self.prepare_unit()
        calls, output = [], []

        def manager(argv, **kw):
            calls.append(argv)
            return SimpleNamespace(returncode=1)

        with mock.patch("subprocess.run", side_effect=AssertionError("host process forbidden")):
            result = update.rollback(confirm=lambda _: True, restart=True,
                                     run=manager, emit_text=output.append)
        self.assertEqual(calls, [["systemctl", "--user", "daemon-reload"]])
        self.assertTrue(result["rolled_back"])
        self.assertIsNone(result["ipc_ok"])
        self.assertEqual(result.get("runtime_error"), "daemon-reload-failed")
        self.assertEqual(unit.read_bytes(), b"old unit directives")
        self.assertEqual(update._manifests(self.state)[-1]["phase"], "restored")
        self.assertIn("disk restore", "\n".join(output))
        self.assertIn("daemon-reload failed", "\n".join(output))

    def test_without_restart_flag_only_manual_reload_then_restart_is_advised(self):
        self.prepare_unit()
        output, prompts = [], []

        def consent(prompt):
            prompts.append(prompt)
            return True

        denied = mock.Mock(side_effect=AssertionError("no manager action consent"))
        with mock.patch("subprocess.run", denied):
            result = update.rollback(confirm=consent, restart=False,
                                     run=denied, emit_text=output.append)
        self.assertTrue(result["rolled_back"])
        self.assertEqual(len(prompts), 1)
        denied.assert_not_called()
        hint = "\n".join(output)
        self.assertIn("systemctl --user daemon-reload", hint)
        self.assertLess(hint.index("systemctl --user daemon-reload"),
                        hint.index("systemctl --user restart wispd"))

    def test_declining_runtime_consent_performs_no_manager_actions(self):
        self.prepare_unit()
        output, prompts = [], []

        def consent(prompt):
            prompts.append(prompt)
            return len(prompts) == 1

        denied = mock.Mock(side_effect=AssertionError("no manager action consent"))
        with mock.patch("subprocess.run", denied):
            result = update.rollback(confirm=consent, restart=True,
                                     run=denied, emit_text=output.append)
        self.assertTrue(result["rolled_back"])
        self.assertIsNone(result["ipc_ok"])
        self.assertEqual(len(prompts), 2)
        self.assertIn("unit definitions", prompts[1])
        self.assertIn("systemctl --user daemon-reload", "\n".join(output))
        denied.assert_not_called()

    def test_removed_update_added_unit_is_unloaded_before_restart(self):
        unit = self.prepare_unit(added=True)
        calls = []

        def manager(argv, **kw):
            calls.append(argv)
            self.assertFalse(unit.exists())
            return SimpleNamespace(returncode=0)

        with mock.patch("subprocess.run", side_effect=AssertionError("host process forbidden")):
            result = update.rollback(confirm=lambda _: True, restart=True,
                                     run=manager, emit_text=lambda _: None)
        self.assertEqual(result["removed"], ["@units/wispd.service"])
        self.assertTrue(result["ipc_ok"])
        self.assertEqual(calls[:2], [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "restart", "wispd"]])

    def assert_reload_exception_is_closed(self, error):
        self.prepare_unit()
        runner = mock.Mock(side_effect=error)
        with mock.patch("subprocess.run", side_effect=AssertionError("host process forbidden")):
            result = update.rollback(confirm=lambda _: True, restart=True,
                                     run=runner, emit_text=lambda _: None)
        self.assertTrue(result["rolled_back"])
        self.assertFalse(result["daemon_reload_ok"])
        self.assertEqual(result["runtime_error"], "daemon-reload-failed")
        self.assertIsNone(result["ipc_ok"])
        runner.assert_called_once_with(["systemctl", "--user", "daemon-reload"],
                                       capture_output=True, timeout=10)

    def test_missing_manager_fails_closed(self):
        self.assert_reload_exception_is_closed(FileNotFoundError("missing manager"))

    def test_timed_out_reload_fails_closed(self):
        self.assert_reload_exception_is_closed(
            update.subprocess.TimeoutExpired(["systemctl"], 10))


class Versions(unittest.TestCase):
    def test_installed_version_prefers_a_tag_ref(self):
        with mock.patch("wisp.deploy.read",
                        lambda: {"ref": "v1.2.3", "commit": "a" * 40}):
            self.assertEqual(update.installed_version(), "v1.2.3")
        with mock.patch("wisp.deploy.read",
                        lambda: {"ref": "master", "commit": "abcdef" * 6}):
            self.assertEqual(update.installed_version(), "abcdefabcdef")
        with mock.patch("wisp.deploy.read", lambda: None):
            self.assertEqual(update.installed_version(), "unknown")


if __name__ == "__main__":
    unittest.main()
