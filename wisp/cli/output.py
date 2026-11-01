"""One output module for every wispd command and script in the repo.

Rules (docs/design/TERMINAL.md):
  * Color is ANSI-16 by default so the terminal's own theme applies. The
    five Wisp tones are the whole vocabulary: ember, needsYou, fail, ok,
    muted. Truecolor from the active Omarchy theme tokens is used only when
    COLORTERM says the terminal has it.
  * Plain when the stream is not a tty, NO_COLOR is set, TERM=dumb, or
    --no-color is passed. FORCE_COLOR turns color on.
  * Status is a word first. The one decoration is the guiding light: a
    single ● marks the current step and everything else stays quiet. Glyphs
    (● ○ › · … and the rules) appear only on a UTF-8 tty; ASCII otherwise.
  * Widths are display widths, never len(), and nothing wraps inside a
    table cell: the flexible column is cut with an ellipsis.
"""
import os
import re
import sys
import unicodedata

# tone name -> theme token (truecolor path)
TONES = {"ok": "ok", "fail": "fail", "warn": "needsYou",
         "muted": "inkMuted", "accent": "ember"}

# tone name -> SGR parameters (ANSI-16 path). Same mapping as the TUI
# (wisp/tui.py _TONE_ANSI): ember yellow, needsYou bright yellow.
ANSI16 = {"ok": "32", "fail": "31", "warn": "93", "muted": "2",
          "accent": "33"}

# tone -> status word. The word is always printed; color and glyph are extra.
WORDS = {"ok": "ok", "warn": "warn", "fail": "fail", "muted": "skip"}

# name -> (glyph, ascii fallback). The allow-list: no emoji, no check marks.
GLYPHS = {"now": ("\u25cf", "*"), "todo": ("\u25cb", "o"),
          "next": ("\u203a", ">"), "sep": ("\u00b7", ","),
          "ellipsis": ("\u2026", "..."), "rule": ("\u2500", "-")}

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


# -- environment decisions --------------------------------------------------

def use_color(no_color_flag: bool, tty: bool | None = None,
              env=None) -> bool:
    env = os.environ if env is None else env
    if no_color_flag or env.get("NO_COLOR"):
        return False
    force = env.get("FORCE_COLOR") or env.get("CLICOLOR_FORCE")
    if force and force != "0":
        return True
    if tty is None:
        tty = sys.stdout.isatty()
    return bool(tty) and env.get("TERM") != "dumb"


def truecolor(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get("COLORTERM", "").lower() in ("truecolor", "24bit")


def use_glyphs(tty: bool | None = None, env=None) -> bool:
    """Glyphs only on a UTF-8 tty that is not TERM=dumb."""
    env = os.environ if env is None else env
    if tty is None:
        tty = sys.stdout.isatty()
    if not tty or env.get("TERM") == "dumb":
        return False
    loc = (env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG")
           or "").lower()
    return "utf-8" in loc or "utf8" in loc


def term_width(env=None, default: int = 80, lo: int = 40,
               hi: int = 200) -> int:
    """COLUMNS, then the tty size, then `default`; clamped to lo..hi."""
    env = os.environ if env is None else env
    n = 0
    try:
        n = int(env.get("COLUMNS", "") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        try:
            n = os.get_terminal_size(sys.stdout.fileno()).columns \
                if sys.stdout.isatty() else 0
        except (OSError, ValueError):
            n = 0
    if n <= 0:
        n = default
    return max(lo, min(hi, n))


# -- width helpers ----------------------------------------------------------

def strip_ansi(s: str) -> str:
    return _ANSI.sub("", s)


def display_width(s: str) -> int:
    """Columns the text takes: escapes are free, wide characters are 2,
    combining marks are 0."""
    w = 0
    for ch in strip_ansi(str(s)):
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(s: str, n: int, right: bool = False) -> str:
    gap = " " * max(0, n - display_width(s))
    return gap + s if right else s + gap


def truncate(s: str, n: int, glyphs: bool = False) -> str:
    """Cut plain text to `n` display columns with an ellipsis."""
    s = str(s)
    if display_width(s) <= n:
        return s
    mark = GLYPHS["ellipsis"][0 if glyphs else 1]
    room = n - display_width(mark)
    if room <= 0:
        return mark[:max(n, 0)]
    out, w = [], 0
    for ch in s:
        cw = display_width(ch)
        if w + cw > room:
            break
        out.append(ch)
        w += cw
    return "".join(out) + mark


def glyph(name: str, on: bool) -> str:
    return GLYPHS[name][0 if on else 1]


def _chunks(word: str, width: int) -> list:
    """Split one word into pieces of at most `width` display columns."""
    out, cur, w = [], "", 0
    for ch in word:
        cw = display_width(ch)
        if cur and w + cw > width:
            out.append(cur)
            cur, w = "", 0
        cur += ch
        w += cw
    return out + [cur] if cur else out


def wrap(text: str, width: int, indent: str = "", first: str = "") -> list:
    """Word-wrap prose to `width` display columns with a hanging indent.
    A word longer than a line is split so no line exceeds `width`."""
    lines, cur = [], first or indent
    for word in str(text).split():
        room = max(1, width - display_width(indent))
        pieces = [word] if display_width(cur + word) <= width \
            else _chunks(word, room)
        for piece in pieces:
            if display_width(cur.strip()) and \
                    display_width(cur + piece) > width:
                lines.append(cur.rstrip())
                cur = indent
            if display_width(cur + piece) > width and not cur.strip():
                # first line prefix plus an unsplit word: split to fit it
                fit = max(1, width - display_width(cur))
                head = _chunks(piece, fit)
                lines.append((cur + head[0]).rstrip())
                cur = indent
                piece = "".join(head[1:])
                if not piece:
                    continue
            cur += piece + " "
    if cur.strip():
        lines.append(cur.rstrip())
    return lines or [first.rstrip()]


# -- color ------------------------------------------------------------------

def hex_rgb(h: str) -> tuple:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def paint(text: str, tone: str | None, tokens: dict | None = None,
          bold: bool = False) -> str:
    """Color `text`. With theme `tokens` -> truecolor; without -> ANSI-16.
    Unknown tone -> plain text (bold still applies)."""
    if tone not in ANSI16:
        return f"\x1b[1m{text}\x1b[0m" if bold else text
    if tokens:
        tok = TONES.get(tone)
        if tok in tokens:
            r, g, b = hex_rgb(tokens[tok])
            sgr = f"38;2;{r};{g};{b}"
        else:
            sgr = ANSI16[tone]
    else:
        sgr = ANSI16[tone]
    return f"\x1b[{'1;' if bold else ''}{sgr}m{text}\x1b[0m"


def _tokens(color: bool, cfg: dict | None, env=None):
    if not (color and truecolor(env)):
        return None
    from .. import theme
    return theme.load(None, cfg or {})["tokens"]


def heading(text: str, color: bool = False) -> str:
    return f"\x1b[1m{text}\x1b[0m" if color else text


# -- layout -----------------------------------------------------------------

def _fit(widths: list, width: int | None, flex: int | None, gap: int) -> list:
    """Shrink columns so the row fits `width`. The flex column gives first,
    then the widest others; no column drops below 6 (or its header)."""
    if width is None:
        return widths
    w = list(widths)
    floor = [min(x, 6) for x in w]
    over = sum(w) + gap * (len(w) - 1) - width
    order = ([flex] if flex is not None else []) + sorted(
        (i for i in range(len(w)) if i != flex), key=lambda i: -w[i])
    for i in order:
        if over <= 0:
            break
        cut = min(over, w[i] - floor[i])
        w[i] -= cut
        over -= cut
    for i in order:  # floors alone cannot fit: squeeze to one column each
        if over <= 0:
            break
        cut = min(over, max(0, w[i] - 1))
        w[i] -= cut
        over -= cut
    return w


def table(headers, rows, tones=None, color: bool = False,
          cfg: dict | None = None, header: bool = True, *,
          width: int | None = None, flex: int | None = None,
          align: str = "", glyphs: bool = False, gap: int = 2,
          env=None) -> str:
    """Aligned columns. `tones[r][c]` colors one cell (ok|fail|warn|muted|
    accent) when `color`. Pass `width` to fit a terminal: the `flex` column
    (default: the widest) is truncated with an ellipsis, so no cell wraps.
    `align` is one letter per column, l or r (default l)."""
    rows = [[str(c) for c in r] for r in rows]
    cols = len(headers)
    widths = [display_width(h) for h in headers] if header else [0] * cols
    for r in rows:
        for i, c in enumerate(r[:cols]):
            widths[i] = max(widths[i], display_width(c))
    if flex is None and width is not None and widths:
        flex = max(range(cols), key=lambda i: widths[i])
    widths = _fit(widths, width, flex, gap)
    tokens = _tokens(color, cfg, env)

    def line(cells, tone_row=None):
        out = []
        for i, c in enumerate(cells[:cols]):
            c = truncate(c, widths[i], glyphs)
            tone = tone_row[i] if tone_row else None
            right = i < len(align) and align[i] == "r"
            plain_pad = pad(c, widths[i], right)
            if color and tone:
                painted = paint(c, tone, tokens)
                cell = painted + plain_pad[len(c):] if not right \
                    else plain_pad[:len(plain_pad) - len(c)] + painted
            else:
                cell = plain_pad
            out.append(cell)
        return (" " * gap).join(out).rstrip()

    lines = []
    if header:
        lines.append(line(list(headers), ["muted"] * cols))
    for n, r in enumerate(rows):
        lines.append(line(r, tones[n] if tones else None))
    return "\n".join(lines)


def kv(pairs, color: bool = False, width: int | None = None,
       indent: int = 0, glyphs: bool = False, tones=None) -> str:
    """Two columns for one record: dim keys, aligned values, values cut to
    fit `width`. `tones` maps key -> tone for the value."""
    pairs = [(str(k), str(v)) for k, v in pairs]
    if not pairs:
        return ""
    kw = max(display_width(k) for k, _ in pairs)
    if width is not None:  # a long key may not eat the whole line
        kw = min(kw, max(1, (width - indent) // 2))
    lines = []
    for k, v in pairs:
        room = None if width is None else max(0, width - indent - kw - 2)
        if room is not None:
            v = truncate(v, room, glyphs)
        key = pad(truncate(k, kw, glyphs), kw)
        if color:
            key = paint(key, "muted")
            if tones and k in tones:
                v = paint(v, tones[k])
        lines.append(" " * indent + key + "  " + v)
    return "\n".join(lines)


def section(name: str, count: int | None = None, color: bool = False) -> str:
    text = name if count is None else f"{name} ({count})"
    return heading(text, color)


def summary(title: str, counts, width: int, color: bool = False,
            glyphs: bool = False) -> str:
    """Title left, counts right on one line. `counts` is [(n, word, tone)];
    zero counts are skipped; a count of None prints the text as is."""
    sep = f" {glyph('sep', glyphs)} " if glyphs else ", "
    parts = [(w if n is None else f"{n} {w}", t) for n, w, t in counts
             if n is None or n]
    right = sep.join(p for p, _ in parts)
    if color:
        right = sep.join(paint(p, t if t != "ok" else "muted")
                         for p, t in parts)
    gap = max(2, width - display_width(title) - display_width(right))
    return heading(title, color) + " " * gap + right


def mark(tone: str, color: bool = False) -> str:
    """The status word for a tone, colored when `color`."""
    word = WORDS.get(tone, tone)
    return paint(word, tone) if color else word


def step_marker(state: str, glyphs: bool = False, color: bool = False) -> str:
    """The guiding light. `now` is the one lit step (ember, bold); `todo`
    is a quiet ring; `done` and `skip` are plain muted words so only the
    current step draws the eye."""
    if state == "now":
        g = glyph("now", glyphs)
        return paint(g, "accent", bold=True) if color else g
    if state == "todo":
        g = glyph("todo", glyphs)
        return paint(g, "muted") if color else g
    word = {"done": "done", "skip": "skip", "na": "n/a"}.get(state, state)
    return paint(word, "muted") if color else word


def banner(version: str = "", glyphs: bool = False,
           color: bool = False) -> str:
    """The wordmark: one lit dot and the name, then a muted line. Shown only
    on bare `wispd`, `onboard`, install and --version, on a tty."""
    dot = step_marker("now", glyphs, color)
    name = heading("wisp", color)
    tag = "voice agent for Omarchy" + (f"  {version}" if version else "")
    if color:
        tag = paint(tag, "muted")
    return f"{dot} {name}\n  {tag}"
