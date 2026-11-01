#!/usr/bin/env python3
"""wispd doctor human view: verdict first, problems with fixes, passes
collapsed, one line per row at 60, 80 and 200 columns."""
import json
import os
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from wisp.cli import diagnose, output  # noqa: E402
from cli_env import CliEnv  # noqa: E402

GOLD = ROOT / "tests" / "golden" / "output"


def _row(name, level, detail, fix=""):
    return {"name": name, "value": detail, "ok": level != "fail",
            "level": level, "detail": detail, "fix": fix}


SECTIONS = [
    {"name": "preflight", "rows": [
        _row("home", "ok", "user directory available"),
        _row("python", "ok", "3.13.5"),
        _row("hyprctl", "warn", "not found; needed for the push-to-talk "
             "bind and pointer",
             "Install separately if you need this capability."),
        _row("pw-record", "warn", "not found; needed for microphone capture",
             "Install separately if you need this capability."),
    ]},
    {"name": "integrations", "rows": [
        _row("dayflow", "fail", "not installed"),
        _row("codegraph (CBM)", "ok", "not installed"),
    ]},
    {"name": "data", "rows": [
        _row("skills", "ok", "0 installed"),
        _row("labels.jsonl", "ok", "absent"),
    ]},
]


def fake_ctx(width, color=False, glyphs=False):
    return types.SimpleNamespace(
        width=width, color=color, glyphs=glyphs, json=False,
        flags=types.SimpleNamespace(quiet=False),
        table=lambda h, r, t=None, header=True, **kw: output.table(
            h, r, t, color, None, header, **kw),
        paint_muted=lambda s: s)


def args(**kw):
    return types.SimpleNamespace(**{"all": False, "section": None, **kw})


def render(width, **kw):
    return diagnose._doctor_text(fake_ctx(width), kw.pop("sections",
                                                          SECTIONS),
                                 args(**kw))


class TestDoctorView(unittest.TestCase):
    def test_goldens_at_three_widths(self):
        for width in (60, 80, 200):
            with self.subTest(width=width):
                text = render(width) + "\n"
                f = GOLD / f"doctor_{width}.txt"
                if os.environ.get("WISP_UPDATE_GOLDEN"):
                    f.write_text(text)
                self.assertEqual(text, f.read_text(), f.name)

    def test_nothing_exceeds_the_width_and_rows_are_one_line(self):
        for width in (60, 80, 200):
            for kw in ({}, {"all": True}, {"section": "preflight"}):
                with self.subTest(width=width, **kw):
                    for line in render(width, **kw).splitlines():
                        self.assertLessEqual(output.display_width(line),
                                             min(width, 100), line)

    def test_verdict_and_counts_come_first(self):
        lines = render(80).splitlines()
        self.assertTrue(lines[0].startswith("wisp doctor"))
        self.assertTrue(lines[0].rstrip().endswith("1 fail, 2 warn, 5 ok"))
        self.assertTrue(lines[2].startswith("1 check needs attention."))

    def test_fail_rows_before_warn_rows_with_fix_on_its_own_line(self):
        text = render(80)
        self.assertLess(text.index("dayflow"), text.index("hyprctl"))
        i = text.index("hyprctl")
        self.assertIn("Try: Install separately",
                      text[i:].splitlines()[1])
        self.assertNotIn("fix:", text)

    def test_a_fix_shared_by_three_rows_is_said_once(self):
        fix = "Install separately if you need this capability."
        more = [{"name": "tools", "rows": [
            _row(n, "warn", "not found", fix) for n in ("a", "b", "c")]}]
        text = render(80, sections=more)
        self.assertEqual(text.count(fix), 1)
        self.assertIn("For the other rows, try: " + fix, text)
        self.assertEqual(render(80).count("Try: Install separately"), 2)

    def test_passes_are_collapsed_and_all_expands_them(self):
        text = render(80)
        self.assertIn("Passing (5)", text)
        self.assertNotIn("user directory available", text)
        full = render(80, all=True)
        for s in SECTIONS:
            for r in s["rows"]:
                self.assertIn(r["name"], full)
        self.assertIn("user directory available", full)

    def test_section_filter_and_unknown_section(self):
        t = render(80, section="data")
        self.assertIn("labels.jsonl", t)
        self.assertNotIn("hyprctl", t)
        from wisp.cli.registry import CliError
        with self.assertRaises(CliError) as cm:
            render(80, section="nope")
        self.assertEqual(cm.exception.code, "E_USAGE")

    def test_all_ok_and_only_warn_verdicts(self):
        ok = [{"name": "p", "rows": [_row("home", "ok", "fine")]}]
        t = render(80, sections=ok)
        self.assertIn("Everything is ready.", t)
        self.assertNotIn("Needs attention", t)
        warn = [{"name": "p", "rows": [_row("x", "warn", "d", "f")]}]
        self.assertIn("Ready.", render(80, sections=warn))

    def test_no_em_dash_and_no_escapes_in_plain_output(self):
        for width in (60, 200):
            t = render(width, all=True)
            self.assertNotIn("\u2014", t)
            self.assertNotIn("\x1b", t)


class TestDoctorCommand(unittest.TestCase):
    def test_json_keeps_old_keys_and_adds_level_and_counts(self):
        with CliEnv() as env:
            code, out, err = env.run(["doctor", "--json"])
            self.assertIn(code, (0, 4), err)
            data = json.loads(out)["data"]
            self.assertIn("healthy", data)
            self.assertEqual(set(data["counts"]), {"ok", "warn", "fail"})
            for s in data["sections"]:
                for r in s["rows"]:
                    self.assertTrue({"name", "value", "ok"} <= set(r))
                    self.assertIn(r["level"], ("ok", "warn", "fail"))
                    self.assertEqual(r["ok"], r["level"] != "fail")

    def test_exit_code_and_error_are_unchanged_when_unhealthy(self):
        with CliEnv() as env:
            code, out, err = env.run(["doctor"])
            if code == 4:
                self.assertIn("E_UNHEALTHY:", err)
                self.assertIn("need attention", out)
            else:
                self.assertEqual(code, 0, err)

    def test_quiet_prints_nothing_on_stdout(self):
        with CliEnv() as env:
            code, out, err = env.run(["doctor", "--quiet"])
            self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
