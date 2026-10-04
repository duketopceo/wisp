#!/usr/bin/env python3
"""Ember snapshot harness (W20, Ember U5).

Renders every window-free component in shell-plugin/components/ against
every state fixture (tests/fixtures/states/*.json, run through the real
lib/state.js reducer) on two themes, and compares the PNGs with the goldens
in tests/qml/snapshots/ inside a per-component tolerance.

    python scripts/ui/snap.py check [--only SUBSTR]   exit 1 on a diff
    python scripts/ui/snap.py update [--only SUBSTR]  rewrite goldens
    python scripts/ui/snap.py render OUTDIR           just render
    python scripts/ui/snap.py sheet OUT.png [--only]  contact sheet
    python scripts/ui/snap.py list

Renderer: `qml tests/qml/harness/Snap.qml` (Qt Quick, no compositor). The
environment is forced headless and deterministic (render_env): offscreen
platform, software scene graph, UTC, a private fontconfig that sees only the
bundled Liberation Mono, fixed theme tokens, a fixed scale factor per pass,
and motion off in the FixtureService. It never opens a Wayland or X window;
Snap.qml itself exits 2 when the platform is not offscreen.

Exit codes: 0 ok, 1 diffs or missing goldens, 2 renderer error, 3 skipped
(no qml runner or no PIL).
"""
import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests" / "qml" / "harness"
FIXTURES = ROOT / "tests" / "fixtures" / "states"
THEME_FIXTURES = ROOT / "tests" / "fixtures" / "themes"
GOLDEN = ROOT / "tests" / "qml" / "snapshots"
FONTS = ROOT / "tests" / "qml" / "fonts"

EXIT_OK, EXIT_DIFF, EXIT_ERROR, EXIT_SKIPPED = 0, 1, 2, 3

# theme name -> fixture theme directory (tokens come from its expected.json,
# the same file the token adapter tests use)
THEMES = {"dark": "vantablack", "light": "catppuccin-latte"}
SCALES = (1, 2)
VARIANT_FIXTURE = "idle"  # state a variant-mode component renders under


@dataclass(frozen=True)
class Tolerance:
    """A pixel is bad when any channel differs by more than `channel`
    (0 to 255); the image passes when at most `fraction` of its pixels are
    bad. Absorbs antialiasing and font rasterisation drift between Qt or
    freetype builds, nothing structural."""
    channel: int
    fraction: float


DEFAULT_TOLERANCE = Tolerance(channel=8, fraction=0.004)
# Per-component overrides. Text-heavy components get more room for glyph
# edge drift; the creature is soft-edged discs.
TOLERANCE = {
    "Answer": Tolerance(10, 0.012),
    "Bubble": Tolerance(10, 0.010),
    "Console": Tolerance(10, 0.010),
    "Pill": Tolerance(10, 0.010),
    "Transcript": Tolerance(10, 0.012),
    "StatusLine": Tolerance(10, 0.010),
    "AgentRow": Tolerance(10, 0.010),
    "EmptyState": Tolerance(10, 0.012),
    "Creature": Tolerance(12, 0.008),
    "Corner": Tolerance(12, 0.008),
}


def tolerance_for(component):
    return TOLERANCE.get(component, DEFAULT_TOLERANCE)


def scenes():
    return json.loads((HARNESS / "scenes.json").read_text())


def find_runner():
    p = shutil.which("qml")
    if p:
        return p
    cand = "/usr/lib/qt6/bin/qml"
    return cand if os.path.exists(cand) else None


def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


def fixture_names():
    return sorted(p.stem for p in FIXTURES.glob("*.json"))


def theme_tokens(theme):
    path = THEME_FIXTURES / THEMES[theme] / "expected.json"
    return json.loads(path.read_text())["tokens"]


def cases(only=None):
    """The full matrix, in stable order. Case id is
    <theme>/<scale>x/<Component>__<fixture or variant>."""
    out = []
    fixtures = {n: json.loads((FIXTURES / f"{n}.json").read_text())
                for n in fixture_names()}
    for comp in sorted(scenes()):
        scene = scenes()[comp]
        for theme in THEMES:
            for scale in SCALES:
                if scale == 2 and not (scene.get("scale2")
                                       and theme == "dark"):
                    continue
                if scene["mode"] == "state":
                    items = [(n, n, {}) for n in fixtures]
                else:
                    items = [(v, VARIANT_FIXTURE, props) for v, props
                             in scene["variants"].items()]
                for label, fx, extra in items:
                    raw = dict(fixtures[fx])
                    mods = raw.pop("_fixture", {})
                    props = dict(scene.get("props", {}))
                    props.update(extra)
                    out.append({
                        "id": f"{theme}/{scale}x/{comp}__{label}",
                        "component": comp, "theme": theme, "scale": scale,
                        "fixture": fx, "snapshot": raw, "mods": mods,
                        "tokens": theme_tokens(theme), "props": props,
                        "width": scene.get("width"),
                        "pad": scene.get("pad", 10),
                        "on": scene.get("on", "canvas"),
                    })
    if only:
        out = [c for c in out if only in c["id"]]
    return out


def render_env(base=None, scale=1, fonts_conf=None):
    """Headless, deterministic environment for the renderer."""
    env = dict(os.environ if base is None else base)
    for k in ("WAYLAND_DISPLAY", "DISPLAY", "XDG_SESSION_TYPE",
              "QT_QPA_PLATFORMTHEME", "QT_STYLE_OVERRIDE", "QT_QPA_FONTDIR"):
        env.pop(k, None)
    env.update({
        "QT_QPA_PLATFORM": "offscreen",
        "QT_QUICK_BACKEND": "software",
        "QT_SCALE_FACTOR": str(scale),
        "QT_ENABLE_HIGHDPI_SCALING": "1",
        "QML_XHR_ALLOW_FILE_READ": "1",
        "TZ": "UTC", "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8",
    })
    if fonts_conf:
        env["FONTCONFIG_FILE"] = str(fonts_conf)
    return env


def _write_fonts_conf(directory):
    conf = pathlib.Path(directory) / "fonts.conf"
    cache = pathlib.Path(directory) / "fc-cache"
    cache.mkdir(exist_ok=True)
    conf.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        f"<fontconfig>\n<dir>{FONTS}</dir>\n<cachedir>{cache}</cachedir>\n"
        '<match target="font"><edit name="hinting" mode="assign">'
        "<bool>false</bool></edit></match>\n"
        '<match target="font"><edit name="antialias" mode="assign">'
        "<bool>true</bool></edit></match>\n</fontconfig>\n")
    return conf


def render(out_dir, only=None, runner=None):
    """Render the matrix (or the cases whose id contains `only`) into
    out_dir/<id>.png. Returns the written paths; raises RuntimeError when
    the renderer fails."""
    runner = runner or find_runner()
    if runner is None:
        raise RuntimeError("qml runner not found")
    out_dir = pathlib.Path(out_dir)
    selected = cases(only)
    written = []
    with tempfile.TemporaryDirectory() as tmp:
        conf = _write_fonts_conf(tmp)
        for scale in SCALES:
            batch = [c for c in selected if c["scale"] == scale]
            if not batch:
                continue
            for c in batch:
                (out_dir / c["id"]).parent.mkdir(parents=True, exist_ok=True)
            manifest = pathlib.Path(tmp) / f"manifest-{scale}.json"
            manifest.write_text(json.dumps({"cases": batch}))
            p = subprocess.run(
                [runner, str(HARNESS / "Snap.qml"), "--", str(manifest),
                 str(out_dir)],
                env=render_env(scale=scale, fonts_conf=conf),
                capture_output=True, text=True, timeout=300)
            bad = [ln for ln in (p.stdout + p.stderr).splitlines()
                   if "SNAP-FAIL" in ln or "Error" in ln
                   or "is not a type" in ln]
            if p.returncode != 0 or bad:
                raise RuntimeError(
                    f"renderer exit {p.returncode}\n" + "\n".join(bad[:20])
                    + "\n" + p.stderr[-800:])
            written += [out_dir / f"{c['id']}.png" for c in batch]
    for p in written:
        if not p.exists():
            raise RuntimeError(f"renderer did not write {p}")
    return written


@dataclass
class Result:
    ok: bool
    bad_pixels: int = 0
    total: int = 0
    max_diff: int = 0
    reason: str = ""


def compare_images(a, b, tol):
    """Compare two PIL images under `tol`."""
    if a.size != b.size:
        return Result(False, reason=f"size {a.size} vs {b.size}")
    from PIL import ImageChops
    a, b = a.convert("RGBA"), b.convert("RGBA")
    diff = ImageChops.difference(a, b)
    total = a.width * a.height
    ch = diff.split()
    peak = ImageChops.lighter(ImageChops.lighter(ch[0], ch[1]),
                              ImageChops.lighter(ch[2], ch[3]))
    hist = peak.histogram()
    bad = sum(hist[tol.channel + 1:])
    worst = max((i for i, n in enumerate(hist) if n), default=0)
    ok = bad <= tol.fraction * total
    return Result(ok, bad, total, worst,
                  "" if ok else f"{bad} of {total} pixels differ by more "
                  f"than {tol.channel} (limit {tol.fraction:.2%})")


@dataclass
class Failure:
    id: str
    reason: str


@dataclass
class Report:
    total: int = 0
    failures: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    orphans: list = field(default_factory=list)

    @property
    def ok(self):
        return not (self.failures or self.missing)


def compare_dir(out_dir, only=None):
    """Compare rendered PNGs in out_dir with the goldens."""
    from PIL import Image
    out_dir = pathlib.Path(out_dir)
    report = Report()
    for c in cases(only):
        report.total += 1
        new = out_dir / f"{c['id']}.png"
        gold = GOLDEN / f"{c['id']}.png"
        if not gold.exists():
            report.missing.append(c["id"])
            continue
        r = compare_images(Image.open(gold), Image.open(new),
                           tolerance_for(c["component"]))
        if not r.ok:
            report.failures.append(Failure(c["id"], r.reason))
    ids = {c["id"] for c in cases()}
    for g in GOLDEN.rglob("*.png"):
        gid = str(g.relative_to(GOLDEN))[:-4]
        if gid not in ids:
            report.orphans.append(gid)
    return report


def check(out_dir=None, only=None, runner=None):
    """Render and compare. Failing renders are kept in out_dir."""
    if out_dir is None:
        out_dir = pathlib.Path(tempfile.mkdtemp(prefix="wisp-snap-"))
    render(out_dir, only=only, runner=runner)
    return compare_dir(out_dir, only=only)


def update(only=None, runner=None):
    with tempfile.TemporaryDirectory() as d:
        paths = render(pathlib.Path(d), only=only, runner=runner)
        for p in paths:
            rel = p.relative_to(d)
            dest = GOLDEN / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
    ids = {c["id"] for c in cases()}
    for g in list(GOLDEN.rglob("*.png")):
        if str(g.relative_to(GOLDEN))[:-4] not in ids:
            g.unlink()
    return len(paths)


def contact_sheet(src_dir, out, only=None, theme="dark", scale=1,
                  max_width=1800):
    """One band per component, tiles wrapped at max_width, label under each
    tile, for eyeballing a whole run."""
    from PIL import Image, ImageDraw
    bands = {}
    for c in cases(only):
        if c["theme"] != theme or c["scale"] != scale:
            continue
        p = pathlib.Path(src_dir) / f"{c['id']}.png"
        if p.exists():
            bands.setdefault(c["component"], []).append(
                (c["id"].split("__", 1)[1], Image.open(p).convert("RGB")))
    if not bands:
        return None
    gap, label_h = 10, 14
    placed, y = [], gap
    for comp, tiles in bands.items():
        placed.append((comp, gap, y, None))
        y += label_h + 4
        x, row_h = gap, 0
        for name, im in tiles:
            w = max(im.width, len(name) * 6) + gap
            if x + w > max_width and x > gap:
                y += row_h + label_h + gap
                x, row_h = gap, 0
            placed.append((name, x, y, im))
            x += w
            row_h = max(row_h, im.height)
        y += row_h + label_h + 2 * gap
    sheet = Image.new("RGB", (max_width, y), (52, 52, 56))
    d = ImageDraw.Draw(sheet)
    for name, x, py, im in placed:
        if im is None:
            d.text((x, py), name, fill=(255, 255, 255))
        else:
            sheet.paste(im, (x, py))
            d.text((x, py + im.height + 2), name, fill=(190, 190, 190))
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out


def main(argv=None, runner="auto"):
    ap = argparse.ArgumentParser(prog="snap.py", description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["check", "update", "render", "sheet",
                                    "list"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--only")
    ap.add_argument("--theme", default="dark")
    ap.add_argument("--keep", help="keep rendered PNGs in this directory")
    a = ap.parse_args(argv)
    if runner == "auto":
        runner = find_runner()
    if a.cmd == "list":
        for c in cases(a.only):
            print(c["id"])
        return EXIT_OK
    if runner is None or _pil() is None:
        print("snap: qml runner or PIL missing, skipped", file=sys.stderr)
        return EXIT_SKIPPED
    try:
        if a.cmd == "update":
            n = update(a.only, runner)
            print(f"snap: wrote {n} goldens")
            return EXIT_OK
        if a.cmd == "render":
            if not a.target:
                ap.error("render needs OUTDIR")
            paths = render(a.target, a.only, runner)
            print(f"snap: rendered {len(paths)} images to {a.target}")
            return EXIT_OK
        if a.cmd == "sheet":
            if not a.target:
                ap.error("sheet needs OUT.png")
            with tempfile.TemporaryDirectory() as d:
                render(d, a.only, runner)
                contact_sheet(d, a.target, a.only, theme=a.theme)
            print(f"snap: wrote {a.target}")
            return EXIT_OK
        out = pathlib.Path(a.keep) if a.keep else None
        rep = check(out, a.only, runner)
    except RuntimeError as e:
        print(f"snap: {e}", file=sys.stderr)
        return EXIT_ERROR
    for f in rep.failures:
        print(f"DIFF    {f.id}: {f.reason}")
    for m in rep.missing:
        print(f"MISSING {m}")
    for o in rep.orphans:
        print(f"ORPHAN  {o}")
    print(f"snap: {rep.total} compared, {len(rep.failures)} differ, "
          f"{len(rep.missing)} missing, {len(rep.orphans)} orphans")
    return EXIT_OK if rep.ok else EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main())
