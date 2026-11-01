"""The bootstrap installer's terminal output: guiding-light steps on a tty,
plain lines when piped, security wording and --inspect-source untouched."""
import ast
import contextlib
import importlib.util
import io
import os
import pathlib
import re
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/bootstrap/install.py"
GOLD = ROOT / "tests" / "golden" / "output"

# The security statements, word for word. Whitespace may reflow; nothing
# else about them may change.
SECURITY = [
    "Require independent gh/Sigstore attestation verification plus SHA-256 "
    "before safe extraction; preview installer, then install user-scoped "
    "files. No service start or restart.",
    "Dry run: no network, writes or service actions.",
]


class TTY(io.StringIO):
    def isatty(self):
        return True


def load():
    spec = importlib.util.spec_from_file_location("wisp_bootstrap", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(argv, tty=False, cols=None, lang="en_US.UTF-8", no_color="1"):
    env = {"HOME": "/nonexistent-home", "LANG": lang, "TERM": "xterm"}
    if no_color:
        env["NO_COLOR"] = no_color
    if cols:
        env["COLUMNS"] = str(cols)
    out = TTY() if tty else io.StringIO()
    mod = load()
    with mock.patch.dict(os.environ, env, clear=True), \
            mock.patch("platform.system", return_value="Linux"), \
            mock.patch("platform.machine", return_value="x86_64"), \
            mock.patch("urllib.request.urlopen",
                       side_effect=AssertionError("network")), \
            contextlib.redirect_stdout(out):
        rc = mod.main(argv)
    return rc, out.getvalue()


def flat(text):
    return " ".join(text.split())


class TestBootstrapUi(unittest.TestCase):
    def test_inspect_source_is_byte_identical(self):
        rc, out = run(["--inspect-source"], tty=True, cols=60)
        self.assertEqual(rc, 0)
        self.assertEqual(out, SCRIPT.read_text())

    def test_security_wording_survives_on_every_surface(self):
        for tty, cols in ((False, None), (True, 60), (True, 80), (True, 200)):
            with self.subTest(tty=tty, cols=cols):
                rc, out = run(["--dry-run"], tty=tty, cols=cols)
                self.assertEqual(rc, 0)
                for sentence in SECURITY:
                    self.assertIn(sentence, flat(out))

    def test_goldens_piped_and_at_three_widths_on_a_tty(self):
        cases = [("install_dryrun_plain", False, None)] + [
            (f"install_dryrun_{c}", True, c) for c in (60, 80, 200)]
        for name, tty, cols in cases:
            with self.subTest(name=name):
                rc, out = run(["--dry-run"], tty=tty, cols=cols)
                f = GOLD / f"{name}.txt"
                if os.environ.get("WISP_UPDATE_GOLDEN"):
                    f.write_text(out)
                self.assertEqual(out, f.read_text())

    def test_tty_lines_fit_the_window(self):
        for cols in (60, 80, 200):
            rc, out = run(["--dry-run"], tty=True, cols=cols)
            for line in out.splitlines():
                if "https://" in line:      # an unbreakable URL may overflow
                    continue
                self.assertLessEqual(len(line), min(cols, 100), line)

    def test_piped_output_is_plain_ascii_without_wordmark_or_wrapping(self):
        rc, out = run(["--dry-run"], tty=False, cols=40)
        self.assertTrue(out.isascii())
        self.assertNotIn("\x1b", out)
        self.assertNotIn("voice agent", out)
        self.assertNotIn("installer\n", out.split("Plan")[0])
        long = [l for l in out.splitlines() if "attestation verification" in l]
        self.assertEqual(len(long), 1)      # one line, never wrapped

    def test_tty_has_wordmark_and_one_lit_dot_per_step(self):
        rc, out = run(["--dry-run"], tty=True, cols=80)
        self.assertTrue(out.startswith("\u25cf wisp\n  installer\n"))
        self.assertEqual(out.count("\u25cf"), 2)    # wordmark + step 1
        self.assertIn("step 1 of 6", out)

    def test_ascii_locale_and_dumb_term_fall_back(self):
        rc, out = run(["--dry-run"], tty=True, cols=80, lang="C")
        self.assertTrue(out.isascii())
        self.assertTrue(out.startswith("* wisp"))

    def test_color_only_with_a_tty_and_no_no_color(self):
        rc, out = run(["--dry-run"], tty=True, cols=80, no_color="")
        self.assertIn("\x1b[1;33m", out)
        rc, out = run(["--dry-run"], tty=False, no_color="")
        self.assertNotIn("\x1b", out)

    def test_refusals_keep_their_exact_text_and_codes(self):
        mod = load()
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"SUDO_USER": "x",
                                          "HOME": "/nonexistent"}), \
                mock.patch("platform.system", return_value="Linux"), \
                mock.patch("platform.machine", return_value="x86_64"), \
                contextlib.redirect_stdout(out):
            rc = mod.main([])
        self.assertEqual(rc, 4)
        self.assertIn("Refusing root/sudo installation. Run as your normal "
                      "desktop user.", flat(out.getvalue()))
        self.assertIn("step 2 of 6", out.getvalue())

    def test_the_bootstrap_still_imports_only_the_standard_library(self):
        tree = ast.parse(SCRIPT.read_text())
        mods = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add((n.module or "").split(".")[0])
        import sys
        std = set(sys.stdlib_module_names)
        self.assertEqual(mods - std, set(), mods - std)
        self.assertNotIn("wisp", mods)


if __name__ == "__main__":
    unittest.main()
