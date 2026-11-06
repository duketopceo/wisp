"""The wisp.observer homepage (site-app/): static HTML rendered at build time,
a small first-paint module, a lazy WebGL hero with a designed static frame,
nothing loaded from another host, and the same claims as before."""
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
JOB = "Wisp is a voice teacher and doer for Omarchy that points at your screen."


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

    def test_hero_has_a_static_frame_and_flame_fallback(self):
        self.assertRegex(self.raw, r'id="hero-bg" data-hero="static"')
        self.assertIn('class="hero-frame', self.raw)
        self.assertIn('<source media="(prefers-reduced-motion: reduce)" srcSet="/assets/wisp-flame/wisp-flame-512.png"/>'.replace("srcSet", "srcset"),
                      self.raw.replace("srcSet", "srcset"))
        self.assertIn('src="/assets/wisp-flame/idle-256.webp"', self.raw)
        self.assertIn('rel="icon" href="/assets/wisp-flame/wisp-flame-32.png"', self.raw)
        self.assertIn('rel="apple-touch-icon"', self.raw)
        self.assertIn("prefers-reduced-motion", self.css)

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
        first = sum(len(c.encode()) for n, c in self.js.items() if not n.startswith("hero-"))
        hero = sum(len(c.encode()) for n, c in self.js.items() if n.startswith("hero-"))
        self.assertLess(first, 8 * 1024)
        self.assertLess(hero, 16 * 1024)
        self.assertLess(len(self.css.encode()), 64 * 1024)
        self.assertNotIn("react", " ".join(self.js.values()).lower().replace("reactive", ""))
        self.assertIn("first-paint JS", self.log)

    def test_hero_respects_motion_power_and_failure(self):
        main = (APP / "src/client/main.ts").read_text()
        for needle in ("prefers-reduced-motion: reduce", "saveData", "hardwareConcurrency",
                       'import("./hero")', "requestIdleCallback"):
            self.assertIn(needle, main)
        hero = (APP / "src/client/hero.ts").read_text()
        self.assertIn("failIfMajorPerformanceCaveat: true", hero)
        self.assertIn("webglcontextlost", hero)
        self.assertLessEqual(float(re.search(r"DPR_CAP = ([\d.]+)", hero).group(1)), 1.5)

    def test_third_party_branding_removed_and_notices_kept(self):
        self.assertNotRegex(self.text, r"(?i)launch ui|launch-ui|threeui")
        credits = (self.out / "credits.txt").read_text()
        for notice in ("Copyright (c) 2024 Mikolaj Dobrucki", "Copyright (c) 2026 Meng To"):
            self.assertIn(notice, credits)
            self.assertIn(notice, (ROOT / "THIRD_PARTY_NOTICES.md").read_text())
        head = (APP / "src/client/hero.ts").read_text()[:900]
        self.assertIn("ThreeUI Community", head)
        self.assertIn("MengTo/threeui", head)


if __name__ == "__main__":
    unittest.main()
