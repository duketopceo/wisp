"""Personal-info denylist scan: fail on a planted token, never print it."""
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN = ROOT / "scripts" / "personal_info_scan.py"
TOKEN = "zzplantedtoken99"


def _run(root, env_extra):
    env = os.environ.copy()
    env.pop("WISP_PERSONAL_DENYLIST", None)
    env.pop("WISP_PERSONAL_DENYLIST_FILE", None)
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCAN), str(root)],
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


class PersonalInfoScanTest(unittest.TestCase):
    def test_planted_token_fails_without_printing_it(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "note.txt").write_text(
                f"hello {TOKEN.upper()} there\n", encoding="utf-8")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertNotEqual(code, 0)
        self.assertIn("note.txt:1", out)
        blob = (out + err).lower()
        self.assertNotIn(TOKEN.lower(), blob)

    def test_clean_tree_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "note.txt").write_text("nothing personal\n", encoding="utf-8")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertEqual(code, 0)
        self.assertNotIn("note.txt:", out)

    def test_license_is_exempt(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "LICENSE").write_text(TOKEN + "\n", encoding="utf-8")
            (root / "ok.txt").write_text("fine\n", encoding="utf-8")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertEqual(code, 0)
        blob = (out + err).lower()
        self.assertNotIn(TOKEN.lower(), blob)

    def test_binary_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "blob.bin").write_bytes(b"\x00" + TOKEN.encode() + b"\xff")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertEqual(code, 0)
        blob = (out + err).lower()
        self.assertNotIn(TOKEN.lower(), blob)

    def test_no_list_skips_with_notice(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "note.txt").write_text(TOKEN + "\n", encoding="utf-8")
            code, out, err = _run(root, {})
        self.assertEqual(code, 0)
        self.assertIn("skip", (out + err).lower())

    def test_missing_denylist_file_fails_without_contents(self):
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "note.txt").write_text("secret-body-line\n", encoding="utf-8")
            missing = root / "no-such-denylist.txt"
            code, out, err = _run(
                root, {"WISP_PERSONAL_DENYLIST_FILE": str(missing)})
        self.assertNotEqual(code, 0)
        blob = out + err
        self.assertNotIn("secret-body-line", blob)
        self.assertNotIn("clean", blob.lower())

    def test_token_in_paths_is_redacted(self):
        parent = pathlib.Path(tempfile.mkdtemp())
        root = parent / f"dir-{TOKEN}"
        root.mkdir()
        (root / "note.txt").write_text("plain\n", encoding="utf-8")
        missing = parent / f"list-{TOKEN}.txt"
        try:
            code, out, err = _run(root, {
                "WISP_PERSONAL_DENYLIST": TOKEN,
                "WISP_PERSONAL_DENYLIST_FILE": str(missing),
            })
        finally:
            missing.unlink(missing_ok=True)
            for p in root.iterdir():
                p.unlink()
            root.rmdir()
            parent.rmdir()
        self.assertNotEqual(code, 0)
        blob = (out + err).lower()
        self.assertNotIn(TOKEN.lower(), blob)
        self.assertNotIn("clean", blob)

    def test_casefold_expansion_does_not_print_token(self):
        # U+0130 casefolds to two code points. Folded indexes would
        # slice past the prefix and print the token.
        mark = "\u0130" * len(TOKEN)
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            nested = root / mark
            nested.mkdir()
            (nested / f"{TOKEN}.txt").write_text(TOKEN + "\n", encoding="utf-8")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertNotEqual(code, 0)
        blob = out + err
        self.assertNotIn(TOKEN, blob)
        self.assertNotIn(TOKEN.lower(), blob.lower())
        self.assertIn("[redacted]", out)

    def test_missing_root_fails_without_claiming_clean(self):
        missing = pathlib.Path(tempfile.mkdtemp()) / "no-such-root"
        code, out, err = _run(missing, {"WISP_PERSONAL_DENYLIST": TOKEN})
        self.assertNotEqual(code, 0)
        blob = (out + err).lower()
        self.assertNotIn("clean", blob)
        self.assertNotIn(TOKEN.lower(), blob)

    def test_casefold_expansion_token_is_redacted(self):
        # Straße casefolds to strasse. A plain IGNORECASE regex misses that,
        # so the path would print the token in clear.
        token = "Stra\u00dfe"
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            (root / "STRASSE.txt").write_text(token + "\n", encoding="utf-8")
            code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": token})
        self.assertNotEqual(code, 0)
        blob = (out + err).casefold()
        self.assertNotIn("strasse", blob)
        self.assertIn("[redacted]", out)

    def test_unreadable_file_makes_the_scan_incomplete(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores file permissions")
        with tempfile.TemporaryDirectory() as td:
            root = pathlib.Path(td)
            secret = root / "locked.txt"
            secret.write_text("nothing here\n", encoding="utf-8")
            secret.chmod(0o000)
            try:
                code, out, err = _run(root, {"WISP_PERSONAL_DENYLIST": TOKEN})
            finally:
                secret.chmod(0o600)
        self.assertEqual(code, 2)
        self.assertIn("incomplete", (out + err).lower())
        self.assertNotIn("clean", (out + err).lower())
