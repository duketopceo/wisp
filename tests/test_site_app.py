"""The wisp.observer homepage (site-app/): static HTML rendered at build time,
a small first-paint module, a lazy Canvas 2D mark over a server-rendered SVG
still, three colours and no others, nothing loaded from another host, and the
same claims as before."""
import html
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "site-app"
INSTALL = 'f=$(mktemp) && curl -fsSL https://wisp.observer/install.py -o "$f" && python3 "$f" --version v1.0.0-rc.2'
INK, PAPER, POP = "#15110E", "#F2ECE0", "#FF5B1F"
JOB = "Wisp is a voice teacher and doer for Omarchy that points at your screen."


def _luminance(hex_color):
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _theme_tokens(css, theme_selector):
    """A resolver for one theme's tokens: hex, var(--x), or an srgb color-mix of two tokens."""
    palette = dict(re.findall(r"--([\w-]+):\s*([^;]+);", css[:css.index("/* Light")]))
    light = css[css.index("/* Light"):css.index("/* Dark")]
    raw = {**palette, **dict(re.findall(r"--([\w-]+):\s*([^;]+);", light))}
    if theme_selector == "dark":
        block = css[css.index(':root[data-theme="dark"]'):]
        raw.update(dict(re.findall(r"--([\w-]+):\s*([^;]+);", block[:block.index("}")])))

    def resolve(name):
        value = raw[name].strip()
        if value.startswith("#"):
            return value.upper()
        ref = re.fullmatch(r"var\(--([\w-]+)\)", value)
        if ref:
            return resolve(ref.group(1))
        mix = re.fullmatch(r"color-mix\(in srgb, var\(--([\w-]+)\) ([\d.]+)%, var\(--([\w-]+)\)\)", value)
        if mix:
            first, pct, second = resolve(mix.group(1)), float(mix.group(2)) / 100, resolve(mix.group(3))
            parts = [round(int(first[i:i + 2], 16) * pct + int(second[i:i + 2], 16) * (1 - pct)) for i in (1, 3, 5)]
            return "#%02X%02X%02X" % tuple(parts)
        raise AssertionError(f"token --{name} is not a palette expression: {value}")
    return resolve


def _plain_builder():
    spec = importlib.util.spec_from_file_location("site_build_for_app", ROOT / "scripts/site/build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("node") and (ROOT / "node_modules/vite").is_dir(),
                     "run `npm ci --ignore-scripts` at the repository root first")
class Homepage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.out = Path(cls.td.name) / "published"
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/site/build_workers.py"), "--out", str(cls.out)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.log = result.stdout
        cls.raw = (cls.out / "index.html").read_text()
        cls.text = html.unescape(cls.raw)
        cls.js = {p.name: p.read_text() for p in (cls.out / "app").glob("*.js")}
        cls.css = "".join(p.read_text() for p in (cls.out / "app").glob("*.css"))

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def test_first_screen_has_the_job_and_the_install_cta(self):
        first = self.text[:self.text.index("<h2")]
        self.assertIn(JOB, first)
        self.assertIn('href="#install"', first)
        self.assertLess(self.raw.index("<h1"), self.raw.index('id="install-code"'))

    def test_install_uses_pinned_authenticated_candidate(self):
        self.assertIn(INSTALL, self.text)
        self.assertIn("--version v1.0.0-rc.2", self.text)
        self.assertIn("independently installed GitHub CLI", self.text)
        self.assertIn("not self-authenticating", self.text)
        self.assertIn("/blob/v1.0.0-rc.2/scripts/bootstrap/install.py", self.text)
        self.assertIn("~/.local/bin/wispd onboard", self.text)
        self.assertIn("A local preset alone does not make every data path local", self.text)

    def test_claims_stay_honest(self):
        self.assertIn("wisp.observer · Cloudflare Workers", self.text)
        self.assertIn("experimental", self.text.lower())
        self.assertNotIn("wisp.casa", self.text)
        self.assertNotIn("/install.sh", self.text)
        visible = re.sub(r"<[^>]+>", " ", self.text)  # copy, not class names
        self.assertNotRegex(visible, r"\b\d+\s*ms\b")
        self.assertIn("docs/TRUST.md", self.text)
        self.assertIn("What leaves your machine", self.text)

    def test_every_external_link_is_the_repo(self):
        for url in re.findall(r'href="(https?://[^"]+)"', self.raw):
            self.assertTrue(url.startswith("https://github.com/duketopceo/wisp"), url)

    def test_nothing_is_loaded_from_another_host(self):
        self.assertEqual([], _plain_builder().third_party(self.raw, self.css))
        self.assertNotRegex(self.raw + self.css,
                            r"(?i)<iframe|<form|@import|googletagmanager|google-analytics|plausible|fonts\.g|cdn\.")
        for name, code in self.js.items():
            self.assertNotRegex(code, r"""(?:from|import\(?)\s*["'](?:https?:)?//""", name)
            self.assertNotRegex(code, r"https?://(?!www\.w3\.org/)", name)

    def test_csp_allows_every_script(self):
        # script-src 'self': no inline script bodies, only same-origin files.
        for tag in re.findall(r"<script\b[^>]*>", self.raw):
            self.assertRegex(tag, r'src="/[^/]')
        self.assertNotRegex(self.raw, r"<script\b[^>]*>[^<]+</script>")
        self.assertNotRegex(self.raw, r"\son[a-z]+=")

    def test_hero_has_an_svg_still_and_the_mark_replaces_the_flame(self):
        stage = re.search(r'<div id="hero-mark" data-mark="still"[^>]*>(.*?)</svg></div>', self.raw, re.S)
        self.assertIsNotNone(stage)
        self.assertIn("<svg", stage.group(1))  # painted with no JavaScript run
        self.assertNotRegex(self.raw[self.raw.index("<body"):], r"idle-256\.webp|wisp-flame|<picture|<img\b")
        self.assertIn('rel="icon" href="/favicon.svg"', self.raw)
        self.assertTrue((self.out / "favicon.svg").is_file())
        self.assertIn('rel="apple-touch-icon"', self.raw)
        self.assertIn("prefers-reduced-motion", self.css)
        nav = self.raw[self.raw.index("<header"):self.raw.index("</header>")]
        self.assertIn("<svg", nav.split("</a>")[1])  # the navbar logo is the small glyph
        self.assertNotIn('data-stage="dark"', self.raw)

    def test_palette_is_three_colours_and_text_is_legible(self):
        source = (APP / "src/styles.css").read_text()
        self.assertEqual({INK, PAPER, POP}, {c.upper() for c in re.findall(r"#[0-9A-Fa-f]{3,8}\b", source)})
        self.assertNotIn("oklch(", source)
        self.assertNotRegex(source, r"(?<![\w-])(?:rgb|hsl|hwb|lab|lch)a?\(")
        for name, ground in (("light", PAPER), ("dark", INK)):
            token = _theme_tokens(source, name)
            self.assertEqual(ground, token("background"))
            for text in ("foreground", "muted-foreground"):
                for surface in ("background", "card", "muted"):
                    self.assertGreaterEqual(_contrast(token(text), token(surface)), 4.5, f"{name} {text} on {surface}")
            self.assertEqual(POP, token("primary"))
            self.assertGreaterEqual(_contrast(token("primary-foreground"), token("primary")), 4.5, name)

    def test_the_pop_is_never_a_text_colour(self):
        classes = " ".join(re.findall(r'class="([^"]*)"', self.raw)).split()
        offenders = [c for c in classes if re.match(r"(?:[\w:-]+:)?(?:text|decoration)-(?:primary|brand|flame|pop)(?:$|/)", c)
                     and not c.startswith("decoration-")]
        self.assertEqual([], offenders)
        self.assertNotRegex(self.css, r"(?<![-\w])color:\s*var\(--(?:pop|primary)\)")

    def test_page_works_without_javascript(self):
        for marker in ('id="install-code"', 'id="copy-status"', 'aria-live="polite"', 'id="copy-install"'):
            self.assertIn(marker, self.raw)
        self.assertGreaterEqual(self.raw.count("<details"), 5)  # FAQ needs no script
        self.assertRegex(self.raw, r'<button[^>]*id="theme-toggle"[^>]*hidden')
        self.assertIn('href="/plain/"', self.raw)

    def test_cost_card_is_the_sourced_one(self):
        import json
        costs = json.loads((ROOT / "site/costs.json").read_text())
        for item in costs["items"]:
            for key in ("label", "value", "source", "as_of"):
                self.assertIn(item[key], self.text, key)
        if costs["status"] != "measured":
            self.assertIn("not published yet", self.text)

    def test_first_paint_javascript_stays_small(self):
        import gzip
        first = sum(len(c.encode()) for n, c in self.js.items() if not n.startswith("mark-"))
        marks = [c for n, c in self.js.items() if n.startswith("mark-")]
        self.assertEqual(1, len(marks))
        self.assertLess(len(gzip.compress(marks[0].encode())), 3 * 1024)
        self.assertLess(first, 8 * 1024)
        self.assertLess(len(self.css.encode()), 64 * 1024)
        self.assertNotIn("react", " ".join(self.js.values()).lower().replace("reactive", ""))
        self.assertIn("first-paint JS", self.log)
        self.assertIn("lazy mark JS", self.log)

    def test_mark_respects_motion_power_and_failure(self):
        main = (APP / "src/client/main.ts").read_text()
        for needle in ("prefers-reduced-motion: reduce", "saveData", "hardwareConcurrency",
                       'import("./mark")', "requestIdleCallback", "recolor"):
            self.assertIn(needle, main)
        mark = (APP / "src/client/mark.ts").read_text()
        for needle in ("IntersectionObserver", "visibilitychange", 'getContext("2d")'):
            self.assertIn(needle, mark)
        self.assertLessEqual(float(re.search(r"Math\.min\(devicePixelRatio \|\| 1, ([\d.]+)\)", mark).group(1)), 2)

    def test_no_shader_or_ribbon_code_ships(self):
        self.assertFalse((APP / "src/client/hero.ts").exists())
        self.assertEqual([], [n for n in self.js if n.startswith("hero-")])
        for name, code in self.js.items():
            self.assertNotRegex(code, r"(?i)webgl|getExtension|gl_FragColor|precision\s+(?:high|medium)p", name)

    def test_third_party_branding_removed_and_notices_kept(self):
        self.assertNotRegex(self.text, r"(?i)launch ui|launch-ui|threeui")
        credits = (self.out / "credits.txt").read_text()
        self.assertIn("Copyright (c) 2024 Mikolaj Dobrucki", credits)
        self.assertIn("Copyright (c) 2024 Mikolaj Dobrucki", (ROOT / "THIRD_PARTY_NOTICES.md").read_text())
        self.assertNotRegex(credits, r"(?i)threeui|Meng To")
        self.assertFalse((APP / "licenses/THREEUI-LICENSE.txt").exists())

if __name__ == "__main__":
    unittest.main()
