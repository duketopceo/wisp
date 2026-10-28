"""B9: `wispd update` verifies, previews, and never installs unasked."""
import hashlib
import io
import os
import pathlib
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from wisp import update  # noqa: E402

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
        for p in (mock.patch.object(update, "opt_dir", lambda: self.opt),
                  mock.patch.object(update, "asset_name", lambda: NAME),
                  mock.patch.object(update, "installed_version",
                                    lambda: "v1.0.0")):
            p.start()
            self.addCleanup(p.stop)

    def release(self, digest=True, sums=None):
        a = {"name": NAME, "browser_download_url": URL}
        if digest:
            a["digest"] = "sha256:" + self.sha
        assets = [a]
        if sums:
            assets.append({"name": "SHA256SUMS",
                           "browser_download_url": update.DOWNLOAD_PREFIX
                           + "v2.0.0/SHA256SUMS"})
        return {"tag_name": "v2.0.0", "assets": assets}

    def seams(self, rel, blob=None, sums=""):
        blob = self.blob if blob is None else blob

        def fetch_file(url, dest):
            self.downloads += 1
            pathlib.Path(dest).write_bytes(blob)
            return hashlib.sha256(blob).hexdigest()
        return dict(fetch_json=lambda u: rel, fetch_file=fetch_file,
                    fetch_text=lambda u: sums)


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
            install_fn=lambda root: ran.append(root) or 0,
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
            return 0
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
                               lambda: "v2.0.0"):
            res, asked, ran = self.go(True)
        self.assertEqual((asked, ran), ([], []))


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
