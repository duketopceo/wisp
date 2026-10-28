"""B26: the changelog, its rules, and the one-time what's-new card."""
import contextlib
import io
import json
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import cli, whatsnew as wn  # noqa: E402

LOG = """# Changelog

## Unreleased

- Draw on the screen.
- Walkthroughs.
- Faster answers (thanks @ada-lovelace)
- A fourth thing.
- A fifth thing.

## v1.2.0 - 2026-10-01

- One headline.
- Two.

## v1.1.0 - 2026-09-01

- Old news.
"""


class Parse(unittest.TestCase):
    def test_sections_dates_and_credits(self):
        s = wn.parse(LOG)
        self.assertEqual([x["version"] for x in s],
                         ["Unreleased", "v1.2.0", "v1.1.0"])
        self.assertEqual(s[1]["date"], "2026-10-01")
        third = s[0]["lines"][2]
        self.assertEqual((third["text"], third["who"]),
                         ("Faster answers", "@ada-lovelace"))
        self.assertEqual(s[0]["lines"][0]["who"], "")

    def test_a_version_without_v_still_matches(self):
        s = wn.parse("## 2.0.0 - 2026-01-01\n- x\n")
        self.assertEqual(s[0]["version"], "v2.0.0")
        self.assertIs(wn.find(s, "2.0.0"), s[0])
        self.assertIs(wn.find(s, "v2.0.0"), s[0])

    def test_find_release_tag_and_commit_install(self):
        s = wn.parse(LOG)
        self.assertEqual(wn.find(s, "v1.2.0")["version"], "v1.2.0")
        self.assertEqual(wn.find(s, "6b7d801aa1c2")["version"],
                         "Unreleased")
        self.assertIsNone(wn.find(s, "v9.9.9"))
        self.assertIsNone(wn.find(s, "unknown"))
        self.assertIsNone(wn.find(s, ""))


class Lint(unittest.TestCase):
    def test_a_count_needs_a_source(self):
        bad = wn.lint("## v1.0.0\n- Loved by 12,000 users.\n")
        self.assertEqual(len(bad), 1)
        self.assertIn("no source", bad[0])
        self.assertEqual(wn.lint(
            "## v1.0.0\n- Loved by 12,000 users "
            "(source: https://example.com/stats).\n"), [])

    def test_other_counts_are_fine(self):
        self.assertEqual(wn.lint(
            "## v1.0.0\n- Keeps 100 entries for 7 days.\n"
            "- Speed 0.5 to 1.5 times.\n"), [])

    def test_stars_and_downloads_are_caught(self):
        for claim in ("1k stars", "300 downloads", "5 contributors"):
            self.assertTrue(wn.lint(f"## v1.0.0\n- Now {claim}.\n"), claim)

    def test_the_shipped_changelog_follows_its_own_rules(self):
        text = (ROOT / "CHANGELOG.md").read_text()
        self.assertEqual(wn.lint(text), [])
        secs = wn.parse(text)
        self.assertEqual(secs[0]["version"], "Unreleased")
        for s in secs:
            self.assertGreaterEqual(len(s["lines"]), 1, s["version"])
        self.assertIn("v0.9.0", [s["version"] for s in secs])
        # every released version in git is in the changelog
        self.assertIn("v0.1.0-rc1", [s["version"] for s in secs])


class Card(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.state = pathlib.Path(td.name) / "d" / "whatsnew.json"

    def card(self, v):
        return wn.card(version=v, text=LOG, path=self.state)

    def test_first_install_shows_nothing_and_records_the_version(self):
        self.assertIsNone(self.card("v1.1.0"))
        self.assertEqual(json.loads(self.state.read_text())["seen"],
                         "v1.1.0")
        self.assertIsNone(self.card("v1.1.0"))

    def test_an_update_shows_the_headline_once_the_panel_marks_it_seen(
            self):
        self.card("v1.1.0")
        c = self.card("v1.2.0")
        self.assertEqual(c["lines"], ["One headline.", "Two."])
        self.assertEqual(c["title"], "v1.2.0")
        self.assertEqual(c["more"], 0)
        self.assertTrue(c["url"].startswith("https://github.com/"))
        self.assertEqual(self.card("v1.2.0")["version"], "v1.2.0")
        wn.mark_seen("v1.2.0", path=self.state)
        self.assertIsNone(self.card("v1.2.0"))

    def test_three_headlines_credit_and_more(self):
        self.card("v1.1.0")
        c = self.card("abc123def456")      # a commit install
        self.assertEqual(c["title"], "Unreleased")
        self.assertEqual(len(c["lines"]), 3)
        self.assertEqual(c["more"], 2)
        self.assertEqual(c["credits"], ["@ada-lovelace"])
        self.assertNotIn("thanks", " ".join(c["lines"]))

    def test_a_version_with_no_section_is_recorded_silently(self):
        self.card("v1.1.0")
        self.assertIsNone(self.card("v7.0.0"))
        self.assertEqual(json.loads(self.state.read_text())["seen"],
                         "v7.0.0")

    def test_the_state_file_is_private(self):
        self.card("v1.1.0")
        self.assertEqual(stat.S_IMODE(os.stat(self.state).st_mode), 0o600)

    def test_a_corrupt_state_counts_as_a_first_install(self):
        self.state.parent.mkdir(parents=True)
        self.state.write_text("{nope")
        self.assertIsNone(self.card("v1.2.0"))


class Command(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        d = pathlib.Path(td.name)
        self.log = d / "CHANGELOG.md"
        self.log.write_text(LOG)
        self.state = d / "whatsnew.json"
        for p in (mock.patch.object(wn, "STATE", self.state),
                  mock.patch.object(wn, "changelog_path",
                                    lambda: self.log),
                  mock.patch("wisp.update.installed_version",
                             lambda: self.version)):
            p.start()
            self.addCleanup(p.stop)
        self.version = "v1.1.0"

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(
                err):
            code = cli.main(list(argv), host=None)
        return code, out.getvalue(), err.getvalue()

    def test_json_card_flow(self):
        code, out, _ = self.run_cmd("whatsnew", "--json")
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(out)["data"]["card"])  # first install
        self.version = "v1.2.0"
        code, out, _ = self.run_cmd("whatsnew", "--json")
        d = json.loads(out)["data"]
        self.assertEqual(d["card"]["lines"], ["One headline.", "Two."])
        self.assertFalse(d["seen"])
        code, out, _ = self.run_cmd("whatsnew", "--seen", "--json")
        self.assertTrue(json.loads(out)["data"]["seen"])
        code, out, _ = self.run_cmd("whatsnew", "--json")
        self.assertIsNone(json.loads(out)["data"]["card"])

    def test_text_card_and_all(self):
        self.run_cmd("whatsnew")
        self.version = "v1.2.0"
        code, out, _ = self.run_cmd("whatsnew")
        self.assertIn("What's new in v1.2.0 (2026-10-01)", out)
        self.assertIn("- One headline.", out)
        code, out, _ = self.run_cmd("whatsnew", "--all")
        self.assertIn("Old news.", out)

    def test_nothing_new_says_so(self):
        self.run_cmd("whatsnew")
        code, out, _ = self.run_cmd("whatsnew")
        self.assertEqual(code, 0)
        self.assertIn("nothing new", out)


class Install(unittest.TestCase):
    def test_the_installer_ships_the_changelog(self):
        src = (ROOT / "wispd").read_text()
        self.assertIn('"CHANGELOG.md"', src)


if __name__ == "__main__":
    unittest.main()
