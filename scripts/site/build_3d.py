#!/usr/bin/env python3
"""Build the guiding-light preview (/light/) and the Wisp flame assets the
homepage (site-app/) links to, independently of site/."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site-3d"
FILES = (
    "vendor/PROVENANCE.md",
    "light/index.html", "light/light.css", "light/light.mjs",
    "light/fonts/newsreader-roman-latin.woff2", "light/fonts/newsreader-ital-latin.woff2",
    "vendor/OFL-Newsreader.txt", "vendor/THREEUI-LICENSE.txt",
    "wisp/sim.mjs", "wisp/gl.mjs",
)
# The Wisp flame ships from its brand source: published path -> repository path.
# Only what the pages use: the idle loop (hero) and stills (favicon,
# apple-touch-icon, reduced motion).
FLAME = ROOT / "assets/brand/wisp-flame/export"
BRAND = {
    "assets/wisp-flame/idle-256.webp": FLAME / "loops/idle-256.webp",
    **{f"assets/wisp-flame/wisp-flame-{size}.png": FLAME / f"stills/wisp-flame-{size}.png"
       for size in (32, 512)},
}
ALL = FILES + tuple(BRAND)

IMPORT = re.compile(r"""(?:from\s*|import\s*\(\s*|import\s*)["']([^"']+)["']""")
# Vendored code is scanned for real import statements only: its strings and
# comments quote colour-space names and example URLs.
VENDOR_IMPORT = re.compile(r"""^(?:import\b.*?|\})\s*from\s*["']([^"']+)["']""", re.M)
CSS_URL = re.compile(r"""url\(\s*["']?([^"')\s]+)""")


class SiteError(ValueError):
    pass


class Resources(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (key in ("src", "srcset", "poster") or key == "href" and tag != "a"):
                self.urls.append(value)


def locate(out, name):
    """Where an asset lives: the built tree, or its source before a build."""
    if out == SITE and name in BRAND:
        return BRAND[name]
    return out / name


def check(out):
    out = Path(out)
    problems = [f"missing asset: {name}" for name in ALL if not locate(out, name).is_file()]

    def resource(value, parent):
        parts = urlsplit(value)
        if parts.scheme or parts.netloc:
            problems.append(f"remote runtime asset: {value}")
            return
        target = (parent / parts.path).resolve()
        rel = target.relative_to(out.resolve()).as_posix() if target.is_relative_to(out.resolve()) else None
        if rel is None or not locate(out, rel).is_file():
            problems.append(f"missing or escaping asset: {value}")

    for name in FILES:
        path = out / name
        if not path.is_file():
            continue
        if path.suffix == ".html":
            parser = Resources()
            parser.feed(path.read_text())
            for url in parser.urls:
                resource(url, path.parent)
        elif path.suffix in (".mjs", ".js"):
            text = path.read_text()
            for url in (VENDOR_IMPORT if name.startswith("vendor/") else IMPORT).findall(text):
                resource(url, path.parent)
        elif path.suffix == ".css":
            for url in CSS_URL.findall(path.read_text()):
                resource(url, path.parent)
    return problems


def build(out):
    out = Path(out).resolve()
    if (ROOT.is_relative_to(out) or out.is_relative_to(SITE)
            or SITE.is_relative_to(out)):
        raise SiteError("output must not replace the repository or site source")
    # Validate the source before deleting any previously built output.
    problems = check(SITE)
    if problems:
        raise SiteError("; ".join(problems))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    inventory = {}
    for name in ALL:
        source, target = BRAND.get(name, SITE / name), out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        data = target.read_bytes()
        inventory[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    (out / "inventory.json").write_text(json.dumps(inventory, sort_keys=True, indent=2) + "\n")
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "build/site-3d"))
    args = parser.parse_args()
    try:
        out = build(args.out)
    except SiteError as exc:
        parser.exit(1, f"site-3d: {exc}\n")
    total = sum((out / name).stat().st_size for name in ALL)
    print(f"site-3d built in {out}: {len(ALL)} assets, {total} bytes")


if __name__ == "__main__":
    main()
