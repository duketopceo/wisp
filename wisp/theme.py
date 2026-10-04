"""Wisp theme tokens: the Omarchy theme -> Wisp token adapter.

DESIGN-v2 sections 5.1 and 5.2 are the spec. `load()` reads the active
Omarchy theme (`colors.toml`, plus `shell.toml` when present) and derives
the Wisp token set: chrome colors straight from the theme, `ember` (the
creature color) derived from the theme's accent, and contrast-corrected
`inkMuted`, state colors and `emberHalo`.

This module is the reference implementation. `shell-plugin/lib/tokens.js`
ports the same pure functions for live theme switches inside the shell,
and both are tested against tests/fixtures/themes/*/expected.json, so any
change here must be mirrored there.

The two Tokyo Night palettes (DARK, LIGHT) are only the fallback used when
no Omarchy theme exists (generic Linux, macOS). `emit()` still writes the
legacy theme.json the current QML surfaces read.
"""
import json
import math
import pathlib
import re

from . import config

FILE = config.DATA_DIR / "theme.json"
CSS_FILE = config.DATA_DIR / "theme.css"
OMARCHY_THEME = (pathlib.Path.home() / ".local" / "state" / "omarchy"
                 / "current" / "theme")

DARK = {
    "canvas": "#1a1b26", "surface": "#283457", "hairline": "#3b4261",
    "ink": "#c0caf5", "muted": "#9aa5ce", "faint": "#565f89",
    "accent": "#7aa2f7", "accentAlt": "#bb9af7", "guide": "#7dcfff",
    "ok": "#9ece6a", "warn": "#e0af68", "err": "#e05555",
}

LIGHT = {
    "canvas": "#f5f6fa", "surface": "#e2e6f2", "hairline": "#c3c9dd",
    "ink": "#1f2335", "muted": "#4c5578", "faint": "#8a91ad",
    "accent": "#2e7de9", "accentAlt": "#9854f1", "guide": "#007197",
    "ok": "#33701f", "warn": "#8f5e15", "err": "#c43a3a",
}

THEMES = {"dark": DARK, "light": LIGHT}

# Token names, in DESIGN-v2 5.1 table order plus the 5.2 ember variants.
TOKENS = ("canvas", "raised", "keyline", "keylineStrong", "ink", "inkMuted",
          "accent", "ember", "emberCore", "emberWick", "emberHalo",
          "needsYou", "fail", "ok", "selection")

# Contrast floors (DESIGN-v2 section 7 / plan R15): text 4.5, state-carrying
# non-text 3.0. Each row is (foreground token, background token, minimum).
CHECKS = (
    ("ink", "canvas", 4.5),
    ("inkMuted", "canvas", 4.5),
    ("ember", "canvas", 3.0),
    ("emberHalo", "ember", 3.0),
    ("needsYou", "canvas", 3.0),
    ("fail", "canvas", 3.0),
    ("ok", "canvas", 3.0),
)

# Omarchy Color.qml defaults, used when colors.toml omits a base key.
_COLOR_DEFAULTS = {"foreground": "#cacccc", "background": "#101315",
                   "accent": "#cacccc", "urgent": "#a55555"}
_NORMAL_BORDER_ALPHA = 0.4     # Style.normalBorderAlpha default
_RAISED_ALPHA = 0.06
_SELECTION_ALPHA = 0.35
_EMBER_CHROMA_FLOOR = 0.05
_EMBER_URGENT_DE = 10.0        # CIE76 deltaE
_EMBER_L = {"dark": (0.70, 0.85), "light": (0.45, 0.60)}
_MIX_STEP = 0.05               # inkMuted mix-toward-ink step
_L_STEP = 0.01                 # state-color OKLCH lightness step


# --- color math (sRGB <-> OKLab, WCAG contrast) --------------------------

def _rgb(hexs: str) -> tuple:
    h = hexs.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(rgb) -> str:
    return "#" + "".join(
        f"{max(0, min(255, int(math.floor(c * 255 + 0.5)))):02x}"
        for c in rgb)


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def oklab(hexs: str) -> tuple:
    r, g, b = (_lin(c) for c in _rgb(hexs))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(x) ** (1 / 3), x) for x in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def _from_oklab(L: float, a: float, b: float) -> str:
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return _hex((_gam(r), _gam(g), _gam(bb)))


def oklch(hexs: str) -> tuple:
    """(L 0..1, C, h degrees 0..360)."""
    L, a, b = oklab(hexs)
    return L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def with_lightness(hexs: str, L: float) -> str:
    """Same OKLab hue and chroma at lightness L (sRGB-clipped)."""
    _, a, b = oklab(hexs)
    return _from_oklab(max(0.0, min(1.0, L)), a, b)


def cielab(hexs: str) -> tuple:
    """CIE L*a*b* (D65)."""
    r, g, b = (_lin(c) for c in _rgb(hexs))
    xyz = ((0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047,
           (0.2126729 * r + 0.7151522 * g + 0.0721750 * b),
           (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883)
    f = [t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
         for t in xyz]
    return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])


def delta_e(x: str, y: str) -> float:
    """CIE76 deltaE (Euclidean distance in CIE L*a*b*)."""
    return math.dist(cielab(x), cielab(y))


def luminance(hexs: str) -> float:
    r, g, b = (_lin(c) for c in _rgb(hexs))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(x: str, y: str) -> float:
    a, b = sorted((luminance(x), luminance(y)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def mix(x: str, y: str, t: float) -> str:
    """Linear sRGB-space blend: t=0 is x, t=1 is y (8-bit rounded)."""
    return _hex(tuple(p + (q - p) * t for p, q in zip(_rgb(x), _rgb(y))))


def over(fg: str, alpha: float, bg: str) -> str:
    """fg at `alpha` composited over opaque bg, as Qt/CSS would draw it."""
    return mix(bg, fg, alpha)


# --- parsing --------------------------------------------------------------

_KV = re.compile(r"""^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#?[^"'#\s]+)""")
_HEX6 = re.compile(r"^#[0-9a-fA-F]{6}$")


def parse_colors(text: str) -> dict:
    """colors.toml -> {key: '#rrggbb' | 'light'/'dark'}. Keys lowercased."""
    out = {}
    for line in text.splitlines():
        m = _KV.match(line)
        if not m:
            continue
        k, v = m.group(1).lower(), m.group(2)
        if _HEX6.match(v):
            out[k] = v.lower()
        elif k == "mode" and v.lower() in ("light", "dark"):
            out[k] = v.lower()
    return out


def parse_shell(text: str) -> dict:
    """shell.toml -> flat {'section.key': 'raw string'} (Color.parseShell)."""
    out, section = {}, ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[([A-Za-z0-9_-]+)\]\s*(#.*)?$", line)
        if m:
            section = m.group(1)
            continue
        m = re.match(r"""^([A-Za-z0-9_-]+)\s*=\s*["']?([^"'#]+?)["']?\s*"""
                     r"(#.*)?$", line)
        if m and section:
            out[f"{section}.{m.group(1)}"] = m.group(2).strip()
    return out


def _shell_hex(shell, key: str, seen=()):
    """Resolve a shell.toml color: hex, or a reference to another key
    (e.g. popups.border = "hyprland.active-border"); gradients use their
    first color stop, like Color.flatColor()."""
    v = (shell or {}).get(key)
    if not v or key in seen:
        return None
    tok = next((p for p in v.split() if not re.match(r"^-?[\d.]+deg$", p)),
               "")
    if _HEX6.match(tok):
        return tok.lower()
    if tok in shell:
        return _shell_hex(shell, tok, seen + (key,))
    return None


# --- derivation -----------------------------------------------------------

def _base(colors: dict) -> dict:
    """Mirror Omarchy Color.loadColors(): named keys, then colorN aliases."""
    c = colors
    fg = c.get("foreground") or c.get("color7") or _COLOR_DEFAULTS["foreground"]
    return {
        "foreground": fg,
        "background": (c.get("background") or c.get("color0")
                       or _COLOR_DEFAULTS["background"]),
        "accent": (c.get("accent") or c.get("color4")
                   or _COLOR_DEFAULTS["accent"]),
        "urgent": (c.get("red") or c.get("color1")
                   or _COLOR_DEFAULTS["urgent"]),
        "muted": c.get("muted") or c.get("color8") or fg,
    }


def ember_for(colors: dict, mode: str) -> str:
    """DESIGN-v2 5.2: the theme's own fire, never an error color."""
    b = _base(colors)
    cand = b["accent"]
    if oklch(cand)[1] < _EMBER_CHROMA_FLOOR:
        cand = colors.get("orange") or colors.get("yellow") or cand
    if delta_e(cand, b["urgent"]) < _EMBER_URGENT_DE:
        for k in ("orange", "yellow"):
            alt = colors.get(k)
            if alt and delta_e(alt, b["urgent"]) >= _EMBER_URGENT_DE:
                cand = alt
                break
    lo, hi = _EMBER_L[mode]
    L = oklch(cand)[0]
    if lo <= L <= hi:
        return cand
    return with_lightness(cand, min(hi, max(lo, L)))


def _mix_until(color: str, toward: str, bg: str, floor: float) -> str:
    """Mix `color` toward `toward` in _MIX_STEP steps until it hits `floor`
    contrast on `bg` (or becomes `toward`)."""
    steps = int(round(1 / _MIX_STEP))
    for i in range(steps + 1):
        c = mix(color, toward, i / steps)
        if contrast(c, bg) >= floor:
            return c
    return toward


def _lift_until(color: str, bg: str, floor: float) -> str:
    """Move `color`'s OKLCH lightness away from `bg` in _L_STEP steps until
    it hits `floor` contrast, keeping hue and chroma (state colors keep
    their identity: yellow stays yellow, only darker or lighter)."""
    if contrast(color, bg) >= floor:
        return color
    L = oklch(color)[0]
    sign = -1 if luminance(bg) > 0.18 else 1
    steps = int(round(1 / _L_STEP))
    c = color
    for i in range(1, steps + 1):
        c = with_lightness(color, L + sign * i * _L_STEP)
        if contrast(c, bg) >= floor:
            return c
    return c


def derive(colors: dict, shell=None, source: str = "omarchy") -> dict:
    """colors.toml (+ shell.toml) values -> {source, mode, tokens}."""
    b = _base(colors)
    canvas = _shell_hex(shell, "popups.background") or b["background"]
    mode = colors.get("mode") or (
        "light" if luminance(canvas) > 0.18 else "dark")
    ink, accent = b["foreground"], b["accent"]
    border_alpha = _NORMAL_BORDER_ALPHA
    try:
        border_alpha = max(0.0, min(1.0, float(
            (shell or {}).get("controls.normal-border-alpha", border_alpha))))
    except ValueError:
        pass
    ember = ember_for(colors, mode)
    eL = oklch(ember)[0]
    halo = max((b["background"], ink), key=lambda c: contrast(c, ember))
    tokens = {
        "canvas": canvas,
        "raised": (colors.get("lighter_background")
                   or over(ink, _RAISED_ALPHA, canvas)),
        "keyline": over(ink, border_alpha, canvas),
        "keylineStrong": _shell_hex(shell, "popups.border") or accent,
        "ink": ink,
        "inkMuted": _mix_until(b["muted"], ink, canvas, 4.5),
        "accent": accent,
        "ember": ember,
        "emberCore": with_lightness(ember, eL + 0.1),
        "emberWick": with_lightness(ember, eL - 0.1),
        "emberHalo": halo,
        "needsYou": _lift_until(colors.get("yellow") or b["urgent"],
                                canvas, 3.0),
        "fail": _lift_until(b["urgent"], canvas, 3.0),
        "ok": _lift_until(colors.get("green") or accent, canvas, 3.0),
        "selection": (colors.get("selection")
                      or over(accent, _SELECTION_ALPHA, canvas)),
    }
    return {"source": source, "mode": mode, "tokens": tokens}


def _fallback_colors(name: str) -> dict:
    p = THEMES[name]
    return {"mode": name, "background": p["canvas"], "foreground": p["ink"],
            "accent": p["accent"], "muted": p["muted"], "red": p["err"],
            "yellow": p["warn"], "green": p["ok"],
            "lighter_background": p["surface"]}


def load(theme_dir=None, cfg=None) -> dict:
    """Tokens for the active Omarchy theme, or the fallback palette
    (`[ui] theme`, dark by default) when no colors.toml exists."""
    d = pathlib.Path(theme_dir) if theme_dir else OMARCHY_THEME
    try:
        colors = parse_colors((d / "colors.toml").read_text())
    except OSError:
        colors = {}
    if not colors:
        return derive(_fallback_colors(current(cfg)), source="fallback")
    try:
        shell = parse_shell((d / "shell.toml").read_text())
    except OSError:
        shell = None
    return derive(colors, shell)


def check(result: dict) -> list:
    """Contrast rows for CHECKS: [{pair, fg, bg, ratio, min, ok}]."""
    t = result["tokens"]
    rows = []
    for fg, bg, floor in CHECKS:
        r = contrast(t[fg], t[bg])
        rows.append({"pair": f"{fg}/{bg}", "fg": t[fg], "bg": t[bg],
                     "ratio": round(r, 2), "min": floor, "ok": r >= floor})
    return rows


def _css_name(token: str) -> str:
    return "--wisp-" + re.sub(r"([A-Z])", r"-\1", token).lower()


def css(result: dict) -> str:
    """theme.css for the arena page: one custom property per token."""
    lines = [f"/* Wisp tokens ({result['source']}, {result['mode']}); "
             "generated by `wispd theme --css`, do not edit. */",
             ":root {", f"  color-scheme: {result['mode']};"]
    lines += [f"  {_css_name(k)}: {result['tokens'][k]};" for k in TOKENS]
    lines.append("}")
    return "\n".join(lines) + "\n"


def write_css(result: dict, path=None) -> pathlib.Path:
    path = pathlib.Path(path) if path else CSS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(css(result))
    tmp.replace(path)
    return path


# --- legacy theme.json (read by the current QML surfaces until U3) --------

def current(cfg: dict) -> str:
    name = (cfg or {}).get("ui", {}).get("theme", "dark")
    return name if name in THEMES else "dark"


def tokens(cfg: dict) -> dict:
    return dict(THEMES[current(cfg)])


def emit(cfg: dict) -> str:
    """Write theme.json atomically. Returns the resolved theme name."""
    name = current(cfg)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"name": name, "tokens": tokens(cfg)}))
    tmp.replace(FILE)
    return name
