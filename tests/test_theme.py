#!/usr/bin/env python3
"""Omarchy theme -> Wisp token adapter (DESIGN-v2 5.1, 5.2; plan U1).

Fixtures live in tests/fixtures/themes/<name>/colors.toml (stock Omarchy
copies, the user's Vantablack override, and two synthetic edge cases).
expected.json beside each is the golden token set the QML port
(shell-plugin/lib/tokens.js) is also tested against. Regenerate after an
intentional algorithm change with:

    python -c "from tests.test_theme import regen; regen()"
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wisp import theme  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "themes"
LIGHT = ("white", "catppuccin-latte", "flexoki-light")
DARK = ("vantablack", "tokyo-night", "red-accent", "partial")


def fixture(name):
    return theme.load(FIXTURES / name)


def regen():
    for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        (d / "expected.json").write_text(
            json.dumps(theme.load(d), indent=2, sort_keys=True) + "\n")


class TestEmber(unittest.TestCase):
    def test_vantablack_override_keeps_its_own_orange(self):
        self.assertEqual(fixture("vantablack")["tokens"]["ember"], "#e58a4b")

    def test_tokyo_night_takes_its_blue(self):
        self.assertEqual(fixture("tokyo-night")["tokens"]["ember"], "#7aa2f7")

    def test_white_low_chroma_falls_back_to_yellow_then_clamps(self):
        t = fixture("white")["tokens"]
        L, C, _ = theme.oklch(t["ember"])
        yl, _, _ = theme.oklch("#4a4a4a")
        self.assertLess(yl, 0.45)          # raw yellow is below the band
        self.assertAlmostEqual(L, 0.45, delta=0.006)
        self.assertLess(C, 0.02)           # still the theme's grey, not accent
        self.assertNotEqual(t["ember"], t["accent"])

    def test_red_accent_rotates_away_from_urgent(self):
        t = fixture("red-accent")["tokens"]
        self.assertNotEqual(t["ember"], "#f7768e")
        self.assertGreaterEqual(theme.delta_e(t["ember"], t["fail"]), 10)
        colors = theme.parse_colors(
            (FIXTURES / "red-accent" / "colors.toml").read_text())
        hues = [theme.oklch(colors[k])[2] for k in ("orange", "yellow")]
        h = theme.oklch(t["ember"])[2]
        self.assertTrue(any(abs(h - x) < 2 for x in hues), (h, hues))

    def test_light_fixtures_clamp_lightness(self):
        for name in LIGHT:
            L = theme.oklch(fixture(name)["tokens"]["ember"])[0]
            self.assertTrue(0.445 <= L <= 0.605, (name, L))

    def test_dark_fixtures_clamp_lightness(self):
        for name in DARK:
            L = theme.oklch(fixture(name)["tokens"]["ember"])[0]
            self.assertTrue(0.695 <= L <= 0.855, (name, L))

    def test_core_brighter_and_wick_darker(self):
        for name in LIGHT + DARK:
            t = fixture(name)["tokens"]
            L = theme.oklch(t["ember"])[0]
            self.assertGreater(theme.oklch(t["emberCore"])[0], L, name)
            self.assertLess(theme.oklch(t["emberWick"])[0], L, name)


class TestContrast(unittest.TestCase):
    def test_ink_muted_meets_4_5_everywhere(self):
        for name in LIGHT + DARK:
            t = fixture(name)["tokens"]
            self.assertGreaterEqual(
                theme.contrast(t["inkMuted"], t["canvas"]), 4.5, name)

    def test_tokyo_night_raw_muted_needed_the_fix(self):
        colors = theme.parse_colors(
            (FIXTURES / "tokyo-night" / "colors.toml").read_text())
        self.assertLess(
            theme.contrast(colors["muted"], colors["background"]), 4.5)

    def test_state_colors_meet_3_to_1(self):
        for name in LIGHT + DARK:
            t = fixture(name)["tokens"]
            for k in ("needsYou", "fail", "ok", "ember"):
                self.assertGreaterEqual(
                    theme.contrast(t[k], t["canvas"]), 3.0, (name, k))

    def test_ember_halo_separates_creature(self):
        for name in LIGHT + DARK:
            t = fixture(name)["tokens"]
            self.assertGreaterEqual(
                theme.contrast(t["emberHalo"], t["ember"]), 3.0, name)

    def test_check_passes_on_every_fixture(self):
        for name in LIGHT + DARK:
            rows = theme.check(fixture(name))
            bad = [r for r in rows if not r["ok"]]
            self.assertEqual(bad, [], name)

    def test_check_reports_failures(self):
        res = theme.derive({"background": "#808080", "foreground": "#858585",
                            "accent": "#808080", "red": "#888888"})
        self.assertTrue(any(not r["ok"] for r in theme.check(res)))


class TestFallbacksAndParsing(unittest.TestCase):
    def test_missing_theme_dir_uses_dark_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            res = theme.load(pathlib.Path(d) / "nope")
        self.assertEqual(res["source"], "fallback")
        self.assertEqual(res["mode"], "dark")
        self.assertEqual(res["tokens"]["canvas"], theme.DARK["canvas"])

    def test_fallback_light_selected_by_config(self):
        with tempfile.TemporaryDirectory() as d:
            res = theme.load(pathlib.Path(d) / "nope",
                             cfg={"ui": {"theme": "light"}})
        self.assertEqual(res["mode"], "light")
        self.assertEqual(res["tokens"]["canvas"], theme.LIGHT["canvas"])

    def test_partial_theme_uses_documented_fallbacks(self):
        res = fixture("partial")
        t = res["tokens"]
        self.assertEqual(res["source"], "omarchy")
        self.assertEqual(res["mode"], "dark")        # inferred from canvas
        self.assertEqual(t["fail"], "#d75f5f")
        self.assertEqual(t["needsYou"], t["fail"])    # no yellow -> urgent
        self.assertEqual(t["ok"], t["accent"])        # no green -> accent
        self.assertEqual(t["raised"], theme.over("#d0d0d0", 0.06, "#202020"))
        self.assertEqual(t["selection"],
                         theme.over("#5fafd7", 0.35, "#202020"))

    def test_shell_toml_feeds_canvas_and_strong_keyline(self):
        t = fixture("vantablack")["tokens"]
        self.assertEqual(t["canvas"], "#000000")
        self.assertEqual(t["keylineStrong"], "#e58a4b")

    def test_no_shell_toml_strong_keyline_is_accent(self):
        t = fixture("catppuccin-latte")["tokens"]
        self.assertEqual(t["keylineStrong"], t["accent"])

    def test_parse_handles_comments_and_case(self):
        c = theme.parse_colors('# x\nmode = "light"\nAccent = "#ABCDEF" # c\n'
                               'muted="#010203"\n')
        self.assertEqual(c, {"mode": "light", "accent": "#abcdef",
                             "muted": "#010203"})

    def test_color_singleton_aliases(self):
        res = theme.derive({"color0": "#111111", "color7": "#eeeeee",
                            "color4": "#3366cc", "color1": "#cc3333"})
        t = res["tokens"]
        self.assertEqual((t["canvas"], t["ink"], t["accent"], t["fail"]),
                         ("#111111", "#eeeeee", "#3366cc", "#cc3333"))

    def test_every_token_is_opaque_hex(self):
        for name in LIGHT + DARK:
            t = fixture(name)["tokens"]
            self.assertEqual(sorted(t), sorted(theme.TOKENS), name)
            for k, v in t.items():
                self.assertRegex(v, r"^#[0-9a-f]{6}$", (name, k))


class TestGolden(unittest.TestCase):
    def test_fixtures_match_expected_json(self):
        dirs = [p for p in FIXTURES.iterdir() if p.is_dir()]
        self.assertGreaterEqual(len(dirs), 7)
        for d in dirs:
            exp = json.loads((d / "expected.json").read_text())
            self.assertEqual(theme.load(d), exp, d.name)


class TestCss(unittest.TestCase):
    def test_css_has_every_token_and_no_other_hex(self):
        res = fixture("catppuccin-latte")
        css = theme.css(res)
        for k, v in res["tokens"].items():
            prop = "--wisp-" + re.sub(r"([A-Z])", r"-\1", k).lower()
            self.assertIn(f"{prop}: {v};", css)
        self.assertEqual(len(re.findall(r"#[0-9a-fA-F]{3,8}\b", css)),
                         len(theme.TOKENS))
        self.assertIn("color-scheme: light;", css)

    def test_write_css_is_atomic_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = pathlib.Path(d) / "theme.css"
            theme.write_css(fixture("tokyo-night"), out)
            self.assertTrue(out.read_text().startswith("/*"))
            self.assertFalse(out.with_suffix(".tmp").exists())


class TestWispdTheme(unittest.TestCase):
    def _run(self, *args):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, HOME=d, XDG_CONFIG_HOME=d + "/c",
                       XDG_DATA_HOME=d + "/s", XDG_RUNTIME_DIR=d + "/r",
                       XDG_STATE_HOME=d + "/st")
            return subprocess.run(
                [sys.executable, str(ROOT / "wispd"), "theme", *args],
                capture_output=True, text=True, env=env, timeout=60)

    def test_check_passes_on_fixture(self):
        p = self._run("--check", str(FIXTURES / "flexoki-light"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("inkMuted", p.stdout)

    def test_check_fails_on_bad_theme(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "colors.toml").write_text(
                'background = "#808080"\nforeground = "#858585"\n'
                'accent = "#808080"\nred = "#888888"\n')
            p = self._run("--check", d)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("FAIL", p.stdout)

    def test_css_prints_stylesheet_for_fixture(self):
        p = self._run("--css", str(FIXTURES / "tokyo-night"), "-")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("--wisp-ember: #7aa2f7;", p.stdout)


if __name__ == "__main__":
    unittest.main()
