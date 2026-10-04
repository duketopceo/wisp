"""`wispd tui` — terminal dashboard. Stdlib curses only, no deps.

Live status + transcript + act steps from the daemon, agent tasks,
pending suggestions, and the last few decisions. Keys:
  c  — pick the first pending choice (clarify/suggestion)
  y/n/v — suggestion automate / snooze / never
  l  — label last turn correct; x — label incorrect
  q  — quit
"""
import curses
import json

from . import copy as wcopy, ipc, suggest

# Colors are ANSI 0-15 only, so the Omarchy terminal palette (and a light
# terminal profile) applies. Tone names are wisp/copy.py TONES.
_TONE_ANSI = {"ember": 3, "needsYou": 11, "fail": 1, "ok": 2}
_ROLES = ("head", "label", "ember", "needsYou", "fail", "ok", "muted",
          "alert")


def _init_styles() -> dict:
    """role -> curses attribute. ANSI colors 0-15 and attributes only;
    plain attributes when the terminal has no color."""
    styles = {"head": curses.A_BOLD, "label": curses.A_UNDERLINE,
              "ember": curses.A_BOLD, "needsYou": curses.A_BOLD,
              "fail": curses.A_BOLD, "ok": curses.A_NORMAL,
              "muted": curses.A_DIM, "alert": curses.A_REVERSE}
    if not curses.has_colors():
        return styles
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = 0
    for i, (tone, color) in enumerate(_TONE_ANSI.items(), start=1):
        curses.init_pair(i, color, bg)
        styles[tone] = curses.color_pair(i) | (
            curses.A_BOLD if tone in ("needsYou", "fail") else 0)
    curses.init_pair(len(_TONE_ANSI) + 1, 1, bg)
    styles["alert"] = curses.color_pair(len(_TONE_ANSI) + 1) | curses.A_BOLD
    return styles


def _send(payload: dict) -> dict:
    try:
        return ipc.send(payload)
    except Exception:
        return {"ok": False, "error": "daemon unreachable"}


def _decisions_tail(n: int = 5) -> list:
    from . import config
    out = []
    try:
        for line in config.DECISIONS.read_text().splitlines()[-n:]:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(d)
    except OSError:
        pass
    return out


def _draw(win, state: dict, suggestions: list, decisions: list,
          offline: bool, styles: dict = None) -> None:
    st = styles or {r: 0 for r in _ROLES}
    win.erase()
    h, w = win.getmaxyx()
    row = 0

    def put(text, attr=0):
        nonlocal row
        if row < h - 1:
            win.addnstr(row, 0, text, w - 1, attr)
        row += 1

    status = "offline" if offline else (state.get("status") or "offline")
    word = wcopy.status_word(status)
    tone = wcopy.status_tone(status)
    put(f"wisp  {word}", st.get(tone, st["head"]))
    if offline:
        put("  daemon unreachable. run `wispd daemon`", st["alert"])
    else:
        if state.get("guide"):
            g = state["guide"]
            put(f"  ghost:  {g.get('mode','guide')} @"
                f"({g.get('x')},{g.get('y')}) {g.get('label','')[:w-20]}")
        if state.get("transcript"):
            put(f"  heard:  {state['transcript'][:w-10]}")
        if state.get("suggestion"):
            s = state["suggestion"]
            put(f"  idea:   {s.get('title', '')}: "
                f"{s.get('evidence', '')[:w-24]}")
        for s in state.get("steps", [])[-4:]:
            put(f"    - {wcopy.translate_result(s)['text'][:w-8]}")
        if state.get("result"):
            put("  result: "
                f"{wcopy.translate_result(state['result'])['text'][:w-10]}")
        if state.get("error"):
            put(f"  error:  {state['error'][:w-9]}", st["fail"])
    row += 1
    put("suggestions", st["label"])
    for s in suggestions[:4]:
        put(f"  [{s.get('status', '?'):8}] {s.get('title', '')[:w-14]}")
    if not suggestions:
        put("  (none)", st["muted"])
    row += 1
    put("agent tasks", st["label"])
    tasks = state.get("tasks", {})
    for name, t in list(tasks.items())[-4:]:
        put(f"  {t.get('status', '?'):9} {name[:w-14]}")
    if not tasks:
        put("  (none)", st["muted"])
    row += 1
    put("telemetry (24h)", st["label"])
    try:
        from . import telemetry as _tele
        for line in _tele.text(24).splitlines()[0:4]:
            put(f"  {line.strip()[:w-4]}")
    except Exception:
        pass
    row += 1
    put("skills", st["label"])
    try:
        from . import skills as _sk
        idx = _sk.index()
        put(f"  {len(idx)} installed "
            f"(luke-agents + seeds + learned)")
        for s in idx[:6]:
            put(f"    {'tool' if s.get('tool') else '    '} "
                f"{s['name'][:w-14]}")
        if len(idx) > 6:
            put(f"    ... {len(idx) - 6} more. `wispd skills`")
    except Exception:
        put("  (unavailable)", st["muted"])
    row += 1
    put("recent decisions", st["label"])
    for d in decisions:
        tr = (d.get("transcript") or "")[:40]
        res = (d.get("result") or "")[:w - 50]
        put(f"  {d.get('ts', '')[11:19]} {tr:<42} "
            f"{wcopy.translate_result(res)['text']}")
    win.refresh()
    win.addnstr(h - 1, 0,
                "y automate, n snooze, v never, c first choice, "
                "l/x label, q quit", w - 1, st["muted"])


def _loop(win) -> int:
    curses.curs_set(0)
    styles = _init_styles()
    win.timeout(1500)  # refresh cadence
    while True:
        resp = _send({"cmd": "status"})
        state = resp.get("state", {}) if resp.get("ok") else {}
        offline = not resp.get("ok")
        try:
            sug = suggest.pending()
        except Exception:
            sug = []
        _draw(win, state, sug, _decisions_tail(), offline, styles)
        ch = win.getch()
        if ch in (ord("q"), 27):
            return 0
        if ch == ord("c") and state.get("choices"):
            _send({"cmd": "choice", "pick": state["choices"][0]})
        if ch in (ord("y"), ord("n"), ord("v")):
            pick = {ord("y"): "suggestion:automate",
                    ord("n"): "suggestion:not now",
                    ord("v"): "suggestion:never"}[ch]
            _send({"cmd": "choice", "pick": pick})
        if ch in (ord("l"), ord("x")):
            _send({"cmd": "label",
                   "label": "correct" if ch == ord("l") else "incorrect"})


def main() -> int:
    try:
        return curses.wrapper(_loop)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
