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
import time

from . import ipc, suggest


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
          offline: bool) -> None:
    win.erase()
    h, w = win.getmaxyx()
    row = 0

    def put(text, attr=0):
        nonlocal row
        if row < h - 1:
            win.addnstr(row, 0, text, w - 1, attr)
        row += 1

    put("WISP TUI", curses.A_BOLD)
    if offline:
        put("  daemon unreachable — run `wispd daemon`", curses.A_REVERSE)
    else:
        put(f"  status: {state.get('status', '?')}", curses.A_BOLD)
        if state.get("transcript"):
            put(f"  heard:  {state['transcript'][:w-10]}")
        if state.get("suggestion"):
            s = state["suggestion"]
            put(f"  suggest: {s.get('title', '')} — "
                f"{s.get('evidence', '')[:w-24]}")
        for s in state.get("steps", [])[-4:]:
            put(f"    → {s}")
        if state.get("result"):
            put(f"  result: {state['result'][:w-10]}")
        if state.get("error"):
            put(f"  error:  {state['error'][:w-9]}", curses.A_REVERSE)
    row += 1
    put("suggestions", curses.A_UNDERLINE)
    for s in suggestions[:4]:
        put(f"  [{s.get('status', '?'):8}] {s.get('title', '')[:w-14]}")
    if not suggestions:
        put("  (none)")
    row += 1
    put("agent tasks", curses.A_UNDERLINE)
    tasks = state.get("tasks", {})
    for name, t in list(tasks.items())[-4:]:
        put(f"  {t.get('status', '?'):9} {name[:w-14]}")
    if not tasks:
        put("  (none)")
    row += 1
    put("recent decisions", curses.A_UNDERLINE)
    for d in decisions:
        tr = (d.get("transcript") or "")[:40]
        res = (d.get("result") or "")[:w - 50]
        put(f"  {d.get('ts', '')[11:19]} {tr:<42} {res}")
    win.refresh()
    win.addnstr(h - 1, 0,
                "y automate · n snooze · v never · c first choice · "
                "l/x label · q quit", w - 1, curses.A_DIM)


def _loop(win) -> int:
    curses.curs_set(0)
    win.timeout(1500)  # refresh cadence
    while True:
        resp = _send({"cmd": "status"})
        state = resp.get("state", {}) if resp.get("ok") else {}
        offline = not resp.get("ok")
        try:
            sug = suggest.pending()
        except Exception:
            sug = []
        _draw(win, state, sug, _decisions_tail(), offline)
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
