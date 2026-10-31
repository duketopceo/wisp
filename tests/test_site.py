"""B19: the landing page leads with the job, loads nothing from anywhere
else, names a source and date for every number, and stays small."""
import datetime as dt
import importlib.util
import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


build = _load("site_build", "scripts/site/build.py")
costcard = _load("site_costcard", "scripts/site/costcard.py")


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.out = pathlib.Path(cls.td.name) / "site"
        build.build(cls.out)
        cls.page = (cls.out / "index.html").read_text("utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_first_screen_has_the_job_and_the_install_line(self):
        first = self.page[:self.page.find("<h2")]
        self.assertIn(build.JOB, first)
        self.assertIn("python3 wispd install", first)
        self.assertLess(self.page.find("<h1>"), self.page.find("<pre>"))

    def test_install_line_is_the_one_in_the_readme(self):
        self.assertIn(build.INSTALL.split(" && ")[0],
                      (ROOT / "README.md").read_text("utf-8"))
        self.assertIn("python3 wispd install",
                      (ROOT / "README.md").read_text("utf-8"))

    def test_nothing_is_loaded_from_another_host(self):
        css = (self.out / "style.css").read_text()
        self.assertEqual(build.third_party(self.page, css), [])
        self.assertNotRegex(self.page + css,
                            r"(?i)<script|<iframe|<form|@import|"
                            r"googletagmanager|google-analytics|plausible|fonts\.g")

    def test_the_checker_catches_third_party_loads(self):
        bad = ('<img src="https://cdn.example.com/a.png">'
               '<link rel="stylesheet" href="//x.example/s.css">'
               '<a href="https://example.com">fine</a>')
        self.assertEqual(len(build.third_party(bad)), 2)
        self.assertEqual(build.third_party("", "a{background:url(https://e.x/a)}"),
                         ["https://e.x/a"])

    def test_every_external_link_is_the_repo_or_a_cited_source(self):
        allowed = ("https://github.com/duketopceo/wisp",
                   "https://www.heyclicky.com/",
                   "https://github.com/wombatoperator/omarchy-voice")
        for url in re.findall(r'href="(https?://[^"]+)"', self.page):
            self.assertTrue(url.startswith(allowed), url)

    def test_size_budget_with_a_full_size_poster(self):
        size = sum(p.stat().st_size for p in self.out.iterdir()
                   if p.suffix in (".html", ".css"))
        self.assertLess(size + 250 * 1024, build.BUDGET)

    def test_over_budget_is_a_build_error(self):
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            (out / "index.html").write_text(self.page)
            (out / "style.css").write_text("")
            (out / "p.png").write_bytes(b"0" * (build.BUDGET + 1))
            self.assertTrue(any("budget" in p for p in build.check(out)))

    def test_no_unfilled_placeholders(self):
        self.assertNotIn("{{", self.page)

    def test_a_published_recording_becomes_the_hero(self):
        # the real tree has none yet: the page says so instead of faking one
        if not list((ROOT / "assets/readme").glob("*.mp4")):
            self.assertIn("No recording is published yet", self.page)
        else:
            self.assertIn("<video", self.page)


class CostCard(unittest.TestCase):
    def test_every_number_names_a_source_and_a_date(self):
        costs = json.loads((ROOT / "site/costs.json").read_text())
        self.assertTrue(costs["items"])
        for it in costs["items"]:
            for k in ("label", "value", "source", "as_of"):
                self.assertTrue(it.get(k), (k, it))
            dt.date.fromisoformat(it["as_of"])
            if it["kind"] == "repo":
                f = it["source"].split(" ")[0]
                self.assertTrue((ROOT / f).is_file(), f)

    def test_the_default_caps_on_the_card_are_the_ones_in_the_code(self):
        from wisp import ledger
        costs = json.loads((ROOT / "site/costs.json").read_text())
        vals = {i["label"]: i["value"] for i in costs["items"]}
        self.assertEqual(vals["Default daily spend cap"],
                         f"${ledger.DEFAULT_DAILY_USD:.2f}")
        self.assertEqual(vals["Default monthly spend cap"],
                         f"${ledger.DEFAULT_MONTHLY_USD:.2f}")

    def test_pending_card_says_the_measured_numbers_are_not_published(self):
        costs = json.loads((ROOT / "site/costs.json").read_text())
        card = build.cost_card(costs)
        if costs["status"] != "measured":
            self.assertIn("not published yet", card)

    def test_a_card_item_without_a_source_is_refused(self):
        with self.assertRaises(build.SiteError):
            build.cost_card({"items": [{"label": "x", "value": "$1",
                                        "as_of": "2026-10-28"}]})

    def test_costcard_measures_paid_rows_in_the_window_only(self):
        today = dt.date(2026, 10, 28)
        rows = [
            {"ts": "2026-10-27T10:00:00", "usd": 0.01, "paid": True},
            {"ts": "2026-10-27T11:00:00", "usd": 0.03, "paid": True},
            {"ts": "2026-10-26T11:00:00", "usd": 0.10, "paid": True},
            {"ts": "2026-10-26T12:00:00", "usd": 0.0, "paid": False},  # local
            {"ts": "2026-08-01T12:00:00", "usd": 9.0, "paid": True},   # old
            {"ts": "garbage", "usd": 1, "paid": True},
        ]
        c = costcard.card(rows, today, 30)
        v = {i["label"]: i["value"] for i in c["items"]}
        self.assertEqual(c["status"], "measured")
        self.assertEqual(v["Median cost of one paid model call"], "$0.0300")
        self.assertEqual(v["Median cost of a day of use"], "$0.07")
        self.assertEqual(v["Most expensive day"], "$0.10")
        self.assertEqual(v["Median paid calls on a day of use"], "1.5")
        for i in c["items"]:
            self.assertIn("2026-09-28 to 2026-10-28", i["source"])
            self.assertEqual(i["as_of"], "2026-10-28")

    def test_no_paid_calls_stays_pending(self):
        c = costcard.card([{"ts": "2026-10-27T10:00:00", "usd": 0,
                            "paid": False}], dt.date(2026, 10, 28))
        self.assertEqual(c["status"], "pending")
        self.assertEqual(c["items"], [])


class Compare(unittest.TestCase):
    def test_every_row_names_a_dated_source_url(self):
        c = json.loads((ROOT / "site/compare.json").read_text())
        for row in c["rows"]:
            self.assertRegex(row[-1], r"^https://\S+ \(.*read 2026-\d\d-\d\d")


class Workflow(unittest.TestCase):
    def test_ci_only_produces_an_artifact_after_both_site_lanes_pass(self):
        y = (ROOT / ".github/workflows/pages.yml").read_text()
        self.assertIn("needs: [build, enhanced]", y)
        self.assertIn("name: wisp-workers-assets", y)
        self.assertNotIn("actions/deploy-pages", y)
        self.assertNotIn("pages: write", y)
        self.assertNotIn("cname", y.lower())
        self.assertNotIn("CNAME", "".join(p.name for p in
                                          (ROOT / "site").iterdir()))


if __name__ == "__main__":
    unittest.main()
