"""One table formatter and the colour decision for every wispd command.

Colours come from the Ember tokens in wisp/theme.py (the active Omarchy
theme, or the fallback palette). Output is plain when stdout is not a tty,
when NO_COLOR is set, or when --no-color is passed.
"""
import sys

# tone name -> theme token
TONES = {"ok": "ok", "fail": "fail", "warn": "needsYou",
         "muted": "inkMuted", "accent": "ember"}


def use_color(no_color_flag: bool, tty: bool | None = None,
              env=None) -> bool:
    import os
    env = os.environ if env is None else env
    if no_color_flag or env.get("NO_COLOR"):
        return False
    if tty is None:
        tty = sys.stdout.isatty()
    return bool(tty) and env.get("TERM") != "dumb"


def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def paint(text: str, tone: str | None, tokens: dict | None) -> str:
    tok = TONES.get(tone or "")
    if not tok or not tokens or tok not in tokens:
        return text
    r, g, b = hex_rgb(tokens[tok])
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"


def table(headers, rows, tones=None, color: bool = False,
          cfg: dict | None = None, header: bool = True) -> str:
    """Aligned columns, two spaces apart. `tones[r][c]` colours one cell
    (ok|fail|warn|muted|accent) when `color`; widths ignore escapes."""
    rows = [[str(c) for c in r] for r in rows]
    cols = len(headers)
    widths = [len(h) for h in headers] if header else [0] * cols
    for r in rows:
        for i, c in enumerate(r[:cols]):
            widths[i] = max(widths[i], len(c))
    tokens = None
    if color:
        from .. import theme
        tokens = theme.load(None, cfg or {})["tokens"]

    def line(cells, tone_row=None):
        out = []
        for i, c in enumerate(cells[:cols]):
            tone = tone_row[i] if tone_row else None
            pad = " " * (widths[i] - len(c))
            last = i == cols - 1
            cell = paint(c, tone, tokens) if tokens else c
            out.append(cell if last else cell + pad)
        return "  ".join(out).rstrip()

    lines = []
    if header:
        lines.append(line(list(headers), ["muted"] * cols))
    for n, r in enumerate(rows):
        lines.append(line(r, tones[n] if tones else None))
    return "\n".join(lines)
