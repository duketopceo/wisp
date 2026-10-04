#!/usr/bin/env python3
"""Copy lint test (W17): user-facing strings carry no emoji, em/en dashes
or banned words, in Python and QML. Comments and docstrings are exempt.

Scope:
  - strict: every value in the wisp/copy.py tables, errors_codes human
    strings, the user-facing Python modules, WispService.qml and lib/*.js
  - ratchet: the QML surfaces not yet rewritten (Companion, Panel,
    BarWidget) may not gain violations; the counts only go down, and the
    surface units (W21 to W23) drive them to zero
"""
import pathlib
import sys
import unittest

import copylint

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import copy as wcopy  # noqa: E402
from wisp import errors_codes  # noqa: E402

PLUGIN = ROOT / "shell-plugin"
USER_FACING_PY = ("wisp/tui.py", "wisp/errors_codes.py")
STRICT_QML = ["WispService.qml"] + sorted(
    p.name for p in (PLUGIN / "lib").glob("*.js")
    if p.name not in ("icons.js",))
# files being rewritten by W21-W23; counts may only fall
RATCHET = {"Companion.qml": 6, "Panel.qml": 15, "BarWidget.qml": 0}


def table_strings():
    out = []
    for word, _tone in wcopy.STATUS.values():
        out.append(word)
    out += [t for _p, t, _s in wcopy.RESULT_RULES]
    out += list(wcopy.ACTION_VERBS.values())
    for msg, hint in wcopy.ERRORS.values():
        out += [msg, hint]
    out += list(wcopy.STRINGS.values())
    return out


class TestLinterRules(unittest.TestCase):
    def test_flags_each_rule(self):
        self.assertEqual(copylint.check_string("done \U0001F389"), ["emoji"])
        self.assertEqual(copylint.check_string("\u2726 ready"), ["emoji"])
        self.assertEqual(copylint.check_string("a \u2014 b"), ["dash"])
        self.assertEqual(copylint.check_string("a \u2013 b"), ["dash"])
        self.assertEqual(copylint.check_string("Simply do it"),
                         ["banned-word"])
        self.assertEqual(copylint.check_string("Oops, that failed"),
                         ["banned-word"])

    def test_clean_strings_pass(self):
        for s in ("ready", "didn't catch which app", "blocked: needs your ok",
                  "just answer", "a - b", "magician", "x \u00b7 y"):
            self.assertEqual(copylint.check_string(s), [], s)

    def test_python_comments_and_docstrings_exempt(self):
        src = ('"""doc \u2014 here"""\n# comment \u2014 here\n'
               'def f():\n    """inner \u2014 doc"""\n    return "ok"\n'
               'X = "bad \u2014 one"\n')
        self.assertEqual(sorted(copylint.python_strings(src)),
                         sorted(["ok", "bad \u2014 one"]))

    def test_qml_comments_exempt_urls_kept(self):
        src = ('// header \u2014 note\n/* block \u2014 note */\n'
               'Text { text: "bad \u2014 one" } // trailing \u2014 note\n'
               'property url u: "http://x.test/a"\n')
        self.assertEqual(copylint.qml_strings(src),
                         ["bad \u2014 one", "http://x.test/a"])


class TestPythonCopy(unittest.TestCase):
    def test_copy_tables(self):
        self.assertEqual(copylint.violations(table_strings()), [])

    def test_error_human_strings(self):
        self.assertEqual(
            copylint.violations(errors_codes._HUMAN.values()), [])

    def test_user_facing_modules(self):
        for rel in USER_FACING_PY:
            src = (ROOT / rel).read_text()
            self.assertEqual(
                copylint.violations(copylint.python_strings(src)), [], rel)


class TestQmlCopy(unittest.TestCase):
    def test_strict_files(self):
        for name in STRICT_QML:
            path = PLUGIN / name if name.endswith(".qml") \
                else PLUGIN / "lib" / name
            self.assertTrue(path.exists(), name)
            bad = copylint.violations(copylint.qml_strings(path.read_text()))
            self.assertEqual(bad, [], name)

    def test_unmigrated_surfaces_do_not_gain_violations(self):
        for name, ceiling in RATCHET.items():
            n = len(copylint.violations(copylint.qml_strings(
                (PLUGIN / name).read_text())))
            self.assertLessEqual(n, ceiling,
                                 f"{name}: {n} violations, ceiling {ceiling}")
            if n < ceiling:
                self.fail(f"{name} improved to {n}: lower its RATCHET to {n}")

    def test_every_qml_file_is_accounted_for(self):
        seen = {p.name for p in PLUGIN.glob("*.qml")}
        self.assertLessEqual(seen - set(STRICT_QML) - set(RATCHET), set())
        for p in (PLUGIN / "components").glob("*.qml"):
            self.assertEqual(copylint.violations(
                copylint.qml_strings(p.read_text())), [], p.name)


if __name__ == "__main__":
    unittest.main()
