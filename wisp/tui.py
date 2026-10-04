"""`wispd tui` - terminal dashboard. Stdlib curses only, no deps.

Views (keys 1 to 5, or tab): status, health, spend, audit, binds. They show
the same data as the management app (shells/debug/shell.qml), from the same
JSON: state `health` and `spend` over the push stream, `wispd cua status
--json`, `wispd spend --json`, `wispd binds --json` and `wispd health --json`
(when the daemon is not running), and the cua audit log. The model builders
below (sections, spend_view, cua_view, ...) mirror shell-plugin/lib/health.js
and lib/manage.js field for field; tests/test_manage_parity.py runs both over
one fixture and compares them.

No polling: state arrives on the subscription (reconnect backoff only), the
one-shot reads run when a view opens or on `r`, and the loop sleeps in
select() until a key or an update arrives. Keys:
  1-5, tab  - switch view          r - reload the view's data
  c  - pick the first pending choice (clarify/suggestion)
  y/n/v - suggestion automate / snooze / never
  l  - label last turn correct; x - label incorrect
  q  - quit
"""
import curses
import json
import math
import os
import pathlib
import select
import subprocess
import sys
import threading
import time

from . import copy as wcopy, ipc, suggest

VIEWS = ("status", "health", "spend", "audit", "binds")
ROOT = pathlib.Path(__file__).resolve().parent.parent

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
    _footer(win, st)
    win.refresh()


# -- models: mirrors of shell-plugin/lib/health.js and lib/manage.js --------
# Same field names (camelCase) on purpose, so one fixture checks both.

_MISSING = object()
_SPECIAL = ("cua", "spend", "stt")


def _num(v):
    """JavaScript Number(v) for a JSON value (NaN when it is not a number)."""
    if v is _MISSING or isinstance(v, (dict, list)):
        return math.nan
    if v is None:
        return 0.0
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return math.nan
    return float(v)


def _usd(v) -> str:
    n = _num(v)
    return f"${n:.2f}" if math.isfinite(n) else ""


def _opt_usd(d, key) -> str:
    v = d.get(key)
    return "" if v is None else _usd(v)


def sections(health) -> dict:
    """State `health` rows -> endpoints, stt, cua, spend, errors."""
    out = {"endpoints": [], "stt": None, "cua": None, "spend": None,
           "errors": []}
    h = health if isinstance(health, dict) else {}
    for name in sorted(h):
        row = h[name]
        if not isinstance(row, dict):
            continue
        lat = row.get("latency_ms")
        r = {"name": name, "ok": row.get("ok") is True,
             "code": row.get("code"), "since": row.get("since") or "",
             "latencyMs": lat if isinstance(lat, (int, float))
             and not isinstance(lat, bool) else None}
        if name in _SPECIAL:
            out[name] = r
        else:
            out["endpoints"].append(r)
        if not r["ok"]:
            out["errors"].append(r)
    return out


def spend_view(spend) -> dict:
    s = spend if isinstance(spend, dict) else {}
    cap = _num(s["cap_usd"]) if s.get("cap_usd") is not None else math.nan
    today = _num(s.get("today_usd", _MISSING))
    ratio = 0.0
    if math.isfinite(cap) and cap > 0 and math.isfinite(today):
        ratio = max(0.0, min(1.0, today / cap))
    return {"has": "today_usd" in s,
            "today": _usd(s.get("today_usd", _MISSING)),
            "month": _usd(s.get("month_usd", _MISSING)),
            "cap": _usd(cap) if math.isfinite(cap) else "",
            "monthCap": _opt_usd(s, "monthly_cap_usd"),
            "blocked": s.get("blocked") is True, "ratio": ratio}


def cua_view(c):
    """`wispd cua status --json` data -> view; None when not loaded."""
    if not isinstance(c, dict) or not c.get("state"):
        return None
    return {"state": str(c["state"]), "fix": c.get("fix") or "",
            "kill": c.get("kill") is True,
            "dryRun": c.get("dry_run") is True,
            "version": c.get("version") or "", "live": c.get("live") is True,
            "mode": c.get("mode") or ""}


def model_rows(models) -> list:
    out = []
    for m in models if isinstance(models, list) else []:
        if isinstance(m, dict):
            calls = _num(m.get("calls", _MISSING))
            out.append({"model": str(m.get("model") or ""),
                        "calls": int(calls) if math.isfinite(calls)
                        and calls else 0, "usd": _usd(m.get("usd", _MISSING))})
    return out


def spend_models(models) -> list:
    out = []
    for m in models if isinstance(models, list) else []:
        if isinstance(m, dict):
            calls = _num(m.get("calls", _MISSING))
            tin = _num(m.get("in", _MISSING))
            tout = _num(m.get("out", _MISSING))
            out.append({
                "model": str(m.get("model") or ""),
                "calls": int(calls) if math.isfinite(calls) and calls else 0,
                "usd": _usd(m.get("usd", _MISSING)),
                "tokens": f"{int(tin) if math.isfinite(tin) else 0}/"
                          f"{int(tout) if math.isfinite(tout) else 0}"})
    return out


def health_from_endpoints(data) -> dict:
    """`wispd health --json` data -> the state `health` shape."""
    out = {}
    for e in (data or {}).get("endpoints", []) if isinstance(data, dict) \
            else []:
        if isinstance(e, dict) and e.get("name"):
            out[e["name"]] = {"ok": bool(e.get("ok")),
                              "code": e.get("code"),
                              "latency_ms": e.get("latency_ms")}
    return out


def clock(ts) -> str:
    n = _num(ts)
    if not math.isfinite(n) or n <= 0:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(n))


_DECISION_TONE = {"allow": "ok", "dry_run": "muted", "cancelled": "needsYou",
                  "deny": "fail"}


def decision_tone(d: str) -> str:
    return _DECISION_TONE.get(d, "muted")


def audit_rows(text: str, limit: int = 50) -> list:
    """cua.jsonl text -> rows, newest first. Reads decision, app, tool,
    result verb and duration only; the log holds no typed text."""
    out = []
    for line in reversed(str(text or "").split("\n")):
        if len(out) >= (limit if limit > 0 else 50):
            break
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(r, dict) or not isinstance(r.get("tool"), str):
            continue
        ms = _num(r.get("ms", _MISSING))
        out.append({
            "time": clock(r.get("ts", _MISSING)), "tool": r["tool"],
            "app": r["app"] if isinstance(r.get("app"), str) else "",
            "decision": r["decision"] if isinstance(r.get("decision"), str)
            else "",
            "result": r["result"] if isinstance(r.get("result"), str)
            else "",
            "ms": int(round(ms)) if math.isfinite(ms) and ms >= 0 else 0,
            "dryRun": r.get("dry_run") is True})
    return out


_MODS = ((64, "SUPER"), (4, "CTRL"), (8, "ALT"), (1, "SHIFT"))


def chord(mask, key) -> str:
    m = _num(mask)
    m = int(m) if math.isfinite(m) else 0
    parts = [n for bit, n in _MODS if m & bit]
    if key:
        parts.append(str(key))
    return "+".join(parts)


def binds_view(data) -> dict:
    d = data if isinstance(data, dict) else {}
    hk = d.get("hotkey") if isinstance(d.get("hotkey"), dict) else {}
    out = {"hotkey": str(hk["chord"]) if hk.get("chord") else "",
           "hyprland": d.get("hyprland") is True, "global": [],
           "submaps": [], "hasSubmap": False}
    for b in d.get("binds") if isinstance(d.get("binds"), list) else []:
        if not isinstance(b, dict):
            continue
        row = {"chord": chord(b.get("modmask"), b.get("key")),
               "arg": str(b.get("arg") or ""),
               "submap": str(b.get("submap") or "")}
        (out["submaps"] if row["submap"] else out["global"]).append(row)
    out["hasSubmap"] = bool(out["submaps"])
    return out


# -- view text (golden-tested) ------------------------------------------------

def _ui(key: str) -> str:
    return wcopy.string(key)


def _words(name) -> str:
    return str(name).replace("_", " ")


def _err_text(r: dict, cv) -> str:
    if r["code"] and r["code"] in wcopy.ERRORS:
        return wcopy.error_message(r["code"])
    if r["name"] == "cua" and cv is not None:
        return _ui("ui.cua." + cv["state"])
    return _words(r["code"]) if r["code"] else _ui("ui.bar.down")


def health_lines(health, spend, cua, models, notice: str = "") -> list:
    """[(text, role)] for the health view, the same rows as HealthSection."""
    sec, sp, cv = sections(health), spend_view(spend), cua_view(cua)
    out = [(_ui("ui.settings.health"), "head")]
    if notice:
        out.append(("  " + notice, "needsYou"))
    out.append(("  " + _ui("ui.health.endpoints"), "label"))
    if not sec["endpoints"]:
        out.append(("    " + _ui("ui.health.none"), "muted"))
    for e in sec["endpoints"]:
        detail = (f"{e['latencyMs']} ms" if e["latencyMs"] is not None
                  else _ui("ui.bar.ok")) if e["ok"] else _ui("ui.bar.down")
        out.append((f"    {'ok  ' if e['ok'] else 'DOWN'} "
                    f"{_words(e['name']):<18} {detail}",
                    "ok" if e["ok"] else "fail"))
    if sec["stt"] is not None:
        ok = sec["stt"]["ok"]
        out.append((f"    {'ok  ' if ok else 'DOWN'} "
                    f"{_ui('ui.health.stt'):<18} "
                    f"{_ui('ui.bar.ok') if ok else _ui('ui.bar.down')}",
                    "ok" if ok else "fail"))
    out.append(("  " + _ui("ui.health.cua"), "label"))
    if cv is not None:
        label = _ui("ui.cua." + cv["state"])
    elif sec["cua"] is not None:
        label = _ui("ui.bar.ok") if sec["cua"]["ok"] else _ui("ui.bar.down")
    else:
        label = _ui("ui.cua.unknown")
    good = sec["cua"]["ok"] if sec["cua"] else bool(cv and cv["live"])
    ver = (f"  {_ui('ui.health.version')} {cv['version']}"
           if cv and cv["version"] else "")
    out.append((f"    {'ok  ' if good else 'DOWN'} {label}{ver}",
                "ok" if good else "fail"))
    if cv and cv["fix"]:
        out.append((f"    {_ui('ui.health.fix')}: {cv['fix']}", "muted"))
    if cv and cv["kill"]:
        out.append(("    " + _ui("ui.cua.kill_switch_on"), "needsYou"))
    if cv and cv["dryRun"]:
        out.append(("    " + _ui("ui.cua.dry_run"), "needsYou"))
    out.append(("  " + _ui("ui.health.spend"), "label"))
    out += _spend_rows(sp, "    ")
    mrows = model_rows(models)
    if mrows:
        out.append(("    " + _ui("ui.health.models"), "muted"))
        for m in mrows:
            out.append((f"      {m['model']}  {m['calls']}  {m['usd']}",
                        "muted"))
    out.append(("  " + _ui("ui.health.errors"), "label"))
    if not sec["errors"]:
        out.append(("    " + _ui("ui.health.no_errors"), "muted"))
    for r in sec["errors"]:
        out.append((f"    {_words(r['name'])}: {_err_text(r, cv)}", "fail"))
    return out


def _spend_rows(sp: dict, pad: str) -> list:
    out = []
    if sp["has"]:
        cap = sp["cap"] if sp["cap"] else _ui("ui.spend.no_cap")
        out.append((f"{pad}{_ui('ui.spend.today')} {sp['today']} / {cap}",
                    "fail" if sp["blocked"] else "ok"))
        if sp["cap"]:
            fill = int(round(sp["ratio"] * 20))
            out.append((pad + "[" + "#" * fill + "." * (20 - fill) + "]",
                        "fail" if sp["blocked"] else "ember"))
        if sp["blocked"]:
            out.append((pad + _ui("ui.spend.blocked"), "fail"))
        mcap = sp["monthCap"] if sp["monthCap"] else _ui("ui.spend.no_cap")
        out.append((f"{pad}{_ui('ui.spend.month')} {sp['month']} / {mcap}",
                    "muted"))
    return out


def spend_lines(spend, models, notice: str = "") -> list:
    out = [(_ui("ui.manage.spend"), "head"),
           ("  " + _ui("ui.manage.spend.sub"), "muted")]
    if notice:
        out.append(("  " + notice, "needsYou"))
    out += _spend_rows(spend_view(spend), "  ")
    out.append(("  " + _ui("ui.health.models"), "label"))
    rows = spend_models(models)
    if not rows:
        out.append(("    " + _ui("ui.manage.spend.none"), "muted"))
    for m in rows:
        out.append((f"    {m['model']:<34} {m['calls']:>3} "
                    f"{_ui('ui.manage.spend.calls'):<5} "
                    f"{m['tokens']:>12} {m['usd']:>8}", "normal"))
    return out


def audit_lines(text: str, limit: int = 50) -> list:
    out = [(_ui("ui.manage.audit"), "head"),
           ("  " + _ui("ui.manage.audit.sub"), "muted")]
    rows = audit_rows(text, limit)
    if not rows:
        out.append(("  " + _ui("ui.manage.audit.none"), "muted"))
    for r in rows:
        word = _ui("ui.manage.audit." + r["decision"])
        out.append((f"  {r['time']:<8} {word:<8} {r['app'] or '-':<14} "
                    f"{r['tool']:<10} {r['ms']:>5} ms",
                    decision_tone(r["decision"])))
    return out


def binds_lines(data) -> list:
    v = binds_view(data)
    out = [(_ui("ui.manage.binds"), "head"),
           ("  " + _ui("ui.manage.binds.sub"), "muted"),
           (f"  {v['hotkey'] or '-':<18} {_ui('ui.manage.binds.hold')}",
            "normal")]
    if not v["hyprland"]:
        out.append(("  " + _ui("ui.manage.binds.no_hypr"), "needsYou"))
    out.append(("  " + _ui("ui.manage.binds.global"), "label"))
    if v["hyprland"] and not v["global"]:
        out.append(("    " + _ui("ui.manage.binds.none"), "muted"))
    for b in v["global"]:
        out.append((f"    {b['chord']:<18} {b['arg']}", "normal"))
    out.append(("  " + _ui("ui.manage.binds.submap"), "label"))
    if not v["hasSubmap"]:
        out.append(("    " + _ui("ui.manage.binds.no_submap"), "muted"))
    for b in v["submaps"]:
        out.append((f"    {b['chord']:<18} {b['submap']}  {b['arg']}",
                    "normal"))
    return out


def view_lines(view: str, data: dict) -> list:
    """Pure: [(text, role)] for one non-status view from the loaded data."""
    notice = data.get("notice", "")
    if view == "health":
        health = data.get("health") or health_from_endpoints(
            data.get("endpoints"))
        return health_lines(health, data.get("spend"), data.get("cua"),
                            data.get("models"), notice)
    if view == "spend":
        return spend_lines(data.get("spend"), data.get("models"), notice)
    if view == "audit":
        return audit_lines(data.get("audit", ""))
    if view == "binds":
        return binds_lines(data.get("binds"))
    return []


# -- data: one subscription, one-shot reads -----------------------------------

def apply_message(state: dict, msg: dict) -> dict:
    """Fold one push-stream message into the state dict (the Python side of
    shell-plugin/lib/state.js, for the fields the TUI shows)."""
    t = msg.get("type")
    if t == "snapshot":
        return dict(msg.get("state") or {})
    if t == "state":
        s = dict(state)
        s.update(msg.get("diff") or {})
        return s
    if t == "event" and msg.get("name") == "health_changed":
        d = msg.get("data") or {}
        if d.get("name"):
            s = dict(state)
            h = dict(s.get("health") or {})
            e = dict(h.get(d["name"]) or {})
            e["ok"] = bool(d.get("ok"))
            e["code"] = d.get("code")
            h[d["name"]] = e
            s["health"] = h
            return s
    return state


def fetch_json(argv: list, timeout: float = 20.0):
    """Run `wispd <argv> --json`; the data dict, or None. Exit codes 4 and 5
    (cua down, unhealthy) still carry data."""
    try:
        p = subprocess.run(
            [sys.executable, str(ROOT / "wispd"), *argv, "--json"],
            capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout).get("data")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def audit_text(max_bytes: int = 65536) -> str:
    """Tail of the cua audit log (read only)."""
    from . import cua_safety
    try:
        with open(cua_safety.audit_default_path(), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


class Feed:
    """The state subscription on a thread. Updates wake the UI through a
    pipe, so the loop blocks in select() and nothing polls. Reconnects back
    off 1, 2, 4 ... 15 s; offline is set while there is no snapshot."""

    def __init__(self):
        self.state, self.offline = {}, True
        self.rfd, self._wfd = os.pipe()
        os.set_blocking(self.rfd, False)
        self._stop = threading.Event()

    def wake(self):
        try:
            os.write(self._wfd, b"x")
        except OSError:
            pass

    def drain(self):
        try:
            while os.read(self.rfd, 4096):
                pass
        except OSError:
            pass

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self):
        delay = 1.0
        while not self._stop.is_set():
            try:
                for msg in ipc.subscribe(["state", "health", "tasks"]):
                    if msg.get("type") == "snapshot":
                        delay = 1.0
                        self.offline = False
                    self.state = apply_message(self.state, msg)
                    self.wake()
            except (OSError, ConnectionError, ValueError):
                pass
            self.offline = True
            self.wake()
            self._stop.wait(delay)
            delay = min(delay * 2, 15.0)


def _load(view: str, feed: Feed, data: dict, wake) -> None:
    """One-shot reads for a view, on a thread; results land in `data`."""
    def run():
        if view in ("health", "spend"):
            data["cua"] = fetch_json(["cua", "status"])
            sp = fetch_json(["spend"])
            data["models"] = (sp or {}).get("models", [])
            if view == "health" and feed.offline:
                data["endpoints"] = fetch_json(["health"])
        elif view == "binds":
            data["binds"] = fetch_json(["binds"])
        wake()
    threading.Thread(target=run, daemon=True).start()



def _footer(win, st) -> None:
    h, w = win.getmaxyx()
    win.addnstr(h - 1, 0,
                "1-5 views, y automate, n snooze, v never, c choice, "
                "l/x label, r reload, q quit", w - 1, st["muted"])


def _draw_view(win, view: str, state: dict, data: dict, offline: bool,
               styles: dict) -> None:
    """Draw a non-status view. Health and spend come from the state fields
    the app reads; the cua status and model table from the one-shot reads."""
    st = styles
    win.erase()
    h, w = win.getmaxyx()
    d = dict(data)
    if not offline:
        d["health"] = state.get("health") or {}
        d["spend"] = state.get("spend") or {}
    notice = wcopy.string("state.offline") if offline else ""
    d["notice"] = notice
    if view == "audit":
        d["audit"] = audit_text()
    for row, (text, role) in enumerate(view_lines(view, d)):
        if row >= h - 1:
            break
        win.addnstr(row, 0, text, w - 1, st.get(role, 0))
    _footer(win, st)
    win.refresh()


def _loop(win) -> int:
    curses.curs_set(0)
    styles = _init_styles()
    win.nodelay(True)
    feed = Feed()
    feed.start()
    view, data = 0, {}
    try:
        while True:
            state, offline = feed.state, feed.offline
            if VIEWS[view] == "status":
                try:
                    sug = suggest.pending()
                except Exception:
                    sug = []
                _draw(win, state, sug, _decisions_tail(), offline, styles)
            else:
                _draw_view(win, VIEWS[view], state, data, offline, styles)
            ready, _, _ = select.select([sys.stdin, feed.rfd], [], [])
            if feed.rfd in ready:
                feed.drain()
            while True:
                ch = win.getch()
                if ch == -1:
                    break
                if ch in (ord("q"), 27):
                    return 0
                if ord("1") <= ch <= ord("5") or ch in (9, ord("r")):
                    if ch == 9:
                        view = (view + 1) % len(VIEWS)
                    elif ch != ord("r"):
                        view = ch - ord("1")
                    data = {}
                    _load(VIEWS[view], feed, data, feed.wake)
                if ch == ord("c") and state.get("choices"):
                    _send({"cmd": "choice", "pick": state["choices"][0]})
                if ch in (ord("y"), ord("n"), ord("v")):
                    pick = {ord("y"): "suggestion:automate",
                            ord("n"): "suggestion:not now",
                            ord("v"): "suggestion:never"}[ch]
                    _send({"cmd": "choice", "pick": pick})
                if ch in (ord("l"), ord("x")):
                    _send({"cmd": "label",
                           "label": "correct" if ch == ord("l")
                           else "incorrect"})
    finally:
        feed.stop()


def main() -> int:
    try:
        return curses.wrapper(_loop)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
